# -*- coding: utf-8 -*-
"""提交前能力校验（preflight）：请求硬条件 vs 单条路线能力。

这是选路过滤与提交前防御的唯一规则源，避免两份逻辑漂移：
- 返回空元组：该路线可服务本次请求；
- 返回非空原因码元组：不满足的具体项，编排层据此分型 preflight_rejected，
  前置秒拒，不触网、不重试、不产生供应商费用。

不含运维开关（enabled）与质量组路由范围约束——那些由 filter_candidates
在调用本函数前后处理，不属于“请求 vs 能力”。
"""
from __future__ import annotations

from ..catalog import Route, VideoSpec


def preflight(spec: VideoSpec, route: Route) -> tuple[str, ...]:
    """返回未满足项原因码；空元组表示全部硬条件通过。"""
    cap = route.capability
    reasons: list[str] = []
    if not cap.duration.accepts(spec.duration_seconds):
        reasons.append("duration_out_of_range")
    if spec.resolution.lower() not in cap.resolutions:
        reasons.append("unsupported_resolution")
    if spec.aspect_ratio not in cap.aspect_ratios:
        reasons.append("unsupported_aspect_ratio")
    if spec.mode not in cap.input_modes:
        reasons.append("mode_not_supported")
    if spec.reference_images > cap.max_images:
        reasons.append("too_many_images")
    if spec.reference_videos > cap.max_videos:
        reasons.append("too_many_videos")
    if spec.reference_audios > cap.max_audios:
        reasons.append("too_many_audios")
    total = (spec.reference_images
             + spec.reference_videos + spec.reference_audios)
    if cap.max_total_assets and total > cap.max_total_assets:
        reasons.append("too_many_assets_total")
    if route.price_plan().quote(
            spec.resolution, spec.duration_seconds) is None:
        reasons.append("quote_unavailable")
    return tuple(reasons)
