"""写后结构化消化服务（P2）：narrative_state_v1 增量沉淀。

职责（对应指导文档第 7 节）::

    章节规划确定"计划"，写后消化确认"执行结果"。
    只沉淀相对计划的增量：事件偏差、计划外事实、人物变化、伏笔证据、叙事债务。

设计约束：
- 只走 chapter_post_save 异步抽取路径，不扩展评审 prompt；
- 持久化存入 review_meta.narrative_state_v1（版本化 JSON，不建新表）；
- 幂等键：project_id + chapter_id + extractor_version，重复消化不重复写入；
- 消化失败（LLM 异常/JSON 损坏/落库失败）一律不抛异常，不影响正文保存；
- 无增量的章节只记录 plan_alignment，不重复落细纲内容；
- character_changes 不另做变化检测：LLM 提示词要求只输出实质变化项，
  人物状态的权威落点仍是 character_state_snapshots。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from core.langchain_bridge import create_model_llm
from app.services.exact_model_guard import require_exact_model
from app.services.narrative_metrics import record_quality_metrics, validate_quality_metrics

logger = logging.getLogger("uvicorn.error")

EXTRACTOR_VERSION = "v1"
NARRATIVE_STATE_KEY = "narrative_state_v1"
# review_meta 中最多保留的已消化章节数（滚动窗口，防止 JSON 无限膨胀）
MAX_STORED_CHAPTERS = 20

_PLAN_ALIGNMENTS = {"matched", "partial", "deviated"}

# 滚动继承的未偿还债务/未闭合事件上限（防 JSON 膨胀）
_MAX_OPEN_ITEMS = 12


def _norm_item_text(value: Any) -> str:
    """条目内容归一化（去空白），用于跨章去重与偿还匹配。"""
    return re.sub(r"\s+", "", str(value or ""))


def _head_tail_excerpt(text: str, *, head: int = 4000, tail: int = 2500) -> str:
    """长文本首尾拼接截取：章节结尾是钩子/伏笔证据/叙事债务最集中的位置，
    只取开头会遗漏后半段事件；短文本原样返回。"""
    content = str(text or "")
    if len(content) <= head + tail:
        return content
    return content[:head] + "\n……（中段省略）……\n" + content[-tail:]


def _build_digest_prompt(
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str,
) -> str:
    plan_block = (chapter_plan or "").strip()[:2500] or "（无章节规划）"
    return f"""你是小说叙事状态分析师。章节规划是"计划"，正文是"执行结果"。
请对比两者，只提取"增量"——不要复述计划本身，不要做文学分析。

【第{chapter_number}章 章节规划】
{plan_block}

【第{chapter_number}章 正文（节选）】
{_head_tail_excerpt(chapter_content)}

只返回合法 JSON 对象，不要输出其他说明文字：
{{
  "plan_alignment": "matched|partial|deviated（本章执行与规划的整体吻合度）",
  "events": [
    {{
      "description": "相对规划发生偏差或计划外的关键事件（30字内）",
      "participants": ["人物名"],
      "consequences": ["该事件造成的后续影响（20字内）"],
      "closed": false,
      "evidence": "原文片段（50字内）"
    }}
  ],
  "character_changes": [
    {{
      "character": "人物名",
      "field": "current_motivation|current_belief|emotional_state|relationship_state",
      "before": "章前状态（不确定则空串）",
      "after": "本章结束时的状态",
      "reason": "变化原因（20字内）"
    }}
  ],
  "foreshadowing": [
    {{
      "content": "伏笔核心内容",
      "action": "plant|pave|reveal|none",
      "evidence": "正文证据片段（50字内）"
    }}
  ],
  "narrative_debts": [
    {{
      "content": "本章结束时仍未兑现的承诺/钩子/未处理问题（30字内）",
      "priority": "high|normal",
      "source": "钩子|承诺|计划外线索|细纲要求"
    }}
  ],
  "resolved_debts": ["本章已兑现/了结的既有债务内容（与既有债务表述对应，没有则空数组）"],
  "quality_metrics": {{
    "tension_score": 0,
    "conflict_progress_score": 0,
    "emotion_change_score": 0,
    "information_gain_score": 0,
    "ending_hook_score": 0
  }}
}}

