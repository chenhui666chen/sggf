# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Dict

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_BASE, require_api_key
from adapters._shared_vision_review import VisionReviewMixin
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 4. 文本对话 - 百炼OpenAI兼容接口
# ============================================================


def _openai_compatible_client() -> Any:
    import openai

    return openai.OpenAI(
        api_key=require_api_key("DASHSCOPE_API_KEY"),
        base_url=f"{DASHSCOPE_BASE}/compatible-mode/v1",
    )


class _DashScopeVisionReviewMixin(VisionReviewMixin):
    """百炼 compatible-mode 侧的视觉评审档位，请求结构与执行层见 adapters/_shared_vision_review。"""

    def _vision_client(self) -> Any:
        return _openai_compatible_client()

    def _vision_disable_thinking_kwargs(self) -> Dict[str, Any]:
        # 百炼兼容接口用顶层 enable_thinking 关闭思考链
        return {"extra_body": {"enable_thinking": False}}


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
    """同族轻量档：百炼 compatible-mode 下走 chat completions，注册后档案才可执行。"""

    MODEL_ID = "qwen3.5-omni-flash"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.5-omni-flash", name="Qwen 3.5 Omni Flash", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=3.0,
        )


@register_model("qwen-plus")
class Qwen37PlusAdapter(_DashScopeVisionReviewMixin, _DashScopeChatAdapter):
    """Qwen3.7 Plus 档案已声明 image/video_understanding，compatible-mode 下可直接做视觉评审。

    实测：图片 11.1s、视频 10.9s 且 JSON 可解析；同一请求开启深度思考要 40.1s，故关闭。
    """

    MODEL_ID = "qwen-plus"
    DISABLE_THINKING = True

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-plus", name="Qwen 3.7 Plus", provider="alibaba", version="3.7 Plus",
            status=ModelStatus.ACTIVE,
            modality=["text_to_text", "image_understanding", "video_understanding"],
            avg_latency_seconds=11.0,
        )


@register_model("qwen3.8-omni-flash")
class Qwen38OmniFlashAdapter(_DashScopeVisionReviewMixin, _DashScopeChatAdapter):
    """Qwen3.8 Omni Flash：官方 request_modality 为 Text/Image/Audio/Video，输出仅文本。

    实测：生产评审提示词下图片 6.4s、视频 4.3s 且 JSON 可解析；默认开思考（reasoning_effort=xhigh）
    要 22.3s/12.4s 并多吃 1655/651 reasoning tokens，故关闭。
    """

    MODEL_ID = "qwen3.8-omni-flash"
    DISABLE_THINKING = True

    def _vision_disable_thinking_kwargs(self) -> Dict[str, Any]:
        # 本档不吃顶层 enable_thinking（那是 Qwen3.7/3.6/3.5/Qwen3-Omni-Flash/Qwen3-VL 的写法），
        # 官方用 OpenAI 标准参数 reasoning_effort，SDK 顶层直传
        return {"reasoning_effort": "none"}

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.8-omni-flash", name="Qwen 3.8 Omni Flash", provider="alibaba", version="v3.8",
            status=ModelStatus.ACTIVE,
            modality=["text_to_text", "image_understanding", "video_understanding"],
            avg_latency_seconds=6.5,
        )


