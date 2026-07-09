"""Shared TTS fallback routing for BasicRouter and other providers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from tools.base_tool import ToolResult, ToolStatus

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "tts_fallback.yaml"


def fallback_enabled() -> bool:
    env = os.environ.get("TTS_FALLBACK_ENABLED", "").strip().lower()
    if env in {"0", "false", "no"}:
        return False
    if env in {"1", "true", "yes"}:
        return True
    config = load_fallback_config()
    return bool(config.get("enabled", True))


def load_fallback_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {"enabled": True, "chains": {}, "piper": {}}
    with open(_CONFIG_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def normalize_language(language: str | None, text: str | None = None) -> str:
    value = (language or "en").strip().lower()
    if value == "auto" and text:
        if any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return "zh"
        return "en"
    if value in {"zh", "zh-cn", "zh_cn", "chinese", "mandarin", "cmn"}:
        return "zh"
    return "en"


def piper_settings(language: str | None = None, text: str | None = None) -> dict[str, str]:
    config = load_fallback_config()
    piper_cfg = config.get("piper", {}) if isinstance(config.get("piper"), dict) else {}
    models = piper_cfg.get("models", {}) if isinstance(piper_cfg.get("models"), dict) else {}
    lang = normalize_language(language, text)
    data_dir = str(_PROJECT_ROOT / piper_cfg.get("data_dir", "config/piper_models"))
    model = models.get(lang) or piper_cfg.get("default_model", "en_US-lessac-medium")
    return {"data_dir": data_dir, "model": model, "language": lang}


def get_fallback_chain(language: str | None = None, text: str | None = None) -> list[str]:
    config = load_fallback_config()
    chains = config.get("chains", {}) if isinstance(config.get("chains"), dict) else {}
    lang = normalize_language(language, text)
    chain = chains.get(lang) or chains.get("en") or ["piper_tts"]
    return [str(name) for name in chain]


def prepare_fallback_inputs(tool_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(inputs)
    language = payload.get("language")
    text = payload.get("text")
    lang = normalize_language(language, text if isinstance(text, str) else None)

    if tool_name == "piper_tts":
        piper = piper_settings(language, text if isinstance(text, str) else None)
        payload.setdefault("model", piper["model"])
        payload.setdefault("data_dir", piper["data_dir"])
        payload.setdefault("language", lang)
        if not payload.get("output_path"):
            payload["output_path"] = f"narration_{lang}.wav"
        elif str(payload["output_path"]).endswith(".mp3"):
            payload["output_path"] = str(Path(payload["output_path"]).with_suffix(".wav"))
    elif tool_name == "dashscope_tts":
        payload.setdefault("language_type", "Chinese" if lang == "zh" else "English")
    elif tool_name == "openai_tts":
        payload.setdefault("voice", "nova" if lang == "zh" else "alloy")

    return payload


def execute_fallback_chain(
    inputs: dict[str, Any],
    *,
    failed_tool: str,
    primary_error: str,
    chain: list[str] | None = None,
) -> ToolResult:
    from tools.tool_registry import registry

    registry.ensure_discovered()
    language = inputs.get("language")
    text = inputs.get("text")
    candidates = chain or get_fallback_chain(language, text if isinstance(text, str) else None)
    errors: list[str] = [f"{failed_tool}: {primary_error}"]

    for tool_name in candidates:
        if tool_name == failed_tool:
            continue
        tool = registry.get(tool_name)
        if tool is None or tool.get_status() != ToolStatus.AVAILABLE:
            continue

        payload = prepare_fallback_inputs(tool_name, inputs)
        result = tool.execute(payload)
        if result.success:
            result.data = dict(result.data or {})
            result.data["fallback_from"] = failed_tool
            result.data["fallback_tool"] = tool_name
            result.data["fallback_reason"] = primary_error
            result.data["language"] = normalize_language(language, text if isinstance(text, str) else None)
            return result
        errors.append(f"{tool_name}: {result.error or 'unknown error'}")

    return ToolResult(
        success=False,
        error="TTS fallback chain exhausted. " + " | ".join(errors),
    )
