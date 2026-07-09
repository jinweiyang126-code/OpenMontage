"""HTTP client for BasicRouter multimodal API.

API base: https://api.basicrouter.ai/api
Docs: https://basicrouter.ai/docs
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import requests
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BASE_URL = "https://api.basicrouter.ai/api"
_MODEL_CONFIG_PATH = _PROJECT_ROOT / "config" / "basicrouter_models.yaml"

_TERMINAL_FAILURE = frozenset(
    {"failed", "failure", "error", "cancelled", "canceled", "expired"}
)
_TERMINAL_SUCCESS = frozenset({"succeeded", "success", "completed", "done", "ready"})


class BasicRouterError(RuntimeError):
    """Raised when BasicRouter returns a business-level error."""


def get_api_key() -> str | None:
    key = os.environ.get("BASICROUTER_API_KEY", "").strip()
    return key or None


def get_base_url() -> str:
    return os.environ.get("BASICROUTER_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def auth_headers() -> dict[str, str]:
    key = get_api_key()
    if not key:
        raise BasicRouterError(
            "BASICROUTER_API_KEY is not set. Get a key at https://basicrouter.ai/"
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def load_model_config() -> dict[str, Any]:
    if not _MODEL_CONFIG_PATH.is_file():
        return {}
    with open(_MODEL_CONFIG_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def default_model(category: str, profile: str = "default") -> str | None:
    config = load_model_config()
    section = config.get(category, {})
    if isinstance(section, dict):
        return section.get(profile) or section.get("default")
    return None


def default_voice(language: str) -> str:
    config = load_model_config()
    voices = config.get("voices", {}) if isinstance(config.get("voices"), dict) else {}
    lang = (language or "en").lower()
    if lang.startswith("zh"):
        return voices.get("zh", "nova")
    return voices.get("en", "alloy")


def _parse_envelope(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if "code" not in payload:
        return payload
    code = payload.get("code")
    if code not in (0, 200, "0", "200"):
        message = payload.get("message") or payload.get("msg") or "BasicRouter API error"
        raise BasicRouterError(str(message))
    return payload.get("data")


def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120,
) -> Any:
    url = f"{get_base_url()}{path}"
    response = requests.request(
        method,
        url,
        headers=auth_headers(),
        json=json_body,
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise BasicRouterError(f"Non-JSON response from {path}: {exc}") from exc

    if response.status_code >= 400 and "code" not in payload:
        message = payload.get("message") or payload.get("error") or response.text
        raise BasicRouterError(f"HTTP {response.status_code}: {message}")

    return _parse_envelope(payload)


def _extract_task_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("task_id", "taskId", "id", "job_id", "jobId"):
        value = data.get(key)
        if value:
            return str(value)
    nested = data.get("task")
    if isinstance(nested, dict):
        return _extract_task_id(nested)
    return None


def _extract_status(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("status", "state", "task_status"):
        value = data.get(key)
        if isinstance(value, str):
            return value.lower()
    nested = data.get("task")
    if isinstance(nested, dict):
        return _extract_status(nested)
    return None


def normalize_payload(payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Map OpenMontage-style fields to BasicRouter request bodies."""
    body = dict(payload)

    text = body.pop("text", None) or body.pop("prompt", None)
    if text:
        body["text"] = text

    if kind == "image":
        body.setdefault("count", 1)
        if "aspect_ratio" in body and "ratio" not in body:
            body["ratio"] = body.pop("aspect_ratio")
        width = body.pop("width", None)
        height = body.pop("height", None)
        if width and height and "resolution" not in body:
            body["resolution"] = f"{width}x{height}"
    elif kind == "video":
        body.setdefault("count", 1)
        body.setdefault("videoType", 1)
        body.setdefault("urls", [])
        if "aspect_ratio" in body and "ratio" not in body:
            body["ratio"] = body.pop("aspect_ratio")
        if "duration" in body:
            try:
                body["duration"] = int(float(body["duration"]))
            except (TypeError, ValueError):
                pass
        if body.get("operation") == "image_to_video":
            image_ref = body.pop("image_url", None) or body.pop("image", None)
            if image_ref:
                body["urls"] = [image_ref]
                body["videoType"] = 2
        body.pop("operation", None)
        body.pop("size", None)

    return body


