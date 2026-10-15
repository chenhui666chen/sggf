# -*- coding: utf-8 -*-
"""独立网关视觉评价约定；与工作台同样采用明确扣分约束。"""
from __future__ import annotations

import json

VISION_DEFAULT_CRITERIA = {
    "image": ["clarity", "composition", "lighting", "color", "style"],
    "video": ["clarity", "smoothness", "consistency", "lighting", "color"],
}
VISION_MAX_TOKENS = 1200
VISION_CRITERION_RUBRICS = {
    "clarity": "主体或整体模糊、失焦、重影时不得高于 5 分。",
    "lighting": "只评曝光是否准确：整体偏暗、欠曝、死黑或过曝时不得高于 5 分，不得因光影有氛围感而给高分。",
    "smoothness": "同一画面被长时间重复（真正的冻结帧、跳帧、突兀运动）时不得高于 5 分；慢动作、缓慢运镜等合理低运动量不扣分。",
    "consistency": "主体造型、场景元素、文字或物体位置在时间轴上突变（消失、跳变、漂移）时不得高于 6 分。",
    "color": "整体偏色、脏灰、色彩断层时不得高于 6 分。",
    "composition": "主体残缺、错误裁切或画面拥挤时不得高于 6 分。",
    "style": "风格或材质在片段内跳变时不得高于 6 分。",
}


def build_vision_review_prompt(*, asset_kind: str, analysis_type: str, criteria: list[str]) -> str:
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


def parse_vision_review_content(text: str) -> dict:
    raw = str(text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start:end + 1], strict=False)
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