要求：
1. 完全按规划执行、无变化、无计划外事实时，对应数组必须为空，plan_alignment 填 matched
2. events 只收录偏差事件与计划外事件；按计划正常发生的事件不要重复记录
3. character_changes 只收录状态发生实质变化的人物，未变化不要输出
4. narrative_debts 收录"答应了但还没还"的执行层欠账，与伏笔主档案分开；本章已兑现的既有欠账写入 resolved_debts
5. quality_metrics 五项均为 0-100 整数：按正文实际执行效果打分（张力/冲突推进/情绪变化/信息增量/结尾钩子），不评价文学性
6. 所有字段宁缺毋滥，无证据支撑的推测一律不输出"""


def _clean_json_object(raw: Any) -> Optional[Dict[str, Any]]:
    """清洗并解析 LLM 返回的 JSON 对象；失败返回 None。"""
    text = re.sub(r"```json\s*", "", str(raw or ""))
    text = re.sub(r"```\s*$", "", text).strip()
    if not text:
        return None
    # 截取首个 { 到末尾 } 之间的内容，容忍前后缀噪声
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(text[start:end + 1])
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def _validate_digest(raw: Dict[str, Any], chapter_number: int) -> Dict[str, Any]:
    """字段级校验与裁剪，保证落库结构稳定。"""
    alignment = str(raw.get("plan_alignment") or "matched").strip().lower()
    if alignment not in _PLAN_ALIGNMENTS:
        alignment = "partial"

    events: List[Dict[str, Any]] = []
    for item in raw.get("events") or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        events.append(
            {
                "description": description[:80],
                "participants": [
                    str(p).strip() for p in (item.get("participants") or []) if str(p).strip()
                ][:6],
                "consequences": [
                    str(c).strip()[:60] for c in (item.get("consequences") or []) if str(c).strip()
                ][:4],
                "closed": bool(item.get("closed", False)),
                "evidence": str(item.get("evidence") or "").strip()[:120],
            }
        )

    character_changes: List[Dict[str, Any]] = []
    for item in raw.get("character_changes") or []:
        if not isinstance(item, dict):
            continue
        character = str(item.get("character") or "").strip()
        after = str(item.get("after") or "").strip()
        if not character or not after:
            continue
        character_changes.append(
            {
                "character": character[:24],
                "field": str(item.get("field") or "").strip()[:40],
                "before": str(item.get("before") or "").strip()[:60],
                "after": after[:60],
                "reason": str(item.get("reason") or "").strip()[:60],
            }
        )

    foreshadowing: List[Dict[str, Any]] = []
    for item in raw.get("foreshadowing") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        action = str(item.get("action") or "none").strip().lower()
        if not content or action not in {"plant", "pave", "reveal", "none"}:
            continue
        foreshadowing.append(
            {
                "content": content[:60],
                "action": action,
                "evidence": str(item.get("evidence") or "").strip()[:120],
            }
        )

    narrative_debts: List[Dict[str, Any]] = []
    for item in raw.get("narrative_debts") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        priority = str(item.get("priority") or "normal").strip().lower()
        narrative_debts.append(
            {
                "content": content[:80],
                "priority": priority if priority in {"high", "normal"} else "normal",
                "source": str(item.get("source") or "").strip()[:24],
                "since_chapter": chapter_number,
            }
        )

    # 本章已兑现的既有债务（用于滚动继承时从 open_debts 中移除）
    resolved_debts: List[str] = []
    for item in raw.get("resolved_debts") or []:
        content = str(item or "").strip()
        if content and content[:80] not in resolved_debts:
            resolved_debts.append(content[:80])

    return {
        "chapter": chapter_number,
        "plan_alignment": alignment,
        "events": events[:8],
        "character_changes": character_changes[:8],
        "foreshadowing": foreshadowing[:8],
        "narrative_debts": narrative_debts[:8],
        "resolved_debts": resolved_debts[:8],
        # P3：张力 5 指标搭车消化输出（不新增 LLM 调用）
        "quality_metrics": validate_quality_metrics(raw.get("quality_metrics")),
    }


def has_meaningful_increment(digest: Dict[str, Any]) -> bool:
    """判断消化结果是否包含增量（无增量章节不重复沉淀细节）。"""
    return bool(
        digest.get("events")
        or digest.get("character_changes")
        or digest.get("foreshadowing")
        or digest.get("narrative_debts")
        or digest.get("plan_alignment") != "matched"
    )


async def extract_narrative_state_from_chapter(
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM 抽取本章执行增量；任何失败返回 {}，不抛异常。"""
    content = str(chapter_content or "").strip()
    if not content:
        return {}

    model_id = require_exact_model(model) or (
        os.getenv("NARRATIVE_STATE_EXTRACTION_MODEL")
        or os.getenv("UNIFIED_EXTRACTION_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("MODEL_NAME")
        or "deepseek-pro"
    )
    try:
        # 消化属短 JSON 抽取步：默认关闭思考模式，避免 reasoning 占用小上下文预算
        llm = create_model_llm(
            model=model_id,
            temperature=0.3,
            extra_body={"thinking": {"type": "disabled"}},
        )
        response = await llm.ainvoke(_build_digest_prompt(chapter_number, content, chapter_plan))
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.warning("写后消化 LLM 调用失败（不影响正文保存）: %s", exc)
        return {}

    parsed = _clean_json_object(raw)
    if parsed is None:
        logger.warning("写后消化返回内容不是合法 JSON，已跳过")
        return {}
    return _validate_digest(parsed, chapter_number)


def _rolling_open_debts(
    state: Dict[str, Any], digest: Dict[str, Any], chapter_number: int
) -> List[Dict[str, Any]]:
    """未偿还债务滚动继承：既有 open_debts + 本章新增 - 本章已兑现，按内容去重。"""
    previous = state.get("open_debts")
    previous = previous if isinstance(previous, list) else []
    resolved_norm = {_norm_item_text(item) for item in (digest.get("resolved_debts") or [])}

    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for debt in list(previous) + list(digest.get("narrative_debts") or []):
        if not isinstance(debt, dict):
            continue
        key = _norm_item_text(debt.get("content"))
        if not key or key in seen or key in resolved_norm:
            continue
        seen.add(key)
        merged.append(
            {
                "content": str(debt.get("content") or "")[:80],
                "priority": str(debt.get("priority") or "normal"),
                "since_chapter": int(debt.get("since_chapter") or chapter_number),
            }
        )
    return merged[:_MAX_OPEN_ITEMS]


def _rolling_open_events(
    state: Dict[str, Any], digest: Dict[str, Any], chapter_number: int
) -> List[Dict[str, Any]]:
    """未闭合事件滚动继承：既有 open_events + 本章未闭合事件；
    本章标记 closed 的同名事件从既有集合中移除。"""
    previous = state.get("open_events")
    previous = previous if isinstance(previous, list) else []
    current_events = [e for e in (digest.get("events") or []) if isinstance(e, dict)]
    closed_norm = {
        _norm_item_text(e.get("description"))
        for e in current_events
        if e.get("closed")
    }

    merged: List[Dict[str, Any]] = []
    seen: set = set()
    candidates = [
        *previous,
        *(
            {**event, "since_chapter": event.get("since_chapter") or chapter_number}
            for event in current_events
            if not event.get("closed")
        ),
    ]
    for event in candidates:
        if not isinstance(event, dict):
            continue
        key = _norm_item_text(event.get("description"))
        if not key or key in seen or key in closed_norm:
            continue
        seen.add(key)
        merged.append(
            {
                "description": str(event.get("description") or "")[:80],
                "since_chapter": int(event.get("since_chapter") or chapter_number),
            }
        )
    return merged[:_MAX_OPEN_ITEMS]


def merge_narrative_state_into_review_meta(
    review_meta: Dict[str, Any],
    chapter_number: int,
    digest: Dict[str, Any],
    *,
    extractor_version: str = EXTRACTOR_VERSION,
) -> bool:
    """将消化结果幂等合并进 review_meta.narrative_state_v1。

    Returns:
        True 表示产生了写入；同章同版本已存在时跳过（False）。
    """
    if not isinstance(review_meta, dict) or not digest:
        return False
    state = review_meta.get(NARRATIVE_STATE_KEY)
    if not isinstance(state, dict):
        state = {}
    chapters = state.get("chapters")
    if not isinstance(chapters, dict):
        chapters = {}

    chapter_key = str(int(chapter_number))
    existing = chapters.get(chapter_key)
    if isinstance(existing, dict) and existing.get("extractor_version") == extractor_version:
        return False  # 幂等：同章同版本不重复写入

    digest = dict(digest)
    digest["extractor_version"] = extractor_version
    chapters[chapter_key] = digest

    # 滚动窗口：仅保留最近 MAX_STORED_CHAPTERS 章
    if len(chapters) > MAX_STORED_CHAPTERS:
        ordered = sorted(chapters.keys(), key=lambda key: int(key) if key.isdigit() else 0)
        for obsolete_key in ordered[: len(chapters) - MAX_STORED_CHAPTERS]:
            chapters.pop(obsolete_key, None)

    state["extractor_version"] = extractor_version
    state["latest_chapter"] = int(chapter_number)
    state["chapters"] = chapters
    # 跨章滚动继承：未偿还债务/未闭合事件不依赖最近一章是否重新提及
    state["open_debts"] = _rolling_open_debts(state, digest, int(chapter_number))
    state["open_events"] = _rolling_open_events(state, digest, int(chapter_number))
    review_meta[NARRATIVE_STATE_KEY] = state
    return True


def format_narrative_state_section(
    review_meta: Optional[Dict[str, Any]],
    current_chapter: int,
    *,
    max_chars: int = 900,
) -> str:
    """将消化结果格式化为下一章规划提示词区块（优先级 2-4 注入）。

    顺序遵循文档 7.2.1：到期叙事债务 > 最近人物变化 > 最近未闭合事件。
    债务/事件优先读跨章滚动继承的 open_debts/open_events（后续章未提及也不丢失），
    旧数据无滚动键时回退最近一章读取。无可用数据时返回空串。
    """
    state = ((review_meta or {}).get(NARRATIVE_STATE_KEY) or {})
    chapters = state.get("chapters") or {}
    if not chapters or not current_chapter:
        return ""

    # 取本章之前最近一章的消化结果（人物变化仍只取最近章）
    prior_keys = [
        int(key) for key in chapters.keys()
        if key.isdigit() and int(key) < int(current_chapter)
    ]
    if not prior_keys:
        return ""
    latest = chapters.get(str(max(prior_keys))) or {}

    lines: List[str] = []
    # 未偿还债务：跨章滚动集合优先，旧数据回退最近章
    open_debts = state.get("open_debts")
    if not isinstance(open_debts, list) or not open_debts:
        open_debts = [
            {**d, "since_chapter": d.get("since_chapter") or max(prior_keys)}
            for d in (latest.get("narrative_debts") or [])
            if isinstance(d, dict)
        ]
    debts = [d for d in open_debts if isinstance(d, dict)]
    # 高优先级在前；同级内新债在前（旧债多为剧情已隐式解决的陈债，
    # 曾因旧债挤占前4名导致活跃常驻目标（如归元散）被截断、规划断线）
    debts.sort(
        key=lambda d: (
            0 if d.get("priority") == "high" else 1,
            -int(d.get("since_chapter") or 0),
        )
    )
    if debts:
        lines.append("未偿还叙事债务（必须优先承接，勿再开新线）：")
        for debt in debts[:4]:
            overdue = int(current_chapter) - int(debt.get("since_chapter") or max(prior_keys))
            overdue_hint = f"（已逾期{overdue}章）" if overdue >= 2 else ""
            lines.append(f"- {debt.get('content')}{overdue_hint}")

    changes = [c for c in (latest.get("character_changes") or []) if isinstance(c, dict)]
    if changes:
        lines.append("最近人物状态变化（按当前状态安排，勿用旧状态）：")
        for change in changes[:4]:
            lines.append(f"- {change.get('character')}：{change.get('after')}")

    # 未闭合事件：跨章滚动集合优先，旧数据回退最近章
    open_events = state.get("open_events")
    if not isinstance(open_events, list) or not open_events:
        open_events = [
            {"description": e.get("description")}
            for e in (latest.get("events") or [])
            if isinstance(e, dict) and not e.get("closed")
        ]
    events = [e for e in open_events if isinstance(e, dict) and e.get("description")]
    if events:
        lines.append("未闭合事件（已成立的事实，不可当作未发生）：")
        for event in events[:3]:
            lines.append(f"- {event.get('description')}")

    # 最近两章出场人物：配角无声消失是高频 CONTINUITY_BREAK 来源（如核心配角
    # 连续两章核心登场后下一章完全缺席且无任何提及），点名注入供规划安排
    recent_chars: List[str] = []
    for key in sorted(prior_keys, reverse=True)[:2]:
        digest = chapters.get(str(key)) or {}
        for ev in (digest.get("events") or []):
            if not isinstance(ev, dict):
                continue
            for p in (ev.get("participants") or []):
                if isinstance(p, str) and p.strip() and p.strip() not in recent_chars:
                    recent_chars.append(p.strip())
        # events 参与者为空时回退人物状态变化名单
        for ch in (digest.get("character_changes") or []):
            if isinstance(ch, dict):
                name = str(ch.get("character") or "").strip()
                if name and name not in recent_chars:
                    recent_chars.append(name)
    if recent_chars:
        lines.append(
            "最近两章出场人物（本章须安排其出场、被提及或注明暂离原因，不得无声消失）："
        )
        lines.append("- " + "、".join(recent_chars[:6]))

    if not lines:
        return ""
    section = "\n".join(lines)
    return section[:max_chars] if len(section) > max_chars else section


async def run_narrative_state_extraction_flow(
    db_session: Any,
    *,
    project_id: int,
    chapter_id: int,
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str = "",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """章节保存后的写后消化落库流程（post_save 异步路径）。

    LLM 抽取 → 幂等合并 review_meta.narrative_state_v1 → 落库。
    任何失败只记录日志并返回空统计，绝不抛异常。
    """
    result: Dict[str, Any] = {"extracted": False, "saved": False}
    try:
        from app.services.workflow_context_builder import WorkflowContextBuilder

        builder = WorkflowContextBuilder(db_session)
        digest = await extract_narrative_state_from_chapter(
            chapter_number=chapter_number,
            chapter_content=chapter_content,
            chapter_plan=chapter_plan,
            model=model,
        )
        if not digest:
            return result
        result["extracted"] = True
        if not has_meaningful_increment(digest):
            # 无增量章节：只记 plan_alignment，避免重复沉淀细纲内容；
            # 保留 resolved_debts 以免无增量章漏删已兑现债务
            digest = {
                "chapter": chapter_number,
                "plan_alignment": digest.get("plan_alignment", "matched"),
                "events": [],
                "character_changes": [],
                "foreshadowing": [],
                "narrative_debts": [],
                "resolved_debts": digest.get("resolved_debts") or [],
            }

        review_meta = builder.load_review_meta(project_id) or {}
        updated = merge_narrative_state_into_review_meta(review_meta, chapter_number, digest)
        # P3：张力指标随消化结果滚动沉淀（即使同章已消化也幂等覆盖同键）
        metrics_updated = record_quality_metrics(
            review_meta, chapter_number, digest.get("quality_metrics") or {}
        )
        if not updated and not metrics_updated:
            logger.info(f"   ℹ️ 写后消化幂等跳过：第{chapter_number}章已消化（同版本）")
            return result
        builder.update_project_settings_fields(project_id, review_meta=review_meta)
        result["saved"] = True
        logger.info(
            f"   🧾 写后消化完成：第{chapter_number}章 alignment={digest.get('plan_alignment')}，"
            f"事件{len(digest.get('events') or [])}条/人物变化{len(digest.get('character_changes') or [])}条"
            f"/伏笔{len(digest.get('foreshadowing') or [])}条/债务{len(digest.get('narrative_debts') or [])}条"
        )
    except Exception as exc:
        logger.warning(f"   ⚠️ 写后消化失败（不影响正文保存）: {exc}")
    return result
