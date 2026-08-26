"""细纲驱动的写前连续性闸门（P1）。

职责边界（对应指导文档第 6 节）::

    章节规划：提出本章要写什么
    写前闸门：验证这个计划能否在当前叙事状态下执行
    正文生成：把通过验证的计划写成正文
    写后评审：检查正文是否真正执行计划且没有产生新矛盾

设计约束：
- 只做规则优先的结构化校验，不评价文学性，不调用 LLM；
- 只检查高置信度规则，宁可漏报也不误报（误报会阻断正常创作）；
- 复用 P0 统一伏笔适配器（``foreshadow_adapter``）的任务结构，不新建字段体系；
- 输出带 ``phase=pre_generation`` 的失败码结构，供重规划反馈与报告复用；
- C 类"回收前置条件"P1 只使用现成字段（appearance_status/life_status/伏笔状态），
  道具/设定/前置线索仅 warning 或跳过，完整证据链等 P2。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.services.foreshadow_adapter import normalize_foreshadow_content
from app.services.prompts.narrative_quality import _parse_foreshadow_items

logger = logging.getLogger(__name__)

SEVERITY_BLOCKING = "blocking"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
PHASE = "pre_generation"

# 复用现有失败码（文档 6.6）
CODE_CONTINUITY_BREAK = "CONTINUITY_BREAK"
CODE_LOGIC_BREAK = "LOGIC_BREAK"
CODE_STALL_NO_PROGRESS = "STALL_NO_PROGRESS"

# 伏笔事项字段解析：直接复用 narrative_quality 的实现，保证与账本登记同语义
_EMPTY_VALUES = {"无", "（无）", "(无)", "暂无", "略", "none", "-"}

# 通用字段行解析：支持 "- 情节作用：xxx" / "**情节作用**：xxx" / "情节作用: xxx"
def _build_field_re(label: str) -> re.Pattern:
    return re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?" + re.escape(label) + r"(?:\*\*)?\s*[：:]\s*(.+?)\s*$",
        re.MULTILINE,
    )


_REVEAL_KEYWORDS = ("回收", "揭示", "揭开", "揭晓", "道破", "真相大白", "暴露", "证实")
_PLANT_KEYWORDS = ("埋设", "埋下", "新埋", "植入")
_HINT_ONLY_KEYWORDS = ("只暗示", "仅暗示", "只铺垫", "仅铺垫", "不揭示", "不揭穿")
_FLASHBACK_KEYWORDS = ("回忆", "闪回", "追忆", "遗物", "往事", "祭奠", "悼念")


def parse_foreshadow_items(text: str) -> List[str]:
    """解析规划/细纲文本中的伏笔事项字段条目（过滤"无"）。"""
    return _parse_foreshadow_items(str(text or ""))


def parse_plan_field(text: str, label: str) -> str:
    """提取规划/细纲文本中指定字段的首个取值（无则空串）。"""
    match = _build_field_re(label).search(str(text or ""))
    if not match:
        return ""
    return match.group(1).strip()


def split_character_names(text: str) -> List[str]:
    """拆分涉及人物字段为角色名列表。"""
    names: List[str] = []
    for part in re.split(r"[、，,；;/／\s]+", str(text or "")):
        name = part.strip().strip("*").strip()
        if 1 < len(name) <= 12 and name not in names and name not in {"无", "暂无", "等"}:
            names.append(name)
    return names


def _is_reveal_declaration(item: str) -> bool:
    return any(keyword in item for keyword in _REVEAL_KEYWORDS)


def _is_plant_declaration(item: str) -> bool:
    return any(keyword in item for keyword in _PLANT_KEYWORDS)


def _match_task(item: str, task: Dict[str, Any]) -> bool:
    """判断伏笔事项条目是否指向统一任务（规范化双向包含，保守匹配）。"""
    item_norm = normalize_foreshadow_content(item)
    task_norm = normalize_foreshadow_content(task.get("content"))
    if not item_norm or not task_norm:
        return False
    return task_norm in item_norm or item_norm in task_norm


def _make_issue(
    *,
    code: str,
    severity: str,
    rule: str,
    evidence: str,
    foreshadowing_id: str = "",
) -> Dict[str, Any]:
    return {
        "code": code,
        "phase": PHASE,
        "severity": severity,
        "rule": rule,
        "foreshadowing_id": foreshadowing_id,
        "evidence": evidence,
    }


def infer_current_volume(*texts: str) -> Optional[int]:
    """从卷上下文/细纲文本推断当前卷号（首个"第N卷"引用，无法确定返回 None）。"""
    pattern = re.compile(r"第\s*(\d+)\s*卷")
    for text in texts:
        match = pattern.search(str(text or ""))
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# 规则实现（A/B/C/E，首期高置信度子集）
# ---------------------------------------------------------------------------
def _check_outline_plan_foreshadow_alignment(
    chapter_outline: str,
    plan_items: List[str],
    plan_foreshadow_raw: str,
) -> List[Dict[str, Any]]:
    """A. 伏笔动作与细纲一致性。"""
    issues: List[Dict[str, Any]] = []
    outline_plot_function = parse_plan_field(chapter_outline, "情节作用")
    outline_items = parse_foreshadow_items(chapter_outline)
    plan_declares_reveal = any(_is_reveal_declaration(item) for item in plan_items)

    # A1：细纲情节作用=伏笔回收，但规划伏笔事项为"无"
    if "伏笔回收" in outline_plot_function and not plan_items:
        issues.append(
            _make_issue(
                code=CODE_CONTINUITY_BREAK,
                severity=SEVERITY_BLOCKING,
                rule="A1",
                evidence=(
                    f"章细纲情节作用标记为「{outline_plot_function}」，"
                    "但章节规划伏笔事项为“无”，未安排任何伏笔回收"
                ),
            )
        )

    # A2：细纲伏笔事项声明回收，规划是否对应执行
    outline_reveal_items = [item for item in outline_items if _is_reveal_declaration(item)]
    if outline_reveal_items and not plan_declares_reveal:
        issues.append(
            _make_issue(
                code=CODE_CONTINUITY_BREAK,
                severity=SEVERITY_BLOCKING,
                rule="A2",
                evidence=(
                    "章细纲伏笔事项要求回收「"
                    + "、".join(outline_reveal_items[:2])
                    + "」，但章节规划未声明任何回收动作"
                ),
            )
        )

    # A3：细纲伏笔事项为"无"，规划却声明回收（可能错误回收他章伏笔）
    outline_foreshadow_raw = parse_plan_field(chapter_outline, "伏笔事项")
    outline_no_item = (
        not outline_items
        and outline_foreshadow_raw
        and outline_foreshadow_raw.strip().strip("*").strip() in _EMPTY_VALUES
    )
    if outline_no_item and plan_declares_reveal:
        issues.append(
            _make_issue(
                code=CODE_CONTINUITY_BREAK,
                severity=SEVERITY_WARNING,
                rule="A3",
                evidence="章细纲伏笔事项为“无”，但章节规划声明了伏笔回收，请确认回收目标与账本状态",
            )
        )

    # A4：规划伏笔事项字段缺失（未写“无”）——仅记录
    if not plan_foreshadow_raw.strip():
        issues.append(
            _make_issue(
                code=CODE_STALL_NO_PROGRESS,
                severity=SEVERITY_INFO,
                rule="A4",
                evidence="章节规划缺少伏笔事项字段，无法确认伏笔任务执行情况",
            )
        )
    return issues


def _check_framework_windows_and_status(
    plan_items: List[str],
    unified_tasks: List[Dict[str, Any]],
    *,
    current_volume: Optional[int],
) -> List[Dict[str, Any]]:
    """B. 框架窗口一致性 + C1. 已回收/已揭示状态（blocking）。"""
    issues: List[Dict[str, Any]] = []
    for item in plan_items:
        is_reveal = _is_reveal_declaration(item)
        is_plant = _is_plant_declaration(item)
        if not (is_reveal or is_plant):
            continue
        for task in unified_tasks:
            if not _match_task(item, task):
                continue
            task_id = str(task.get("id") or "")
            content = str(task.get("content") or "")
            status = str(task.get("status") or "")
            # C1：对已完结伏笔再次声明回收 → 重复回收
            if is_reveal and status in {"revealed", "recovered", "abandoned"}:
                issues.append(
                    _make_issue(
                        code=CODE_CONTINUITY_BREAK,
                        severity=SEVERITY_BLOCKING,
                        rule="C1",
                        foreshadowing_id=task_id,
                        evidence=f"伏笔「{content}」状态已为 {status}，章节规划再次声明回收，构成重复回收",
                    )
                )
                continue
            reveal_volume = task.get("reveal_volume")
            planted_volume = task.get("planted_volume")
            # B1：早于规定揭秘卷提前揭示
            if (
                is_reveal
                and reveal_volume is not None
                and current_volume is not None
                and int(current_volume) < int(reveal_volume)
            ):
                issues.append(
                    _make_issue(
                        code=CODE_CONTINUITY_BREAK,
                        severity=SEVERITY_BLOCKING,
                        rule="B1",
                        foreshadowing_id=task_id,
                        evidence=(
                            f"伏笔「{content}」框架规定第{reveal_volume}卷揭秘，"
                            f"当前为第{current_volume}卷，章节规划提前揭示"
                        ),
                    )
                )
            # B2：埋设卷窗口不一致
            if (
                is_plant
                and planted_volume is not None
                and current_volume is not None
                and int(planted_volume) != int(current_volume)
            ):
                issues.append(
                    _make_issue(
                        code=CODE_CONTINUITY_BREAK,
                        severity=SEVERITY_WARNING,
                        rule="B2",
                        foreshadowing_id=task_id,
                        evidence=(
                            f"伏笔「{content}」框架规定第{planted_volume}卷埋设，"
                            f"当前为第{current_volume}卷，章节规划声明本章埋设"
                        ),
                    )
                )
    return issues


def _check_character_states(
    chapter_plan: str,
    character_states: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """C/F. 角色生死/出场状态（P1 只用现成字段；回忆/闪回语境豁免）。"""
    issues: List[Dict[str, Any]] = []
    involved_raw = parse_plan_field(chapter_plan, "涉及人物")
    if not involved_raw:
        return issues
    plan_text = str(chapter_plan or "")
    for name in split_character_names(involved_raw):
        state = next((c for c in character_states if str(c.get("name") or "") == name), None)
        if state is None:
            continue
        life_status = str(state.get("life_status") or "").strip()
        appearance_status = str(state.get("appearance_status") or "").strip()
        if life_status == "死亡":
            # 回忆/闪回等语境允许已故角色出现
            context_lines = [
                line for line in plan_text.splitlines()
                if name in line and any(k in line for k in _FLASHBACK_KEYWORDS)
            ]
            if not context_lines:
                issues.append(
                    _make_issue(
                        code=CODE_LOGIC_BREAK,
                        severity=SEVERITY_BLOCKING,
                        rule="F1",
                        evidence=f"角色「{name}」状态为已死亡，章节规划仍安排其出场（如为回忆/闪回请在规划中注明）",
                    )
                )
        elif appearance_status == "未出场":
            issues.append(
                _make_issue(
                    code=CODE_LOGIC_BREAK,
                    severity=SEVERITY_BLOCKING,
                    rule="F2",
                    evidence=f"角色「{name}」出场状态为未出场，章节规划直接安排其出场，缺少登场铺垫",
                )
            )
    return issues


def _check_internal_consistency(chapter_plan: str) -> List[Dict[str, Any]]:
    """E. 计划内部一致性：同一行同时声明"只暗示"与"明确揭示"。"""
    issues: List[Dict[str, Any]] = []
    for line in str(chapter_plan or "").splitlines():
        has_hint = any(keyword in line for keyword in _HINT_ONLY_KEYWORDS)
        has_reveal = any(keyword in line for keyword in ("明确揭示", "完整揭示", "直接揭示", "彻底揭示"))
        if has_hint and has_reveal:
            issues.append(
                _make_issue(
                    code=CODE_CONTINUITY_BREAK,
                    severity=SEVERITY_WARNING,
                    rule="E1",
                    evidence=f"章节规划同一处同时声明“只暗示”与“明确揭示”：{line.strip()[:60]}",
                )
            )
            break  # 只报一次，避免重复噪音
    return issues


def _check_long_open_foreshadow(
    unified_tasks: List[Dict[str, Any]],
    current_chapter: Optional[int],
    *,
    threshold: int = 20,
) -> List[Dict[str, Any]]:
    """D/6.6：埋设已久但长期未推进的伏笔提示（warning）。"""
    issues: List[Dict[str, Any]] = []
    if not current_chapter:
        return issues
    for task in unified_tasks:
        if str(task.get("status")) != "open" or task.get("action") != "none":
            continue
        planted_chapter = task.get("planted_chapter")
        if not planted_chapter:
            continue
        age = int(current_chapter) - int(planted_chapter)
        if age >= threshold:
            issues.append(
                _make_issue(
                    code=CODE_CONTINUITY_BREAK,
                    severity=SEVERITY_WARNING,
                    rule="D1",
                    foreshadowing_id=str(task.get("id") or ""),
                    evidence=(
                        f"伏笔「{task.get('content')}」第{planted_chapter}章埋设，"
                        f"已{age}章未推进，建议尽快安排铺垫或回收"
                    ),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _extract_setting_names(catalog: str) -> List[str]:
    names: List[str] = []
    for line in str(catalog or '').splitlines():
        text = line.strip().lstrip('-').strip()
        if not text:
            continue
        name = re.split(r'[：:（(]', text, maxsplit=1)[0].strip()
        if 1 < len(name) <= 20 and name not in names:
            names.append(name)
    return names


def _check_settings_prerequisites(plan_text: str, settings_catalog: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    catalog_names = _extract_setting_names(settings_catalog)
    if not catalog_names:
        return issues
    required = parse_plan_field(plan_text, '设定调用') or parse_plan_field(plan_text, '关键设定')
    if not required:
        return issues
    missing = []
    for part in re.split(r'[、，,；;]', required):
        item = part.strip().strip('*')
        if not item or item in {'无', '暂无'}:
            continue
        if not any(item == name or item in name or name in item for name in catalog_names):
            missing.append(item)
    if missing:
        issues.append(_make_issue(code=CODE_CONTINUITY_BREAK, severity=SEVERITY_WARNING, rule='C3', evidence='规划调用了设定清单中未见的设定：' + '、'.join(missing[:3]) + '（仅 warning，待事实图复核）'))
    return issues


def run_pre_generation_gate(
    *,
    chapter_plan: str,
    chapter_outline: str = "",
    unified_tasks: Optional[List[Dict[str, Any]]] = None,
    character_states: Optional[List[Dict[str, Any]]] = None,
    current_volume: Optional[int] = None,
    current_chapter: Optional[int] = None,
    settings_catalog: str = '',
) -> List[Dict[str, Any]]:
    """执行写前连续性闸门，返回失败码结构列表（严重度 blocking/warning/info）。

    任何内部异常都吞掉并记日志，闸门故障不得阻断章节生成。
    """
    issues: List[Dict[str, Any]] = []
    try:
        plan_text = str(chapter_plan or "")
        plan_items = parse_foreshadow_items(plan_text)
        plan_foreshadow_raw = parse_plan_field(plan_text, "伏笔事项")
        tasks = [t for t in (unified_tasks or []) if isinstance(t, dict)]

        issues.extend(
            _check_outline_plan_foreshadow_alignment(chapter_outline, plan_items, plan_foreshadow_raw)
        )
        issues.extend(
            _check_framework_windows_and_status(plan_items, tasks, current_volume=current_volume)
        )
        issues.extend(_check_character_states(plan_text, character_states or []))
        issues.extend(_check_internal_consistency(plan_text))
        issues.extend(_check_long_open_foreshadow(tasks, current_chapter))
        issues.extend(_check_settings_prerequisites(plan_text, settings_catalog))
    except Exception as exc:  # 闸门自身故障不阻断创作
        logger.warning("写前闸门执行异常，跳过闸门: %s", exc)
        return []
    return issues


def has_blocking_issues(issues: List[Dict[str, Any]]) -> bool:
    return any(issue.get("severity") == SEVERITY_BLOCKING for issue in issues or [])


def format_gate_feedback(issues: List[Dict[str, Any]]) -> str:
    """生成重规划反馈文本（附在规划 prompt 末尾，要求修正冲突）。"""
    blocking = [i for i in issues if i.get("severity") == SEVERITY_BLOCKING]
    warnings = [i for i in issues if i.get("severity") == SEVERITY_WARNING]
    if not blocking and not warnings:
        return ""
    lines: List[str] = ["【写前闸门冲突反馈】写前连续性闸门发现以下问题，重规划时必须解决："]
    if blocking:
        lines.append("必须修正（blocking）：")
        for issue in blocking:
            lines.append(f"- [{issue.get('code')}] {issue.get('evidence')}")
    if warnings:
        lines.append("建议规避（warning）：")
        for issue in warnings:
            lines.append(f"- [{issue.get('code')}] {issue.get('evidence')}")
    lines.append(
        "请仅修正与上述冲突相关的规划内容，保持其余规划稳定；"
        "若细纲要求回收伏笔，必须在伏笔事项中明确回收目标；"
        "若框架窗口未到揭秘卷，只允许铺垫或暗示，禁止揭示。"
    )
    return "\n".join(lines)


def format_gate_warning_section(issues: List[Dict[str, Any]]) -> str:
    """生成注入正文生成 prompt 的闸门提醒区块（仅 blocking/warning 要点）。"""
    relevant = [
        i for i in issues
        if i.get("severity") in (SEVERITY_BLOCKING, SEVERITY_WARNING)
    ]
    if not relevant:
        return ""
    lines = ["【写前闸门提醒】正文创作时请注意："]
    for issue in relevant[:6]:
        lines.append(f"- {issue.get('evidence')}")
    return "\n".join(lines)


def build_gate_report(
    issues: List[Dict[str, Any]],
    *,
    chapter_number: int,
    rounds: int = 0,
) -> Dict[str, Any]:
    """生成闸门报告（用于沉淀 review_meta 与人工确认）。"""
    return {
        "phase": PHASE,
        "chapter_number": chapter_number,
        "replan_rounds": rounds,
        "blocking_count": sum(1 for i in issues if i.get("severity") == SEVERITY_BLOCKING),
        "warning_count": sum(1 for i in issues if i.get("severity") == SEVERITY_WARNING),
        "issues": issues,
    }
