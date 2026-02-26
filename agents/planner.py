from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model, llm_stream_context
from pipeline.style_presets import ensure_style_payload


def _estimate_shot_count(source_text: str, *, min_count: int = 6, max_count: int = 24) -> int:
    text = (source_text or "").strip()
    if not text:
        return min_count
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return max(min(len(paragraphs), max_count), min_count)


def _llm_plan(
    ctx: Any,
    *,
    source_text: str,
    chapter_count: int,
    style_preset: str,
    style_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
) -> Optional[Tuple[str, int]]:
    system = (
        "你是短剧制片统筹与导演助理。\n"
        "任务：对输入章节文本做“制作计划/结构提要”，并估算分镜镜头数。\n"
        "只输出严格 JSON（不要 Markdown/解释文字）。"
    )
    user = (
        "请输出 JSON：\n"
        "{\n"
        '  "plan_text": "一句话概述 + 3~6 条要点（可用换行）",\n'
        '  "estimated_shot_count": 12\n'
        "}\n\n"
        f"项目章节数：{chapter_count}\n"
        f"风格预设：{style_preset}\n"
        f"风格提示：{style_prompt}\n\n"
        "章节文本：\n"
        f"{source_text[:12000]}"
    )
    with llm_stream_context(ctx, stage="init", stream_key="plan") as on_chunk:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout_s=timeout_s,
            on_chunk=on_chunk,
        )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    plan_text = obj.get("plan_text")
    shot_count = obj.get("estimated_shot_count")
    if not isinstance(plan_text, str) or not plan_text.strip():
        return None
    try:
        sc = int(shot_count) if shot_count is not None else 0
    except Exception:  # noqa: BLE001
        sc = 0
    if sc <= 0:
        return plan_text.strip(), 0
    return plan_text.strip(), sc


def run(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)

    source_text = str(ctx.payload.get("source_text") or "")
    chapter_ids = ctx.payload.get("chapter_ids")
    chapter_count = len(chapter_ids) if isinstance(chapter_ids, list) else 0

    enable_llm = env_flag("DREAMWEAVER_PLANNER_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag(
        "DREAMWEAVER_PLANNER_REQUIRE_LLM", default=False
    )

    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
    model = pick_model(primary_env="DREAMWEAVER_PLANNER_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen-plus")
    timeout_s = int(os.getenv("DREAMWEAVER_PLANNER_TIMEOUT", "120") or "120")

    can_llm = bool(enable_llm and api_key and base_url)
    if require_llm and not can_llm:
        raise RuntimeError("planner require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

    mode = "rule"
    llm_error: str | None = None
    plan_text = ""
    shot_count = 0

    if can_llm:
        try:
            llm_plan = _llm_plan(
                ctx,
                source_text=source_text,
                chapter_count=chapter_count,
                style_preset=str(ctx.payload.get("style_preset") or ""),
                style_prompt=str(ctx.payload.get("style_prompt") or ""),
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
            )
            if llm_plan:
                mode = "llm"
                plan_text, llm_shots = llm_plan
                shot_count = max(1, min(int(llm_shots), 60))
            else:
                llm_error = "no valid plan returned"
        except Exception as exc:  # noqa: BLE001
            llm_error = f"{exc.__class__.__name__}: {exc}"
            if require_llm:
                raise

    if mode != "llm":
        shot_count = _estimate_shot_count(source_text, min_count=6, max_count=24)
        style_hint = str(ctx.payload.get("style_preset") or "").strip()
        plan_text = f"章节数={chapter_count}；预估镜头数≈{shot_count}；风格={style_hint or 'default'}。"

    ctx.payload["plan"] = {
        "text": plan_text,
        "meta": {
            "chapter_count": chapter_count,
            "estimated_shot_count": shot_count,
            "mode": mode,
            "llm_model": model if mode == "llm" else None,
            "llm_error": llm_error,
        },
    }
