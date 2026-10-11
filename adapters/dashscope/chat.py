# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_BASE, _encode_image, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 4. 文本对话 - 百炼OpenAI兼容接口
# ============================================================

_VISION_DEFAULT_CRITERIA: Dict[str, List[str]] = {
    "image": ["clarity", "composition", "lighting", "color", "style"],
    "video": ["clarity", "smoothness", "consistency", "lighting", "color"],
}
_VISION_MAX_TOKENS = 1200
_VIDEO_MIME_TYPES: Dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


def _openai_compatible_client() -> Any:
    import openai

    return openai.OpenAI(
        api_key=require_api_key("DASHSCOPE_API_KEY"),
        base_url=f"{DASHSCOPE_BASE}/compatible-mode/v1",
    )


def _resolve_image_asset_url(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        raise RuntimeError("image_path is required")
    if value.startswith(("http://", "https://", "data:")):
        return value
    encoded = _encode_image(value)
    if encoded == value:
        # _encode_image 对读不到的本地路径原样返回，这里换成明确报错，
        # 否则会把一个无效文件名当成 URL 发给上游
        raise RuntimeError(f"image not found: {value}")
    return encoded


def _resolve_video_asset_url(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        raise RuntimeError("video_path is required")
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        raise RuntimeError(f"video not found: {value}")
    mime = _VIDEO_MIME_TYPES.get(path.suffix.lower(), "video/mp4")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"


def _build_vision_review_prompt(*, asset_kind: str, analysis_type: str, criteria: List[str]) -> str:
    asset_label = "视频" if asset_kind == "video" else "图片"
    return (
        f"你是素材质量评审员。请对这段{asset_label}做{analysis_type}评审，"
        "按给定维度逐项打分（0-10 分，可含小数）并给出可执行的修改建议。\n"
        f"评分维度：{', '.join(criteria)}\n"
        "只输出 JSON，不要任何额外文字，格式为："
        '{"scores": {"<维度>": {"score": 分数, "comment": "简述"}}, '
        '"summary": "整体结论", "strengths": ["优点"], "issues": ["问题"], '
        '"revised_prompt": "用于重新生成该素材的优化提示词"}'
    )


def _parse_vision_review_content(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class _DashScopeVisionReviewMixin:
    """视觉理解档位：把素材与评审维度一起送进百炼 compatible-mode 多模态对话。

    媒体运行时按 adapter 上的同名方法执行 analyze_image / analyze_video，
    未混入本类的纯文本档位不应暴露这两个方法。
    """

    MODEL_ID = ""

    def _run_vision_review(
        self,
        *,
        parts: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> GenerationResult:
        start = time.time()
        try:
            client = _openai_compatible_client()
            response = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": parts}],
                max_tokens=_VISION_MAX_TOKENS,
            )
            content = response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(exc), latency=time.time() - start,
            )

        payload = _parse_vision_review_content(content) or {"content": content}
        return GenerationResult(
            success=True, task_id="", model_id=self.spec.id,
            outputs=[content],
            metadata={**metadata, "content": content, "result_data": payload},
            latency=time.time() - start,
        )

    def analyze_image(
        self,
        *,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> GenerationResult:
        names = [str(item) for item in (criteria or _VISION_DEFAULT_CRITERIA["image"])]
        parts = [
            {"type": "image_url", "image_url": {"url": _resolve_image_asset_url(image_path)}},
            {
                "type": "text",
                "text": _build_vision_review_prompt(
                    asset_kind="image", analysis_type=analysis_type, criteria=names
                ),
            },
        ]
        return self._run_vision_review(
            parts=parts,
            metadata={"image_path": image_path, "analysis_type": analysis_type, "criteria": names},
        )

    def analyze_video(
        self,
        *,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> GenerationResult:
        names = [str(item) for item in (criteria or _VISION_DEFAULT_CRITERIA["video"])]
        parts = [
            {"type": "video_url", "video_url": {"url": _resolve_video_asset_url(video_path)}},
            {
                "type": "text",
                "text": _build_vision_review_prompt(
                    asset_kind="video", analysis_type=analysis_type, criteria=names
                ),
            },
        ]
        return self._run_vision_review(
            parts=parts,
            metadata={"video_path": video_path, "analysis_type": analysis_type, "criteria": names},
        )


class _DashScopeChatAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            client = _openai_compatible_client()
            response = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": prompt or "你好"}],
                max_tokens=200,
            )
            content = response.choices[0].message.content or ""
            return GenerationResult(
                success=bool(content), task_id="", model_id=self.spec.id,
                outputs=[content], error=None if content else "Empty response",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen3.5-omni-plus")
class Qwen35OmniPlusAdapter(_DashScopeVisionReviewMixin, _DashScopeChatAdapter):
    MODEL_ID = "qwen3.5-omni-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.5-omni-plus", name="Qwen 3.5 Omni Plus", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


@register_model("qwen3.6-plus")
class Qwen36PlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3.6-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.6-plus", name="Qwen 3.6 Plus", provider="alibaba", version="v3.6",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


@register_model("qwen3.5-omni-flash")
class Qwen35OmniFlashAdapter(_DashScopeChatAdapter):
    """与 omni-plus 同族：百炼 compatible-mode 下走 chat completions，注册后档案才可执行。"""

    MODEL_ID = "qwen3.5-omni-flash"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.5-omni-flash", name="Qwen 3.5 Omni Flash", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=3.0,
        )


