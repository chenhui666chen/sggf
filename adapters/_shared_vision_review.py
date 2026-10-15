# -*- coding: utf-8 -*-
"""视觉评审的供应商中立执行层。

媒体运行时把 analyze_image / analyze_video 交给 adapter 上的同名方法执行
（`core/unified_media_runtime.py::_execute_custom_registry_method`），注册表里只有
adapter 而没有方法时，视觉识别入口只能拿到 adapter_missing。

百炼 compatible-mode 与火山方舟两家的多模态消息结构一致，差异只剩两点：
用哪个 base_url / 密钥，以及"关闭深度思考"的载荷写法。因此素材编码、评审提示词、
结果解析收敛在本文件，供应商子类只实现 `_vision_client` 与
`_vision_disable_thinking_kwargs` 两个钩子。
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import GenerationResult
from adapters._shared import _encode_image

VISION_DEFAULT_CRITERIA: Dict[str, List[str]] = {
    "image": ["clarity", "composition", "lighting", "color", "style"],
    "video": ["clarity", "smoothness", "consistency", "lighting", "color"],
}
VISION_MAX_TOKENS = 1200
# 三档评审在同一批素材上实测出的共同失效模式：只给维度名时，模型按"看着顺眼"打分——
# 整段偏暗的素材 lighting 给到 9.8（把氛围感当成曝光准确），后 4 秒完全静止的素材
# smoothness 给到 8.5（把镜头不动当成画面稳定），且提高抽帧率到 8fps 判分不变。
# 因此把每个维度的扣分下限写进提示词，让"缺陷"必须落到分数上。
VISION_CRITERION_RUBRICS: Dict[str, str] = {
    "clarity": "主体或整体模糊、失焦、重影时不得高于 5 分。",
    "lighting": "只评曝光是否准确：整体偏暗、欠曝、死黑或过曝时不得高于 5 分，不得因光影有氛围感而给高分。",
    "smoothness": "同一画面被长时间重复（真正的冻结帧、跳帧、突兀运动）时不得高于 5 分；慢动作、缓慢运镜等合理低运动量不扣分。",
    "consistency": "主体造型、场景元素、文字或物体位置在时间轴上突变（消失、跳变、漂移）时不得高于 6 分。",
    "color": "整体偏色、脏灰、色彩断层时不得高于 6 分。",
    "composition": "主体残缺、错误裁切或画面拥挤时不得高于 6 分。",
    "style": "风格或材质在片段内跳变时不得高于 6 分。",
}
VIDEO_MIME_TYPES: Dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


def resolve_image_asset_url(path_text: str) -> str:
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


def resolve_video_asset_url(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        raise RuntimeError("video_path is required")
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        raise RuntimeError(f"video not found: {value}")
    mime = VIDEO_MIME_TYPES.get(path.suffix.lower(), "video/mp4")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"


def build_vision_review_prompt(*, asset_kind: str, analysis_type: str, criteria: List[str]) -> str:
    asset_label = "视频" if asset_kind == "video" else "图片"
    rubric = "\n".join(
        f"- {name}: {VISION_CRITERION_RUBRICS[name]}" for name in criteria if name in VISION_CRITERION_RUBRICS
    )
    return (
        f"你是素材质量评审员。请对这段{asset_label}做{analysis_type}评审，"
        "按给定维度逐项打分（0-10 分，可含小数）并给出可执行的修改建议。\n"
        f"评分维度：{', '.join(criteria)}\n"
        f"各维度扣分约束：\n{rubric}\n"
        "comment 必须写你在画面里看到的具体证据，未发现缺陷的维度才可以给 8 分以上。\n"
        "只输出 JSON，不要任何额外文字，格式为："
        '{"scores": {"<维度>": {"score": 分数, "comment": "简述"}}, '
        '"summary": "整体结论", "strengths": ["优点"], "issues": ["问题"], '
        '"revised_prompt": "用于重新生成该素材的优化提示词"}'
    )


def parse_vision_review_content(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    candidate = raw[start : end + 1]
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        # 评审 comment 里偶发未转义的裸换行等控制字符（实测 qwen3.8-omni-flash 约 7%，
        # finish_reason=stop、正文看起来完整）。strict=False 只放宽这一项，
        # 其余语法错误仍按失败处理，不做猜测式修补。
        try:
            payload = json.loads(candidate, strict=False)
        except (json.JSONDecodeError, ValueError):
            return {}
    return payload if isinstance(payload, dict) else {}


class VisionReviewMixin:
    """视觉理解档位：把素材与评审维度一起送进 OpenAI 兼容多模态对话。

    未混入本类的纯文本档位不应暴露 analyze_image / analyze_video，
    否则目录、白名单与执行层会重新失去一致性。
    """

    MODEL_ID = ""
    # 深度思考默认开启的档位必须显式关闭：实测豆包 Seed 2.1 开启后 39.8s、输出 1900+ tokens，
    # 关闭后 9.4s、输出 363 tokens；评审是交互调用，预算也会被思考链吃光。
    DISABLE_THINKING = False

    def _vision_client(self) -> Any:
        raise NotImplementedError

    def _vision_disable_thinking_kwargs(self) -> Dict[str, Any]:
        """DISABLE_THINKING 为 True 时并入 create() 的额外参数，各家写法不同。"""
        return {}

    def _run_vision_review(
        self,
        *,
        parts: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> GenerationResult:
        start = time.time()
        create_kwargs: Dict[str, Any] = {
            "model": self.MODEL_ID,
            "messages": [{"role": "user", "content": parts}],
            "max_tokens": VISION_MAX_TOKENS,
        }
        if self.DISABLE_THINKING:
            create_kwargs.update(self._vision_disable_thinking_kwargs())
        try:
            client = self._vision_client()
            response = client.chat.completions.create(**create_kwargs)
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = getattr(choice, "finish_reason", None)
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(exc), latency=time.time() - start,
            )

        payload = parse_vision_review_content(content)
        return GenerationResult(
            success=True, task_id="", model_id=self.spec.id,
            outputs=[content],
            metadata={
                **metadata,
                "content": content,
                "result_data": payload or {"content": content},
                # 降级要能归因：finish_reason=length 指向预算被吃光，stop 指向正文本身非法，
                # 两者对应的修法完全不同，缺这两个字段时线上只能看到"成功但纯文本"。
                "finish_reason": finish_reason,
                "vision_parse_failed": not payload,
            },
            latency=time.time() - start,
        )

    def analyze_image(
        self,
        *,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> GenerationResult:
        names = [str(item) for item in (criteria or VISION_DEFAULT_CRITERIA["image"])]
        parts = [
            {"type": "image_url", "image_url": {"url": resolve_image_asset_url(image_path)}},
            {
                "type": "text",
                "text": build_vision_review_prompt(
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
        names = [str(item) for item in (criteria or VISION_DEFAULT_CRITERIA["video"])]
        parts = [
            {"type": "video_url", "video_url": {"url": resolve_video_asset_url(video_path)}},
            {
                "type": "text",
                "text": build_vision_review_prompt(
                    asset_kind="video", analysis_type=analysis_type, criteria=names
                ),
            },
        ]
        return self._run_vision_review(
            parts=parts,
            metadata={"video_path": video_path, "analysis_type": analysis_type, "criteria": names},
        )