def extract_media_url(data: Any) -> str | None:
    if isinstance(data, str) and data.startswith(("http://", "https://")):
        return data
    if not isinstance(data, dict):
        return None

    for key in ("url", "image_url", "video_url", "videoUrl", "output_url", "result_url", "content_url"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    for key in ("result", "output", "data"):
        nested = data.get(key)
        found = extract_media_url(nested)
        if found:
            return found

    for list_key in ("imageUrls", "videoUrls", "images", "videos", "generations", "outputs", "results", "assets"):
        items = data.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            found = extract_media_url(item)
            if found:
                return found

    b64 = data.get("b64_json") or data.get("base64")
    if isinstance(b64, str) and b64:
        return f"data:base64,{b64}"

    return None


def _poll_video_task(task_id: str, *, timeout_seconds: float, poll_interval: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    delay = poll_interval
    last_payload: dict[str, Any] = {}

    while time.time() < deadline:
        url = f"{get_base_url()}/ai/getVideoByTaskId"
        response = requests.get(
            url,
            headers=auth_headers(),
            params={"taskId": task_id},
            timeout=60,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            response.raise_for_status()
            raise BasicRouterError(f"Non-JSON poll response for task {task_id}: {exc}") from exc

        if response.status_code >= 400 and "code" not in payload:
            message = payload.get("message") or payload.get("error") or response.text
            raise BasicRouterError(f"HTTP {response.status_code}: {message}")

        data = _parse_envelope(payload)
        if isinstance(data, dict):
            last_payload = data
        else:
            last_payload = {"raw": data}

        status = _extract_status(last_payload)
        media_url = extract_media_url(last_payload)
        if media_url:
            return {**last_payload, "url": media_url}

        if status in _TERMINAL_SUCCESS:
            media_url = extract_media_url(last_payload)
            if media_url:
                return {**last_payload, "url": media_url}
            raise BasicRouterError(
                f"Task {task_id} succeeded but no media URL was returned"
            )

        if status in _TERMINAL_FAILURE:
            message = (
                last_payload.get("message")
                or last_payload.get("error")
                or f"Task {task_id} failed with status {status}"
            )
            raise BasicRouterError(str(message))

        time.sleep(delay)
        delay = min(delay * 1.4, 20.0)

    raise BasicRouterError(f"Timed out polling task {task_id} after {timeout_seconds:.0f}s")


def poll_async_task(
    task_id: str,
    *,
    timeout_seconds: float | None = None,
    poll_interval: float = 3.0,
    kind: str = "video",
) -> dict[str, Any]:
    if timeout_seconds is None:
        timeout_seconds = float(os.environ.get("BASICROUTER_POLL_TIMEOUT", "600"))

    if kind == "video":
        return _poll_video_task(task_id, timeout_seconds=timeout_seconds, poll_interval=poll_interval)

    deadline = time.time() + timeout_seconds
    delay = poll_interval
    last_payload: dict[str, Any] = {}

    while time.time() < deadline:
        for body in ({"taskId": task_id}, {"task_id": task_id}):
            try:
                data = _request_json("POST", "/ai/getAsyncResponse", json_body=body, timeout=60)
            except BasicRouterError:
                data = _request_json(
                    "POST",
                    "/v1/getAsyncResponse",
                    json_body=body,
                    timeout=60,
                )
            if isinstance(data, dict):
                last_payload = data
            else:
                last_payload = {"raw": data}

            status = _extract_status(last_payload)
            media_url = extract_media_url(last_payload)
            if media_url:
                return {**last_payload, "url": media_url}

            if status in _TERMINAL_SUCCESS:
                media_url = extract_media_url(last_payload)
                if media_url:
                    return {**last_payload, "url": media_url}
                raise BasicRouterError(
                    f"Task {task_id} succeeded but no media URL was returned"
                )

            if status in _TERMINAL_FAILURE:
                message = (
                    last_payload.get("message")
                    or last_payload.get("error")
                    or f"Task {task_id} failed with status {status}"
                )
                raise BasicRouterError(str(message))

        time.sleep(delay)
        delay = min(delay * 1.4, 20.0)

    raise BasicRouterError(f"Timed out polling task {task_id} after {timeout_seconds:.0f}s")


def create_image(payload: dict[str, Any]) -> dict[str, Any]:
    body = normalize_payload(payload, kind="image")
    data = _request_json("POST", "/ai/createImage", json_body=body, timeout=360)
    if not isinstance(data, dict):
        data = {"raw": data}
    media_url = extract_media_url(data)
    if media_url:
        return {**data, "url": media_url}

    task_id = _extract_task_id(data)
    if not task_id:
        raise BasicRouterError("createImage returned neither a URL nor a task id")
    polled = poll_async_task(task_id, kind="image")
    return {**data, **polled, "task_id": task_id}


def create_video(payload: dict[str, Any]) -> dict[str, Any]:
    body = normalize_payload(payload, kind="video")
    data = _request_json("POST", "/ai/createVideo", json_body=body, timeout=120)
    if not isinstance(data, dict):
        data = {"raw": data}
    media_url = extract_media_url(data)
    if media_url:
        return {**data, "url": media_url}

    task_id = _extract_task_id(data)
    if not task_id:
        raise BasicRouterError("createVideo returned neither a URL nor a task id")
    polled = poll_async_task(task_id, kind="video")
    return {**data, **polled, "task_id": task_id}


def download_url(url: str, output_path: Path, *, timeout: float = 180) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("data:base64,"):
        output_path.write_bytes(base64.b64decode(url.split(",", 1)[1]))
        return

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    output_path.write_bytes(response.content)


def synthesize_speech(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    url = f"{get_base_url()}/v1/audio/speech"
    response = requests.post(
        url,
        headers=auth_headers(),
        json=payload,
        timeout=180,
    )

    content_type = (response.headers.get("Content-Type") or "").lower()
    if response.status_code >= 400:
        try:
            envelope = response.json()
            _parse_envelope(envelope)
        except BasicRouterError:
            raise
        except ValueError:
            response.raise_for_status()

    if "application/json" in content_type:
        data = _parse_envelope(response.json())
        if not isinstance(data, dict):
            data = {"raw": data}
        media_url = extract_media_url(data)
        if not media_url:
            raise BasicRouterError("audio/speech JSON response did not include audio URL")
        download_url(media_url, output_path)
        return data

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return {"format": payload.get("response_format", "mp3")}
