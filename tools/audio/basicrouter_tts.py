"""BasicRouter text-to-speech via OpenAI-compatible /v1/audio/speech."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from lib import basicrouter_client as br
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


def _normalize_language(language: str | None) -> str:
    value = (language or "en").strip().lower()
    if value in {"zh", "zh-cn", "zh_cn", "chinese", "mandarin", "cmn"}:
        return "zh"
    return "en"


class BasicrouterTTS(BaseTool):
    name = "basicrouter_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "basicrouter"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set BASICROUTER_API_KEY to your BasicRouter API key.\n"
        "  Get one at https://basicrouter.ai/"
    )
    fallback = "piper_tts"
    fallback_tools = ["piper_tts", "openai_tts", "dashscope_tts"]
    agent_skills = []

    capabilities = [
        "text_to_speech",
        "voice_selection",
        "multilingual",
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
    }
    best_for = [
        "English and Chinese narration through a single BasicRouter API key",
        "gateway-routed OpenAI-compatible speech synthesis",
    ]
    not_good_for = [
        "fully offline production",
        "voice clone matching",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "language": {
                "type": "string",
                "enum": ["en", "zh", "auto"],
                "default": "auto",
                "description": "Narration language. zh selects Chinese delivery defaults.",
            },
            "voice": {
                "type": "string",
                "description": "Speech voice name. Defaults from config/basicrouter_models.yaml.",
            },
            "model": {
                "type": "string",
                "description": "Speech model routed by BasicRouter.",
            },
            "format": {
                "type": "string",
                "default": "mp3",
                "enum": ["mp3", "wav", "pcm", "opus", "aac", "flac"],
            },
            "response_format": {
                "type": "string",
                "default": "mp3",
                "enum": ["mp3", "wav", "pcm", "opus", "aac", "flac"],
            },
            "instructions": {
                "type": "string",
                "description": "Optional delivery instructions for gpt-4o-mini-tts style models.",
            },
            "speed": {
                "type": "number",
                "default": 1.0,
                "minimum": 0.25,
                "maximum": 4.0,
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["text", "voice", "model", "language", "format", "response_format"]
    side_effects = ["writes audio file to output_path", "calls BasicRouter API"]
    user_visible_verification = ["Listen to generated audio for intelligibility and tone"]

    def get_status(self) -> ToolStatus:
        if not br.get_api_key():
            return ToolStatus.UNAVAILABLE
        enabled = os.environ.get("BASICROUTER_TTS_ENABLED", "").strip().lower()
        if enabled in {"0", "false", "no"}:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return round(len(inputs.get("text", "")) * 0.000015, 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not br.get_api_key():
            return ToolResult(success=False, error="No BasicRouter API key. " + self.install_instructions)

        start = time.time()
        text = inputs["text"]
        language = _normalize_language(inputs.get("language"))
        fmt = inputs.get("response_format") or inputs.get("format", "mp3")
        voice = inputs.get("voice") or br.default_voice(language)
        model = (
            inputs.get("model")
            or br.default_model("tts", language)
            or br.default_model("tts", "default")
            or "gpt-4o-mini-tts"
        )
        output_path = Path(inputs.get("output_path", f"basicrouter_tts.{fmt}"))

        payload: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": fmt,
        }
        if inputs.get("speed") and float(inputs["speed"]) != 1.0:
            payload["speed"] = float(inputs["speed"])

        instructions = inputs.get("instructions")
        if not instructions and language == "zh":
            instructions = "Speak in natural, clear Mandarin Chinese with calm documentary pacing."
        if instructions:
            payload["instructions"] = instructions

        try:
            br.synthesize_speech(payload, output_path)
        except Exception as exc:
            from lib.tts_fallback import execute_fallback_chain, fallback_enabled

            if not fallback_enabled():
                return ToolResult(success=False, error=f"BasicRouter TTS failed: {exc}")

            fallback = execute_fallback_chain(
                inputs,
                failed_tool=self.name,
                primary_error=str(exc),
                chain=self.fallback_tools,
            )
            if fallback.success:
                return fallback
            return ToolResult(
                success=False,
                error=f"BasicRouter TTS failed: {exc}. {fallback.error}",
            )

        from tools.analysis.audio_probe import probe_duration

        audio_duration = probe_duration(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": model,
                "voice": voice,
                "language": language,
                "format": fmt,
                "response_format": fmt,
                "instructions": instructions,
                "speed": inputs.get("speed", 1.0),
                "text_length": len(text),
                "audio_duration_seconds": round(audio_duration, 2) if audio_duration else None,
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=model,
        )
