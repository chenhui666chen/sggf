"""小说叙事质量结构化模块：失败码、修订路由、项目级问题记忆、伏笔账本。

设计对齐 AI Director OS 的失败码直检（L1）与修复路由（R0-R6）思想：
- 评审端输出结构化失败码 → 修订端按码路由（轻码局部修订 / 重码整章重写）
- 项目级高频问题记忆跨章沉淀，注入后续创作预防
- 伏笔账本登记埋设与回收，防止烂尾

纯函数实现，无外部依赖；持久化载体为 project_settings.review_meta（JSON dict）。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.prompts.stages.content_creation import (
    extract_chapter_position,
    match_scene_type,
)

QUALITY_MEMORY_KEY = "quality_memory"
FORESHADOW_LEDGER_KEY = "foreshadow_ledger"

_FAILURE_CASES_PATH = Path(__file__).parent / "narrative_failure_cases.json"
_failure_cases_cache: Optional[List[Dict[str, Any]]] = None

# ---------------------------------------------------------------------------
# 失败码目录
# class: light = 局部修订可解决；heavy = 需实质性重写
# ---------------------------------------------------------------------------
NOVEL_FAILURE_CODES: Dict[str, Dict[str, str]] = {
    # --- 轻码：局部修订（等价 R2 编辑修复） ---
    "HOOK_WEAK":        {"name": "钩子乏力",     "class": "light", "hint": "重写结尾段钩子，兑现更强悬念"},
    "PACING_DRAG":      {"name": "局部节奏拖沓", "class": "light", "hint": "压缩指定拖沓段落，删冗余描写"},
    "DESC_ABSTRACT":    {"name": "描写空洞",     "class": "light", "hint": "将空洞形容词替换为具体动作/细节"},
    "DIALOG_STIFF":     {"name": "对话失真",     "class": "light", "hint": "按人设重写指定对话，去说明腔"},
    "AI_TRACE":         {"name": "AI痕迹",       "class": "light", "hint": "清除重复句式与机械排比"},
    "EMOTION_FLAT":       {"name": "情绪平淡",     "class": "light", "hint": "补身体反应与细节动作强化情绪"},
    # 修订阶段专用：为应付必改项而新造前文不存在的事实（轻码：删改单点即可修复，阻断力来自严重度）
    "NEW_FACT_UNSOURCED": {"name": "无出处新事实", "class": "light", "hint": "删去该新增事实或改按现有可溯源素材重写，不得用编造细节圆场"},
    # --- 重码：实质性重写（等价 R4） ---
    "STALL_NO_PROGRESS": {"name": "原地踏步",     "class": "heavy", "hint": "核心推进未发生，需重构本章事件"},
    "LOGIC_BREAK":       {"name": "逻辑硬伤",     "class": "heavy", "hint": "因果链断裂，需重排事件逻辑"},
    "OOC_MAJOR":         {"name": "人设漂移",     "class": "heavy", "hint": "人物行为背离既有人设，相关段落重写"},
    "CONTINUITY_BREAK":  {"name": "连续性断裂",   "class": "heavy", "hint": "与前文状态/设定冲突，需对齐后重写"},
    "STRUCT_BROKEN":     {"name": "结构断裂",     "class": "heavy", "hint": "开头/结尾脱节或全文双环重复时，删除重复线后只保留一条叙事，不要只重排首尾"},
    "INFO_DUMP":         {"name": "设定倾倒",     "class": "heavy", "hint": "大段旁白式设定说明，需拆进冲突重写"},
}

FAILURE_CODE_OUTPUT_SPEC = """### 失败码清单（结构化，供修订路由使用）
逐条列出本章问题对应的失败码，格式严格为：`失败码|严重度|位置或证据`
- 失败码从以下枚举中选择：""" + " / ".join(NOVEL_FAILURE_CODES.keys()) + """
- 严重度：HIGH（必改）/ MED（建议）/ LOW（可选）
- 无问题时输出：`无`
示例：
```
失败码清单：
HOOK_WEAK|HIGH|结尾仅总结情绪，未留悬念
DESC_ABSTRACT|MED|战斗段"剑光如虹"等空洞描写
```"""

# 编造类失败码：修订靠新造事实让必改项“看起来已闭环”，本质上仍是未解决
UNSOURCED_FACT_FAILURE_CODES = {"NEW_FACT_UNSOURCED"}

# 失败码行格式：CODE|SEVERITY|desc 或 CODE[SEVERITY]
_FAILURE_LINE_RE = re.compile(
    r"\b(" + "|".join(NOVEL_FAILURE_CODES.keys()) + r")\b\s*[|｜\[]\s*(HIGH|MED|LOW)\s*[|｜\]]?\s*([^\n]*)",
    re.IGNORECASE,
)


def extract_failure_codes(review_text: str) -> List[Dict[str, str]]:
    """从评审报告中解析结构化失败码行。"""
    results: List[Dict[str, str]] = []
    seen = set()
    for match in _FAILURE_LINE_RE.finditer(str(review_text or "")):
        code = match.group(1).upper()
        severity = match.group(2).upper()
        evidence = (match.group(3) or "").strip().strip("|｜")
        key = (code, evidence)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "code": code,
            "name": NOVEL_FAILURE_CODES[code]["name"],
            "severity": severity,
            "evidence": evidence,
            "class": NOVEL_FAILURE_CODES[code]["class"],
        })
    return results


# 综合评分行：**综合评分**：X/10分（"分"可省略；整段替换避免残留尾字）
_REVIEW_SCORE_LINE_RE = re.compile(
    r"(综合评分\**\s*[：:]\s*)([0-9]+(?:\.[0-9]+)?)\s*/\s*10\s*分?"
)


def review_has_unsourced_new_fact(review_text: str) -> bool:
    """复评是否判定存在 HIGH 级无出处新增事实（编造圆场不得判为达标）。"""
    return any(
        str(fc.get("code") or "") in UNSOURCED_FACT_FAILURE_CODES
        and str(fc.get("severity") or "").upper() == "HIGH"
        for fc in extract_failure_codes(str(review_text or ""))
    )


def review_has_required_issues(review_text: str) -> bool:
    """只消费本次评审的阻断证据，不把建议或已完成的核验项当作必改。"""
    text = str(review_text or "")
    if any(item["severity"] == "HIGH" for item in extract_failure_codes(text)):
        return True
    for line in text.splitlines():
        cleaned = line.replace("**", "").strip()
        if cleaned.startswith("|"):
            cells = [cell.strip() for cell in cleaned.strip("|").split("|")]
            if len(cells) >= 2 and re.search(r"MUST|必改", cells[0], re.I):
                if cells[1] in {"未执行", "部分执行"}:
                    return True
            continue
        match = re.search(r"【必改】\s*[:：]?\s*(.*)", cleaned)
        if match and not re.fullmatch(r"(?:无|无必改项|无问题|已全部解决)[。.]?", match.group(1).strip()):
            return True
    return False


def extract_review_score(review_text: str) -> Optional[float]:
    """解析评审/复评报告的综合评分；无有效分数返回 None。"""
    match = _REVIEW_SCORE_LINE_RE.search(str(review_text or "").replace("**", ""))
    if not match:
        return None
    try:
        return float(match.group(2))
    except (TypeError, ValueError):
        return None


def review_needs_revision(review_text: str, *, pass_score: float) -> bool:
    """综合分与结构化阻断项共同判定；缺少有效分数时不得视为达标。"""
    text = str(review_text or "").replace("**", "")
    if review_has_required_issues(text):
        return True
    if re.search(r"(?:结论|结果)\s*[:：]\s*(?:继续修改|需要修改|需要修订|风险较高|不通过)", text):
        return True
    score = extract_review_score(text)
    return score is None or not pass_score <= score <= 10


def review_verifies_required_ids(review_text: str, requirements: str) -> bool:
    """有编号的必改项必须逐项核验，缺表或证据占位不得放行。"""
    id_pattern = r"\b(?:R\d+-)?MUST-\d+\b"
    required_ids = set(re.findall(id_pattern, requirements or "", re.I))
    verified_ids = set()
    for line in str(review_text or "").replace("**", "").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[1] != "已执行":
            continue
        if not cells[2] or re.fullmatch(r"(?:无|待补充|待确认|待核验|未提供|不适用|\.\.\.|…+|[-—]+)[。.]?", cells[2]):
            continue
        verified_ids.update(re.findall(id_pattern, cells[0], re.I))
    return {item.upper() for item in required_ids} <= {item.upper() for item in verified_ids}


def calibrate_review_score_to_rubric(review_text: str) -> str:
    """按评分锚点校准评审综合分（程序化兜底，治"零问题低分"的模型先验惯性）。

    规则（与 STANDARD_CHAPTER_REVIEW_RUBRIC 锚点一致）：
    - 无【必改】建议 且 无 HIGH/MED 失败码 → 分数不得低于 8.0（8-8.5 档下限）
    - 存在【必改】建议 或 HIGH 失败码 → 分数不得高于 7.5

    仅在明显违规时改写分数行并附校准说明；轻度越界（±0.5 内按档内解释）不动。
    """
    text = str(review_text or "")
    match = _REVIEW_SCORE_LINE_RE.search(text)
    if not match:
        return text
    try:
        score = float(match.group(2))
    except (TypeError, ValueError):
        return text

    codes = extract_failure_codes(text)
    has_high_or_med = any(fc.get("severity") in ("HIGH", "MED") for fc in codes)
    # 【必改】判定：修改建议区存在【必改】条目（排除"无必改"字样）
    must_fix_hits = [
        m for m in re.finditer(r"【必改】", text)
        if "无必改" not in text[max(0, m.start() - 6):m.start()]
    ]
    has_must_fix = bool(must_fix_hits)

    calibrated = None
    reason = ""
    if (not has_must_fix) and (not has_high_or_med) and score < 7.5 and score >= 6.5:
        # 零必改+零中高级失败码却压到 7 档以下：按锚点应为 8-8.5 档
        calibrated = 8.0
        reason = "无必改项且无 HIGH/MED 失败码，按评分锚点应为 8-8.5 档"
    elif (has_must_fix or any(fc.get("severity") == "HIGH" for fc in codes)) and score > 8.0:
        # 有必改项/HIGH 码却给出 8+ 高分：按锚点不得高于 7.5
        calibrated = 7.5
        reason = "存在必改项或 HIGH 失败码，按评分锚点不得高于 7.5 分"

    if calibrated is None:
        return text

    old_line = match.group(0)
    new_line = f"{match.group(1)}{calibrated:g}/10分"
    text = text.replace(old_line, new_line, 1)
    # 透明标注校准痕迹（追加在评分行后，不侵入正文结构）
    text = text.replace(
        new_line,
        f"{new_line}（评分校准：原评 {score:g} 分；{reason}）",
        1,
    )
    return text


def resolve_revision_mode(failure_codes: List[Dict[str, str]]) -> Tuple[Optional[str], str]:
    """根据失败码判定修订模式。

    Returns:
        (mode, hint)：mode 为 "light" / "heavy" / None（无码时不干预）
    """
    if not failure_codes:
        return None, ""
    has_heavy = any(fc["class"] == "heavy" for fc in failure_codes)
    if has_heavy:
        heavy_names = "、".join(
            f"{fc['code']}({fc['name']})" for fc in failure_codes if fc["class"] == "heavy"
        )
        return "heavy", (
            f"本轮检测到重级失败码：{heavy_names}。属于结构性问题，"
            "需要对相关段落进行实质性重写（可保留与问题无关的可用段落）。"
        )
    light_names = "、".join(
        f"{fc['code']}({fc['name']})" for fc in failure_codes if fc["severity"] == "HIGH"
    ) or "、".join(f"{fc['code']}({fc['name']})" for fc in failure_codes)
    return "light", (
        f"本轮仅检测到轻级失败码：{light_names}。全部可通过局部修订解决，"
        "采用局部修订模式：仅修改问题所在段落及其直接衔接处，未受影响的段落必须保持原文照抄，禁止顺手润色。"
    )


# ---------------------------------------------------------------------------
# 项目级问题记忆（P1-2）
# ---------------------------------------------------------------------------
_UNRESOLVED_SECTION_RE = re.compile(r"##\s*剩余关键问题\s*\n+(.*?)(?=\n##|\n结论[：:]|\Z)", re.DOTALL)
_ISSUE_ITEM_RE = re.compile(r"^\s*\d+[\.、)]\s*(.*?)\s*$")
_MUST_FIX_RE = re.compile(r"【必改】\s*(.{6,400})")
# 记忆条目只留问题主干：评审报告常写成“问题：建议修改如下：……”，
# 旧实现按硬截断取前 120 字，跨行续写还会被拆成碎片，沉淀到 review_meta 后读不通
_ISSUE_HEAD_MIN_LEN = 4
_ISSUE_MAX_LEN = 80
_SENTENCE_BREAK_RE = re.compile(r"[。！？；]")
_LEADING_TAG_RE = re.compile(r"^[【\[][^】\]]{1,6}[】\]]\s*")
_INSTRUCTION_TAIL_RE = re.compile(r"[，、；;：:]*\s*(?:具体)?(?:修改|调整)?(?:建议|方案|示例)?如下[：:]?\s*$")
_INSTRUCTION_ONLY = {
    "建议", "修改建议", "操作建议", "如下", "建议如下", "修改如下", "建议修改如下",
    "修改建议如下", "具体如下", "示例如下", "方案如下", "改法如下",
}


def _collect_numbered_lines(block: str) -> List[str]:
    """提取编号条目，并把 markdown 滞后续行归回上一条（跨行书写的问题不得拆成两条）。"""
    items: List[str] = []
    for raw in str(block or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        match = _ISSUE_ITEM_RE.match(raw)
        if match:
            items.append(match.group(1))
            continue
        if not items or stripped.startswith(("#", "|", "-", "*", ">")):
            continue
        items[-1] = f"{items[-1]}{stripped}"
    return items


def _truncate_issue(text: str) -> str:
    """超长条目在标点处收口，不得在词中间腰斩。"""
    if len(text) <= _ISSUE_MAX_LEN:
        return text
    window = text[:_ISSUE_MAX_LEN]
    cut = max(window.rfind(mark) for mark in "。！？；，、")
    if cut < _ISSUE_HEAD_MIN_LEN:
        return text
    return window[:cut + 1].rstrip("，、")


def _normalize_issue_text(raw: str) -> str:
    """把一条评审意见归一为可读的问题主干；纯执行引导语返回空串。"""
    text = re.sub(r"\*+", "", str(raw or "")).strip()
    text = _LEADING_TAG_RE.sub("", text)
    text = _INSTRUCTION_TAIL_RE.sub("", text).strip()

    parts = re.split(r"[：:]", text, maxsplit=1)
    if len(parts) == 2 and len(parts[0].strip("，、 ")) >= _ISSUE_HEAD_MIN_LEN:
        text = parts[0].strip("，、 ")
    sentence = _SENTENCE_BREAK_RE.search(text)
    if sentence and sentence.end() >= _ISSUE_HEAD_MIN_LEN:
        text = text[:sentence.end()]
    text = _INSTRUCTION_TAIL_RE.sub("", text).strip("，、；：。 ")
    if not text or len(text) < _ISSUE_HEAD_MIN_LEN:
        return ""
    if text in _INSTRUCTION_ONLY or (text.endswith("如下") and len(text) <= 10):
        return ""
    return _truncate_issue(text)


def extract_unresolved_issues(review_text: str, max_items: int = 3) -> List[str]:
    """从评审报告提取未解决关键问题（剩余关键问题 > 必改项）。"""
    text = str(review_text or "")
    section = _UNRESOLVED_SECTION_RE.search(text)
    candidates = _collect_numbered_lines(section.group(1)) if section else []
    if not candidates:
        candidates = _MUST_FIX_RE.findall(text)

    issues: List[str] = []
    for raw in candidates:
        issue = _normalize_issue_text(raw)
        if issue and issue not in issues:
            issues.append(issue)
    return issues[:max_items]


def update_quality_memory(
    review_meta: Dict[str, Any],
    chapter_number: int,
    issues: List[str],
) -> Dict[str, Any]:
    """将本章未解决问题并入项目级记忆（就地更新并返回 review_meta）。

    结构：quality_memory.items = [{"issue","hits","first_chapter","last_chapter"}]
    归并规则：与已有条目高度相似（一方包含另一方≥8字）时计数+1，否则新增。
    """
    memory = review_meta.get(QUALITY_MEMORY_KEY) or {}
    items: List[Dict[str, Any]] = list(memory.get("items") or [])
    for issue in issues:
        merged = False
        for item in items:
            existing = str(item.get("issue") or "")
            if existing and (existing in issue or issue in existing):
                item["hits"] = int(item.get("hits") or 0) + 1
                item["last_chapter"] = chapter_number
                item["issue"] = existing if len(existing) >= len(issue) else issue
                merged = True
                break
        if not merged:
            items.append({
                "issue": issue,
                "hits": 1,
                "first_chapter": chapter_number,
                "last_chapter": chapter_number,
            })
    # 高频优先，同类保留最新描述
    items.sort(key=lambda x: (-int(x.get("hits") or 0), int(x.get("last_chapter") or 0)))
    memory["items"] = items[:20]
    review_meta[QUALITY_MEMORY_KEY] = memory
    return review_meta


def format_quality_memory(review_meta: Dict[str, Any], top_n: int = 3) -> str:
    """格式化项目级高频问题记忆为提示词区块；无有效记忆时返回空串。"""
    memory = review_meta.get(QUALITY_MEMORY_KEY) or {}
    items = [i for i in (memory.get("items") or []) if int(i.get("hits") or 0) >= 1]
    if not items:
        return ""
    lines = []
    for item in items[:top_n]:
        hits = int(item.get("hits") or 0)
        span = f"第{item.get('first_chapter')}-{item.get('last_chapter')}章" if item.get("first_chapter") != item.get("last_chapter") else f"第{item.get('last_chapter')}章"
        freq = "（高频复发，重点防御）" if hits >= 3 else f"（出现{hits}次）"
        lines.append(f"- [{span}{freq}] {item.get('issue')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 伏笔账本（P1-3）
# ---------------------------------------------------------------------------
# 规划字段行解析：允许加粗（**伏笔事项**：）、行内前缀（“补充伏笔事项：”）与缩进写法，
# 标签按长度降序参与匹配，保证“伏笔事项”优先于“伏笔”、“回收伏笔”优先于“伏笔”
_PLANT_FIELD_LABELS = ("伏笔事项", "新埋设伏笔", "伏笔")
_RECOVERY_FIELD_LABELS = ("回收伏笔", "拟回收伏笔", "待回收伏笔")
_FORESHADOW_LABEL_RE = re.compile(
    "(" + "|".join(sorted(set(_RECOVERY_FIELD_LABELS + _PLANT_FIELD_LABELS), key=len, reverse=True)) + ")"
    + r"(?:\*\*)?\s*[：:]\s*(.*)$"
)
# 内联回收声明：中文规划常把“回收第N章…”直接写在伏笔事项字段里，
# 不能依赖章节定位字段判定（定位写成“关键转折”时旧实现会把回收声明当新埋设登记）
_RECOVERY_CLAIM_RE = re.compile(r"回收|收回|兑现|呼应前文")
_EMPTY_FIELD_VALUES = {"无", "（无）", "(无)", "暂无", "略", "none", "None", "-"}
# 回收记录只保留最近 N 条，未回收条目全部保留，避免账本无上限膨胀
_MAX_RECOVERED_HISTORY = 20


def _match_foreshadow_label(line: str) -> Optional[Tuple[str, str]]:
    """识别伏笔字段行，返回（标签, 同行取值）；非伏笔字段行返回 None。"""
    match = _FORESHADOW_LABEL_RE.search(str(line or ""))
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def _collect_field_values(lines: List[str], label_index: int, inline_value: str) -> List[str]:
    """取字段取值：同行内容 + 紧随其后、缩进更深的子条目（字段值另起行的写法）。"""
    values: List[str] = []
    if inline_value:
        values.append(inline_value)
    label_indent = len(lines[label_index]) - len(lines[label_index].lstrip())
    for offset in range(label_index + 1, len(lines)):
        raw = lines[offset]
        stripped = raw.strip()
        if not stripped:
            break
        if len(raw) - len(raw.lstrip()) <= label_indent:
            break
        if _match_foreshadow_label(stripped):
            # 子条目自己带了伏笔标签（如“  - 回收伏笔：xxx”），属于另一个字段
            break
        values.append(stripped.lstrip("-*· ").strip())
    return values


def _split_field_items(value: str) -> List[str]:
    """切分字段取值为伏笔条目。

    只按分号断条目：逗号、顿号属于句内连接，切开会产出“目前下落不明”
    这类读不通的碎片，既污染注入提示词，又让写前闸门对碎片误报未推进。
    """
    items: List[str] = []
    for part in re.split(r"[；;]+", str(value or "")):
        item = part.strip().strip("*").strip().rstrip("。，、,，")
        if not item or item in _EMPTY_FIELD_VALUES or len(item) < 4:
            continue
        if item not in items:
            items.append(item)
    return items


def _parse_foreshadow_fields(chapter_plan: str) -> Tuple[List[str], List[str]]:
    """解析章节规划中的伏笔字段，返回（新埋设条目, 回收声明）。"""
    lines = str(chapter_plan or "").splitlines()
    plants: List[str] = []
    claims: List[str] = []
    for index, raw in enumerate(lines):
        hit = _match_foreshadow_label(raw)
        if not hit:
            continue
        label, inline_value = hit
        for value in _collect_field_values(lines, index, inline_value):
            for item in _split_field_items(value):
                is_claim = label in _RECOVERY_FIELD_LABELS or bool(_RECOVERY_CLAIM_RE.search(item))
                target = claims if is_claim else plants
                if item not in target:
                    target.append(item)
    return plants, claims


def _parse_foreshadow_items(chapter_plan: str) -> List[str]:
    """解析章节规划中的伏笔事项字段，返回全部非空条目（含回收声明）。

    写前闸门需要同时看到埋设与回收条目做一致性校验，故这里不区分语义。
    """
    plants, claims = _parse_foreshadow_fields(chapter_plan)
    return plants + claims


def _char_bigrams(text: str) -> set:
    text = re.sub(r"\s+", "", str(text or ""))
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}


def _foreshadow_similar(a: str, b: str, threshold: float = 0.2) -> bool:
    """基于字符 bigram 重叠率判断两条伏笔描述是否指向同一伏笔。"""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ga, gb = _char_bigrams(a), _char_bigrams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / min(len(ga), len(gb)) >= threshold


def register_foreshadowing(
    review_meta: Dict[str, Any],
    chapter_number: int,
    chapter_plan: str,
    chapter_position: Optional[str] = None,
) -> Dict[str, Any]:
    """登记本章伏笔埋设 / 标记回收（就地更新并返回 review_meta）。

    - 埋设条目登记为 open，与已有条目相似的不再重复登记
    - 回收声明（分标签写法或文本含“回收/兑现/呼应前文”）只用于匹配账本，
      命中的 open 条目标记 recovered，绝不作为新埋设入账
    - 定位为“伏笔回收”的章节：伏笔字段整体按回收声明处理（保留原行为）
    """
    ledger = review_meta.get(FORESHADOW_LEDGER_KEY) or {}
    entries: List[Dict[str, Any]] = list(ledger.get("entries") or [])
    plants, claims = _parse_foreshadow_fields(chapter_plan)
    if chapter_position == "伏笔回收":
        claims = claims + plants
        plants = []

    for claim in claims:
        for entry in entries:
            if entry.get("status") != "open":
                continue
            if _foreshadow_similar(str(entry.get("content") or ""), claim):
                entry["status"] = "recovered"
                entry["recovered_chapter"] = chapter_number

    for item in plants:
        already = any(
            _foreshadow_similar(str(e.get("content") or ""), item)
            for e in entries
        )
        if not already:
            entries.append({
                "content": item,
                "planted_chapter": chapter_number,
                "status": "open",
            })

    recovered_indices = [i for i, e in enumerate(entries) if e.get("status") == "recovered"]
    if len(recovered_indices) > _MAX_RECOVERED_HISTORY:
        drop = set(recovered_indices[:-_MAX_RECOVERED_HISTORY])
        entries = [e for i, e in enumerate(entries) if i not in drop]

    ledger["entries"] = entries
    review_meta[FORESHADOW_LEDGER_KEY] = ledger
    return review_meta


def format_foreshadow_ledger(
    review_meta: Dict[str, Any],
    current_chapter_number: int,
    max_items: int = 6,
) -> str:
    """格式化未回收伏笔账本为提示词区块；无未回收伏笔时返回空串。"""
    ledger = review_meta.get(FORESHADOW_LEDGER_KEY) or {}
    open_entries = [e for e in (ledger.get("entries") or []) if e.get("status") == "open"]
    if not open_entries:
        return ""
    # 埋设越早越接近烂尾风险，优先展示
    open_entries.sort(key=lambda e: int(e.get("planted_chapter") or 0))
    lines = []
    for entry in open_entries[:max_items]:
        planted = int(entry.get("planted_chapter") or 0)
        age = current_chapter_number - planted
        warn = "（⚠️埋设已久，尽快安排回收）" if age >= 10 else ""
        lines.append(f"- 第{planted}章埋设：{entry.get('content')}{warn}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 失败案例库（P2-2）：JSON SSOT + 双相位调度
# T3 事前预防：按 题材/情节类型/章节定位 触发条件匹配 → prevention 注入创作
# T1 事后修复：失败码直检（L1）→ repair_model 注入修订（机制修复优先）
# ---------------------------------------------------------------------------
def load_failure_cases(refresh: bool = False) -> List[Dict[str, Any]]:
    """加载失败案例库（模块级缓存；解析失败安全降级为空列表）。"""
    global _failure_cases_cache
    if _failure_cases_cache is not None and not refresh:
        return _failure_cases_cache
    try:
        with open(_FAILURE_CASES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        cases = data.get("cases") or []
        _failure_cases_cache = [c for c in cases if isinstance(c, dict) and c.get("code")]
    except Exception:
        _failure_cases_cache = []
    return _failure_cases_cache


def match_prevention_cases(
    genre: str,
    chapter_plan: str,
    max_cases: int = 3,
) -> List[Dict[str, Any]]:
    """T3 预防匹配：题材/情节类型/章节定位任一维度命中触发条件的案例。

    触发条件为空的案例（如 AI_TRACE）不参与预防匹配，仅走 T1 修复相位。
    """
    cases = load_failure_cases()
    if not cases:
        return []
    scene_type = match_scene_type(chapter_plan)
    position = extract_chapter_position(chapter_plan)
    matched: List[Dict[str, Any]] = []
    for case in cases:
        triggers = case.get("triggers") or {}
        scene_hit = bool(scene_type) and scene_type in (triggers.get("scene_types") or [])
        position_hit = bool(position) and position in (triggers.get("positions") or [])
        genre_hit = bool(genre) and genre in (triggers.get("genres") or [])
        if scene_hit or position_hit or genre_hit:
            matched.append(case)
    return matched[:max_cases]


def format_prevention_block(matched_cases: List[Dict[str, Any]]) -> str:
    """格式化预防案例为提示词区块；无命中时返回空串。"""
    lines = []
    for case in matched_cases:
        prevention = str(case.get("prevention") or "").strip()
        if not prevention:
            continue
        lines.append(f"- {case.get('name')}（{case.get('code')}）：{prevention}")
    return "\n".join(lines)


def build_repair_hints(failure_codes: List[Dict[str, Any]], max_hints: int = 4) -> str:
    """T1 修复指引：按失败码直检命中案例，输出 repair_model 机制修复文本。"""
    if not failure_codes:
        return ""
    case_by_code = {c.get("code"): c for c in load_failure_cases()}
    lines = []
    seen = set()
    for fc in failure_codes:
        code = fc.get("code")
        if not code or code in seen:
            continue
        seen.add(code)
        case = case_by_code.get(code)
        repair = str((case or {}).get("repair_model") or "").strip()
        if not repair:
            continue
        lines.append(f"- {fc.get('name')}（{code}）修复机制：{repair}")
        if len(lines) >= max_hints:
            break
    return "\n".join(lines)
