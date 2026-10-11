# -*- coding: utf-8 -*-
"""剧本引擎编排入口（原地重写自旧 scripter.run）。

阶段流（对齐指导文档 Phase 2.2）：
  幂等短路 → 知识加载 → Story Graph 摄取（只读冻结章节，provenance 登记）
  → 结构化剧本生成（知识注入 prompt）→ CCV 协作环 → 3E 完整性门
  → 兼容产物派生（script_text Markdown 视图 / entities / profiles / audio_markers）
  → payload 写回（含 script_document / story_graph 新键）→ 人工审核门保留

兼容契约（勘察确认，不可破坏）：
  - run(ctx) -> None，产物写 ctx.payload
  - script_requires_review=True → 状态机转 WAITING_SCRIPT_APPROVAL
  - script_text 含旧标记（## 概要/## 分场/### 场N/节拍/对白/视觉锚点）供旧 storyboarder 消费
  - character_profiles / audio_markers 字段结构与旧版完全一致
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List

from agents.llm_client import env_flag, resolve_llm_runtime_config
from agents.scripter_pkg import _knowledge
from agents.scripter_pkg._ccv import run_ccv
from agents.scripter_pkg._generate import generate_script_document
from agents.scripter_pkg._schema import (
    SCHEMA_VERSION,
    beat_families_used,
    derive_audio_markers,
    derive_character_profiles,
    derive_entities,
    render_markdown,
    source_provenance,
)
from agents.scripter_pkg._story_graph import extract_story_graph, graph_summary_for_prompt
from agents.scripter_pkg._three_e import run_three_e
from pipeline.style_presets import ensure_style_payload


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _pick_script_model() -> str:
    raw = os.getenv("DREAMWEAVER_SCRIPT_MODEL")
    if raw and raw.strip():
        return raw.strip()
    legacy = os.getenv("DEEPSEEK_MODEL")
    if legacy and legacy.strip():
        return legacy.strip()
    return "qwen-plus"


def _auto_max_scenes(source_text: str, chars_per_scene: int) -> int:
    """场数预算：按文本量估（对齐旧引擎的自动档逻辑量级）。"""
    n = len(source_text or "")
    if n <= 0:
        return 3
    return max(2, min(12, (n // max(200, chars_per_scene)) + 2))


def _fallback_document(source_text: str, provenance: Dict[str, Any]) -> Dict[str, Any]:
    """无 LLM 时的降级剧本：单场 + 段落节拍（保留管线可跑通，人工门兜底）。"""
    paragraphs = [p.strip() for p in re.split(r"\n+", source_text or "") if p.strip()]
    beats = []
    for i, para in enumerate(paragraphs[:12], start=1):
        beats.append({
            "beat_id": f"S1-B{i}",
            "family": "",
            "type": "action",
            "description": para[:80],
            "action": "",
            "shot_purpose": "传递信息",
            "dialogue": [],
            "visual_anchor": "",
            "hook": i == 1,
            "duration_hint_s": 5.0,
        })
    if not beats:
        beats.append({
            "beat_id": "S1-B1", "family": "", "type": "action",
            "description": "（空章节）", "action": "", "shot_purpose": "传递信息",
            "dialogue": [], "visual_anchor": "", "hook": True, "duration_hint_s": 5.0,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "title": "（降级草稿）",
        "logline": "",
        "synopsis": "无 LLM 可用，由章节文本直接降级生成，待人工改写。",
        "hooks": {"opening_hook": beats[0].get("description", ""), "ending_hook": "", "share_emotion": ""},
        "scenes": [{
            "scene_id": "S1", "number": 1, "title": "降级场",
            "interior": "内景", "location": "未知", "time_of_day": "日",
            "characters": [], "summary": "降级生成", "beats": beats,
        }],
        "source": provenance,
    }


def run(ctx: Any) -> None:
    """剧本引擎主入口（状态机 SCRIPT 阶段调用）。"""
    payload = ctx.payload if isinstance(getattr(ctx, "payload", None), dict) else {}

    # ---- 幂等短路：已审核剧本不重跑（旧契约保留） ----
    existing_script = payload.get("script_text")
    existing_review = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
    if (
        isinstance(existing_script, str)
        and existing_script.strip()
        and bool((existing_review or {}).get("approved"))
    ):
        payload["script_requires_review"] = False
        ctx.payload = payload
        return

    # ---- 配置（沿用旧环境变量口径） ----
    source_text = str(payload.get("source_text") or "")
    run_id = str(payload.get("run_id") or "")
    require_review = env_flag("DREAMWEAVER_REQUIRE_SCRIPT_APPROVAL", default=True)
    enable_llm = env_flag("DREAMWEAVER_SCRIPT_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag(
        "DREAMWEAVER_SCRIPT_REQUIRE_LLM", default=False
    )
    enable_ccv = env_flag("DREAMWEAVER_SCRIPT_CCV", default=True)
    enable_graph = env_flag("DREAMWEAVER_SCRIPT_STORY_GRAPH", default=True)

    quality_mode = str(payload.get("quality_mode") or "").strip().lower() == "quality"
    chars_per_scene = max(60, _env_int("DREAMWEAVER_SCRIPT_CHARS_PER_SCENE", 120))
    max_scenes_raw = _env_int("DREAMWEAVER_SCRIPT_MAX_SCENES", 0 if quality_mode else 8)
    if max_scenes_raw <= 0:
        max_scenes = _auto_max_scenes(source_text, chars_per_scene)
        max_scenes_mode = "auto"
    else:
        max_scenes = max(1, max_scenes_raw)
        max_scenes_mode = "fixed"
    min_scenes_hint = max(1, min(4, max_scenes))

    ensure_style_payload(payload)
    style_prompt = str(payload.get("style_prompt") or "")

    model = _pick_script_model()
    llm_runtime = resolve_llm_runtime_config(model)
    api_key = llm_runtime.api_key
    base_url = llm_runtime.base_url
    timeout_s = int(os.getenv("DREAMWEAVER_SCRIPT_TIMEOUT", "180") or "180")
    temperature = _env_float("DREAMWEAVER_SCRIPT_TEMPERATURE", 0.3)
    temperature = max(0.0, min(1.0, temperature))
    retries = max(1, _env_int("DREAMWEAVER_SCRIPT_LLM_RETRIES", 2 if quality_mode else 1))

    can_llm = bool(enable_llm and api_key and base_url)
    if require_llm and not can_llm:
        raise RuntimeError(
            f"{llm_runtime.api_key_env} and {llm_runtime.base_url_env} are required for script generation"
        )

    warnings: List[str] = []
    provenance = source_provenance(
        source_text=source_text,
        chapter_ids=payload.get("chapter_ids"),
        run_id=run_id,
    )

    # ---- 知识加载（Phase 2.1 派生目录，硬前置） ----
    knowledge = _knowledge.load_script_knowledge()
    families: List[str] = knowledge["beat_family_names"]

    # ---- 阶段 1：Story Graph 摄取 ----
    hints = payload.get("script_entities") if isinstance(payload.get("script_entities"), dict) else None
    if can_llm and enable_graph:
        story_graph, graph_mode = extract_story_graph(
            source_text=source_text,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_s=timeout_s,
            temperature=temperature,
            hints=hints,
        )
    else:
        from agents.scripter_pkg._story_graph import _fallback_graph
        story_graph = _fallback_graph(source_text, hints)
        graph_mode = "fallback"
        if not can_llm:
            warnings.append("LLM 不可用，剧本引擎降级运行（人工审核门兜底）")

    # ---- 阶段 2：结构化剧本生成 ----
    if can_llm:
        doc = generate_script_document(
            source_text=source_text,
            graph_view=graph_summary_for_prompt(story_graph),
            knowledge=knowledge,
            style_prompt=style_prompt,
            max_scenes=max_scenes,
            min_scenes_hint=min_scenes_hint,
            quality_mode=quality_mode,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_s=timeout_s,
            temperature=temperature,
            retries=retries,
            warnings=warnings,
        )
        mode = "llm_structured"
    else:
        doc = _fallback_document(source_text, provenance)
        mode = "fallback_structured"

    doc["schema_version"] = SCHEMA_VERSION

    # ---- 阶段 3：CCV 协作环 ----
    if can_llm and enable_ccv:
        doc, ccv_report = run_ccv(
            document=doc,
            families=families,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_s=timeout_s,
            temperature=temperature,
            max_rounds=1 if not quality_mode else 2,
            warnings=warnings,
        )
    else:
        from agents.scripter_pkg._ccv import collect_issues
        ccv_report = {
            "protocol": "critique_correct_verify",
            "llm_used": False,
            "initial_issues": len(collect_issues(doc, families)),
            "remaining_issues": collect_issues(doc, families)[:20],
            "status": "disabled_or_code_only",
        }

    # ---- 阶段 4：3E 完整性门 ----
    doc, three_e_report = run_three_e(
        document=doc,
        families=families,
        max_scenes=max_scenes,
        min_scenes_hint=min_scenes_hint,
        ccv_remaining_issues=ccv_report.get("remaining_issues") if isinstance(ccv_report, dict) else None,
        api_key=api_key if can_llm else "",
        base_url=base_url if can_llm else "",
        model=model,
        timeout_s=timeout_s,
        temperature=temperature,
        explore_candidates=2 if quality_mode else 1,
        warnings=warnings,
    )

    # ---- 阶段 5：兼容产物派生 + payload 写回 ----
    # 引擎元数据在 CCV/3E 之后统一回写（revised/patched document 由 LLM 返回，不允许持有溯源字段）
    doc["schema_version"] = SCHEMA_VERSION
    doc["source"] = provenance
    script_text = render_markdown(doc)
    entities = derive_entities(doc, story_graph)

    payload["script_document"] = doc
    payload["story_graph"] = story_graph
    payload["script_text"] = script_text
    payload["script_entities"] = entities
    payload["script_generation"] = {
        "engine": "director_os_script_v2",
        "mode": mode,
        "model": model if mode.startswith("llm") else None,
        "warnings": warnings,
        "max_scenes": max_scenes,
        "max_scenes_mode": max_scenes_mode,
        "min_scenes_hint": min_scenes_hint,
        "chars_per_scene": chars_per_scene,
        "story_graph_mode": graph_mode,
        "beat_families_used": sorted(set(beat_families_used(doc))),
        "ccv": {
            "status": ccv_report.get("status"),
            "initial_issues": ccv_report.get("initial_issues"),
            "remaining": len(ccv_report.get("remaining_issues") or []),
        },
        "three_e": {
            "status": three_e_report.get("status"),
            "remaining": len(three_e_report.get("remaining_issues") or []),
        },
        "source_version": provenance.get("chapter_version"),
    }
    payload["script_review"] = {"approved": False}
    payload["script_requires_review"] = bool(require_review)
    payload["script_enhancement"] = {
        "mode": "ccv_3e_integrated",
        "ccv": ccv_report,
        "three_e": three_e_report,
    }

    # 角色档案：从 Story Graph 派生（图内已有描述，省 LLM 调用）
    if env_flag("DREAMWEAVER_ENABLE_CHARACTER_PROFILES", default=True):
        profiles = derive_character_profiles(doc, story_graph)
        payload["character_profiles"] = [p.to_dict() for p in profiles]

    # 音频标记：从 beat.dialogue 派生（语速预算估时）
    if env_flag("DREAMWEAVER_ENABLE_AUDIO_MARKERS", default=True):
        markers = derive_audio_markers(doc)
        payload["audio_markers"] = [m.to_dict() for m in markers]

    ctx.payload = payload
