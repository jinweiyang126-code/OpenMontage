"""BasicRouter text-to-video generation."""

from __future__ import annotations

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


class BasicrouterVideo(BaseTool):
    name = "basicrouter_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "basicrouter"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set BASICROUTER_API_KEY to your BasicRouter API key.\n"
        "  Get one at https://basicrouter.ai/"
    )
    agent_skills = ["ai-video-gen"]
    fallback_tools = ["image_selector"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "cinematic_quality": True,
    }
    best_for = [
        "single-key multimodal gateway video generation",
        "bilingual prompts (Chinese and English)",
        "text-to-video through one API bill",
    ]
    not_good_for = ["offline generation", "avatar/talking-head workflows"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "default": "text_to_video",
            },
            "model": {
                "type": "string",
                "description": "BasicRouter video model id. Defaults from config/basicrouter_models.yaml.",
            },
            "duration": {
                "type": ["string", "integer"],
                "default": "5",
                "description": "Duration in seconds",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "9:16", "1:1"],
                "default": "16:9",
            },
            "image_url": {
                "type": "string",
                "description": "Reference image URL for image_to_video",
            },
            "reference_image_path": {
                "type": "string",
                "description": "Local reference image path (uploaded when needed)",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "operation", "duration"]
    side_effects = ["writes video file to output_path", "calls BasicRouter API"]
    user_visible_verification = ["Watch generated clip for motion coherence and visual quality"]

    def get_status(self) -> ToolStatus:
        if br.get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            duration = float(inputs.get("duration", 5))
        except (TypeError, ValueError):
            duration = 5.0
        return round(0.08 * max(duration, 1.0), 3)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not br.get_api_key():
            return ToolResult(success=False, error="No BasicRouter API key. " + self.install_instructions)

        start = time.time()
        operation = inputs.get("operation", "text_to_video")
        model = inputs.get("model") or br.default_model("video", "default") or "seedance-2.0"
        output_path = Path(inputs.get("output_path", "basicrouter_video.mp4"))

        payload: dict[str, Any] = {
            "model": model,
            "prompt": inputs["prompt"],
            "duration": inputs.get("duration", 5),
            "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
            "resolution": inputs.get("resolution", "720p"),
            "operation": operation,
        }

        image_url = inputs.get("image_url")
        if operation == "image_to_video":
            if not image_url and inputs.get("reference_image_path"):
                try:
                    from tools.video._shared import upload_image_fal

                    image_url = upload_image_fal(inputs["reference_image_path"])
                except Exception as exc:
                    return ToolResult(
                        success=False,
                        error=f"Failed to upload reference image for image_to_video: {exc}",
                    )
            if image_url:
                payload["image_url"] = image_url
                payload["image"] = image_url

        try:
            result_data = br.create_video(payload)
            media_url = result_data.get("url") or br.extract_media_url(result_data)
            if not media_url:
                raise br.BasicRouterError("Video generation completed without a downloadable URL")
            br.download_url(media_url, output_path, timeout=300)
        except Exception as exc:
            return ToolResult(success=False, error=f"BasicRouter video generation failed: {exc}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": model,
                "prompt": inputs["prompt"],
                "operation": operation,
                "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
                "duration": payload["duration"],
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                "task_id": result_data.get("task_id"),
                "source_url": media_url,
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=model,
        )
