"""Tests for BasicRouter provider tools and client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.base_tool import ToolStatus


@pytest.fixture
def api_key_env(monkeypatch):
    monkeypatch.setenv("BASICROUTER_API_KEY", "test-basicrouter-key")


def test_basicrouter_tools_discovered(api_key_env):
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()

    for name in ("basicrouter_image", "basicrouter_video"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.provider == "basicrouter"
        assert tool.get_status() == ToolStatus.AVAILABLE

    tts_tool = registry.get("basicrouter_tts")
    assert tts_tool is not None
    assert tts_tool.provider == "basicrouter"


def test_basicrouter_image_execute_downloads_result(api_key_env, tmp_path, monkeypatch):
    from tools.graphics.basicrouter_image import BasicrouterImage

    output_path = tmp_path / "shot.png"
    monkeypatch.setattr(
        "lib.basicrouter_client.create_image",
        lambda payload: {"url": "https://example.com/image.png", "task_id": "img_1"},
    )

    downloaded: list[str] = []

    def fake_download(url: str, path: Path, **kwargs):
        downloaded.append(url)
        path.write_bytes(b"png-bytes")

    monkeypatch.setattr("lib.basicrouter_client.download_url", fake_download)

    result = BasicrouterImage().execute(
        {
            "prompt": "A calm mountain lake at dawn",
            "width": 1280,
            "height": 720,
            "output_path": str(output_path),
        }
    )

    assert result.success, result.error
    assert output_path.read_bytes() == b"png-bytes"
    assert downloaded == ["https://example.com/image.png"]
    assert result.data["provider"] == "basicrouter"


def test_basicrouter_video_polls_async_task(api_key_env, tmp_path, monkeypatch):
    from tools.video.basicrouter_video import BasicrouterVideo

    output_path = tmp_path / "clip.mp4"
    monkeypatch.setattr(
        "lib.basicrouter_client.create_video",
        lambda payload: {
            "task_id": "vid_123",
            "url": "https://example.com/video.mp4",
        },
    )
    monkeypatch.setattr(
        "lib.basicrouter_client.download_url",
        lambda url, path, **kwargs: path.write_bytes(b"mp4-bytes"),
    )
    monkeypatch.setattr(
        "tools.video._shared.probe_output",
        lambda path: {"duration_seconds": 5.0, "width": 1280, "height": 720},
    )

    result = BasicrouterVideo().execute(
        {
            "prompt": "Ocean waves at sunset",
            "duration": "5",
            "output_path": str(output_path),
        }
    )

    assert result.success, result.error
    assert output_path.read_bytes() == b"mp4-bytes"
    assert result.data["task_id"] == "vid_123"


def test_basicrouter_tts_chinese_defaults(api_key_env, tmp_path, monkeypatch):
    from tools.audio.basicrouter_tts import BasicrouterTTS

    output_path = tmp_path / "narration.mp3"
    captured: dict = {}

    def fake_speech(payload, path):
        captured.update(payload)
        path.write_bytes(b"mp3-bytes")

    monkeypatch.setattr("lib.basicrouter_client.synthesize_speech", fake_speech)
    monkeypatch.setattr("tools.analysis.audio_probe.probe_duration", lambda path: 12.5)

    result = BasicrouterTTS().execute(
        {
            "text": "互联网改变了世界。",
            "language": "zh",
            "output_path": str(output_path),
        }
    )

    assert result.success, result.error
    assert output_path.read_bytes() == b"mp3-bytes"
    assert result.data["language"] == "zh"
    assert "Mandarin Chinese" in (captured.get("instructions") or "")


def test_client_parse_envelope_rejects_error():
    from lib.basicrouter_client import BasicRouterError, _parse_envelope

    with pytest.raises(BasicRouterError, match="Invalid API Key"):
        _parse_envelope({"code": 401, "message": "Invalid API Key", "data": None})


def test_client_extract_media_url_nested():
    from lib.basicrouter_client import extract_media_url

    assert (
        extract_media_url({"generations": [{"url": "https://example.com/a.png"}]})
        == "https://example.com/a.png"
    )
    assert (
        extract_media_url({"imageUrls": ["https://example.com/b.png"]})
        == "https://example.com/b.png"
    )
    assert (
        extract_media_url({"status": "succeeded", "videoUrl": "https://example.com/c.mp4"})
        == "https://example.com/c.mp4"
    )


def test_basicrouter_tts_falls_back_to_piper(api_key_env, tmp_path, monkeypatch):
    from tools.audio.basicrouter_tts import BasicrouterTTS

    output_path = tmp_path / "narration.wav"
    monkeypatch.setenv("TTS_FALLBACK_ENABLED", "true")

    def fail_speech(payload, path):
        raise RuntimeError("speech endpoint unavailable")

    monkeypatch.setattr("lib.basicrouter_client.synthesize_speech", fail_speech)

    result = BasicrouterTTS().execute(
        {
            "text": "互联网改变了世界。",
            "language": "zh",
            "output_path": str(output_path),
        }
    )

    assert result.success, result.error
    assert output_path.exists()
    assert result.data.get("fallback_tool") == "piper_tts"
    assert result.data.get("language") == "zh"


def test_piper_tts_generates_chinese(tmp_path):
    from tools.audio.piper_tts import PiperTTS

    output_path = tmp_path / "zh.wav"
    result = PiperTTS().execute(
        {
            "text": "互联网正在改变我们的生活方式。",
            "language": "zh",
            "output_path": str(output_path),
        }
    )
    assert result.success, result.error
    assert output_path.stat().st_size > 1000
    from lib.basicrouter_client import normalize_payload

    image_body = normalize_payload(
        {"model": "gpt-image-2", "prompt": "sunset", "width": 1024, "height": 1024},
        kind="image",
    )
    assert image_body["text"] == "sunset"
    assert image_body["count"] == 1
    assert image_body["resolution"] == "1024x1024"

    video_body = normalize_payload(
        {
            "model": "seedance-2.0",
            "prompt": "waves",
            "duration": "5",
            "aspect_ratio": "16:9",
            "operation": "text_to_video",
        },
        kind="video",
    )
    assert video_body["text"] == "waves"
    assert video_body["ratio"] == "16:9"
    assert video_body["duration"] == 5
    assert video_body["videoType"] == 1
