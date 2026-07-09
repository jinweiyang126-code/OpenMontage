"""BasicRouter text-to-image generation."""

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


class BasicrouterImage(BaseTool):
    name = "basicrouter_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "basicrouter"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set BASICROUTER_API_KEY to your BasicRouter API key.\n"
        "  Get one at https://basicrouter.ai/\n"
        "Optional: BASICROUTER_BASE_URL (default https://api.basicrouter.ai/api)"
    )
    agent_skills = ["flux-best-practices"]

    capabilities = ["generate_image", "text_to_image"]
    supports = {
        "negative_prompt": False,
        "seed": True,
        "custom_size": True,
        "aspect_ratio": True,
    }
    best_for = [
        "single-key multimodal gateway image generation",
        "bilingual prompts (Chinese and English)",
        "routing multiple image model families through one API key",
    ]
    not_good_for = ["offline generation", "providers without BasicRouter model access"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "description": "BasicRouter image model id. Defaults from config/basicrouter_models.yaml.",
            },
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "aspect_ratio": {
                "type": "string",
                "description": "Aspect ratio hint, e.g. 16:9, 9:16, 1:1.",
            },
            "seed": {"type": "integer"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "width", "height", "seed", "model"]
    side_effects = ["writes image file to output_path", "calls BasicRouter API"]
    user_visible_verification = ["Inspect generated image for relevance and quality"]

    def get_status(self) -> ToolStatus:
        if br.get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.04

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not br.get_api_key():
            return ToolResult(success=False, error="No BasicRouter API key. " + self.install_instructions)

        start = time.time()
        prompt = inputs["prompt"]
        width = int(inputs.get("width", 1024))
        height = int(inputs.get("height", 1024))
        model = inputs.get("model") or br.default_model("image", "default") or "gpt-image-2"
        output_path = Path(inputs.get("output_path", "basicrouter_image.png"))

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "size": f"{width}x{height}",
        }
        if inputs.get("aspect_ratio"):
            payload["aspect_ratio"] = inputs["aspect_ratio"]
        if inputs.get("seed") is not None:
            payload["seed"] = inputs["seed"]

        try:
            result_data = br.create_image(payload)
            media_url = result_data.get("url") or br.extract_media_url(result_data)
            if not media_url:
                raise br.BasicRouterError("Image generation completed without a downloadable URL")
            br.download_url(media_url, output_path)
        except Exception as exc:
            return ToolResult(success=False, error=f"BasicRouter image generation failed: {exc}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "aspect_ratio": inputs.get("aspect_ratio"),
                "output": str(output_path),
                "output_path": str(output_path),
                "task_id": result_data.get("task_id"),
                "source_url": media_url,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=model,
            seed=inputs.get("seed"),
        )
