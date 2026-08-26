"""统一伏笔上下文适配器（P0/P1 共用）。

背景：项目存在两套并行的伏笔机制——
1. 框架级 ``ForeshadowingTracker``（planned/planted/paving/revealed/abandoned）
2. 章节级 ``review_meta.foreshadow_ledger``（open/recovered）

本适配器只做"读取和投影"，不新增第三套账本，也不删除旧字段：
- 将框架伏笔、卷细纲伏笔摘要、章节账本统一投影为 6.4 节任务结构；
- 旧账本 open/recovered 只作为兼容输入，映射到统一 status；
- 跨层归并保守执行：仅当规范化后的核心文本完全相同才合并，
  宁可两条暂不合并，也不误并成一条；
- 解析失败一律回退为空结果，不阻断章节生成。

统一任务结构::

    {
        "id": "fs_fw_xxxxxxxx",
        "content": "主角真实身份",
        "status": "planned|planted|open|paving|revealed|recovered|abandoned",
        "action": "plant|pave|continue|reveal|none",
        "importance": "critical|important|normal|minor",
        "planted_volume": 1,
        "pave_volumes": [2, 3, 4],
        "reveal_volume": 5,
        "source": "framework|volume_outline|chapter_outline|chapter_plan",
        "chapter_requirement": "",
        "evidence": "",
    }
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

UNIFIED_STATUSES = {
    "planned",
    "planted",
    "open",
    "paving",
    "revealed",
    "recovered",
    "abandoned",
}
UNIFIED_ACTIONS = {"plant", "pave", "continue", "reveal", "none"}
_UNSETTLED_STATUSES = {"planned", "planted", "open", "paving"}

# 卷引用：第3卷 / 第3,5卷 / 3卷
_VOLUME_REF_RE = re.compile(r"第?\s*(\d+)\s*卷")


def normalize_foreshadow_content(content: Any) -> str:
    """规范化伏笔核心文本：去空白、标点与常见修饰词，用于跨层对齐。

    只做确定性归一化（不做语义相似度），保证"完全相同才合并"的保守语义。
    """
    text = str(content or "").strip()
    if not text:
        return ""
    # 去掉空白与常见中英文标点
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。、；：！？“”‘’（）《》【】…—,.:;!?'\"()\[\]{}]", "", text)
    # 去掉常见伏笔修饰前缀/后缀词，保留核心名词短语
    for filler in ("关于", "伏笔：", "伏笔:", "伏笔"):
        if text.startswith(filler) and len(text) > len(filler):
            text = text[len(filler):]
    return text.lower()


def _stable_hash(text: str, length: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def make_stable_foreshadow_id(
    content: Any,
    *,
    source: str,
    chapter: Optional[int] = None,
    window_seed: str = "",
) -> str:
    """生成确定性伏笔 ID：同一来源同一核心文本跨运行稳定。

    框架层使用 fs_fw_*（可升级为稳定主档案 ID）；
    章节/卷层使用临时键，仅用于单层去重，不作跨层永久 ID。
    window_seed 用于区分同文本但埋设/揭秘窗口冲突的条目。
    """
    normalized = normalize_foreshadow_content(content)
    digest = _stable_hash(f"{normalized}|{window_seed}" if window_seed else (normalized or str(content or "unknown")))
    if source == "framework":
        return f"fs_fw_{digest}"
    if source == "volume_outline":
        return f"fs_vol_{digest}"
    if chapter:
        return f"fs_ch{int(chapter)}_{digest}"
    return f"fs_ch_{digest}"


def _empty_task(**overrides: Any) -> Dict[str, Any]:
    task: Dict[str, Any] = {
        "id": "",
        "content": "",
        "status": "planned",
        "action": "none",
        "importance": "normal",
        "planted_volume": None,
        "pave_volumes": [],
        "reveal_volume": None,
        "source": "chapter_plan",
        "chapter_requirement": "",
        "evidence": "",
    }
    task.update(overrides)
    return task


def _parse_volume_refs(text: Any) -> List[int]:
    """从"第3,5卷 / 第3卷"等文本提取卷号列表。"""
    refs: List[int] = []
    for match in _VOLUME_REF_RE.finditer(str(text or "")):
        try:
            refs.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return refs


# ---------------------------------------------------------------------------
# 各来源适配
# ---------------------------------------------------------------------------
def adapt_framework_foreshadowing(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """适配 Foreshadowing.to_dict() 结构的框架伏笔。"""
    content = str(item.get("content") or "").strip()
    if not content:
        return None
    status = str(item.get("status") or "planned").strip().lower()
    if status not in UNIFIED_STATUSES:
        # 旧账本状态不强行推断完整生命周期，映射到最近的统一状态
        status = "planned" if status in {"", "planned", "plant"} else "open"
    try:
        planted_volume = int(item.get("planted_volume")) if item.get("planted_volume") is not None else None
    except (TypeError, ValueError):
        planted_volume = None
    try:
        reveal_volume = int(item.get("reveal_volume")) if item.get("reveal_volume") is not None else None
    except (TypeError, ValueError):
        reveal_volume = None
    pave_volumes = [
        int(v) for v in (item.get("pave_volumes") or [])
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit())
    ]
    # 窗口参与 ID 种子：同文本但窗口冲突的条目不会被误并为同一 ID
    window_seed = f"pv{planted_volume}|rv{reveal_volume}" if (planted_volume is not None or reveal_volume is not None) else ""
    return _empty_task(
        id=make_stable_foreshadow_id(content, source="framework", window_seed=window_seed),
        content=content,
        status=status,
        importance=str(item.get("importance") or "normal"),
        planted_volume=planted_volume,
        pave_volumes=sorted(set(pave_volumes)),
        reveal_volume=reveal_volume,
        source="framework",
    )


def adapt_chapter_ledger_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """适配 review_meta.foreshadow_ledger 旧账本条目（open/recovered 兼容映射）。"""
    content = str(entry.get("content") or "").strip()
    if not content:
        return None
    raw_status = str(entry.get("status") or "open").strip().lower()
    if raw_status == "recovered":
        status = "recovered"
    elif raw_status in UNIFIED_STATUSES:
        status = raw_status
    else:
        status = "open"
    planted_chapter = entry.get("planted_chapter")
    try:
        planted_chapter = int(planted_chapter) if planted_chapter is not None else None
    except (TypeError, ValueError):
        planted_chapter = None
    task = _empty_task(
        id=make_stable_foreshadow_id(content, source="chapter_plan", chapter=planted_chapter),
        content=content,
        status=status,
        source="chapter_plan",
    )
    if planted_chapter is not None:
        task["planted_chapter"] = planted_chapter
    if entry.get("recovered_chapter") is not None:
        task["recovered_chapter"] = entry.get("recovered_chapter")
    return task


def adapt_volume_foreshadow_text(text: Any) -> Optional[Dict[str, Any]]:
    """适配卷细纲 new_foreshadowings 中的摘要字符串（无窗口信息的低置信条目）。"""
    content = str(text or "").strip().rstrip("。.")
    # 去掉"伏笔1："类编号前缀
    content = re.sub(r"^伏笔\s*\d+\s*[：:]\s*", "", content)
    if len(content) < 4:
        return None
    return _empty_task(
        id=make_stable_foreshadow_id(content, source="volume_outline"),
        content=content,
        status="open",
        importance="minor",
        source="volume_outline",
    )


# 卷级文本中伏笔条目的引导词（兼容卷细纲渲染与卷摘要的常见写法；
# 引导词与冒号之间容忍括号说明，如"已埋下的伏笔（需在本卷回收）：xxx"）
_VOLUME_FORESHADOW_LABEL_RE = re.compile(
    r"(?:遗留伏笔|已埋下的伏笔|新埋伏笔|新伏笔|伏笔事项|伏笔布局|伏笔)[^：:\n]{0,40}[：:]\s*([^\n]+)"
)


def extract_volume_foreshadow_texts(*texts: Any, max_items: int = 10) -> List[str]:
    """从卷级文本（卷细纲明细/卷上下文）规则提取伏笔摘要条目。

    兼容两类写法：
    - 引导词行："上一卷遗留伏笔：A；B；C" / "伏笔1：xxx"
    - 按 ；;、 分隔的条目拆分；过短/过长条目丢弃。

    纯规则解析，不调用 LLM，不抛异常；无法解析时返回空列表。
    """
    try:
        items: List[str] = []
        for raw_text in texts:
            content = str(raw_text or "")
            if not content or "伏笔" not in content:
                continue
            for match in _VOLUME_FORESHADOW_LABEL_RE.finditer(content):
                segment = re.sub(r"[*#>\-]+", "", match.group(1) or "").strip()
                for part in re.split(r"[；;、\n]+", segment):
                    item = part.strip().rstrip("。.")
                    item = re.sub(r"^伏笔\s*\d+\s*[：:]\s*", "", item)
                    if 4 <= len(item) <= 80 and item not in items:
                        items.append(item)
                    if len(items) >= max_items:
                        return items
        return items
    except Exception:
        return []


def extract_framework_tasks_from_text(framework_text: Any) -> List[Dict[str, Any]]:
    """从长篇框架原文提取框架伏笔任务（仅规则解析，不调用 LLM）。

    复用 ForeshadowingTracker 的表格/列表解析，失败时回退为空列表。
    """
    content = str(framework_text or "").strip()
    if not content:
        return []
    try:
        # 局部导入避免循环依赖；不传 llm，保证纯规则解析
        from app.services.foreshadowing_tracker import ForeshadowingTracker

        tracker = ForeshadowingTracker(project_id=0)
        extracted = tracker.extract_from_framework(content)
    except Exception as exc:
        logger.warning("框架伏笔解析失败，回退为空: %s", exc)
        return []
    tasks: List[Dict[str, Any]] = []
    for fs in extracted or []:
        try:
            task = adapt_framework_foreshadowing(fs.to_dict())
        except Exception:
            continue
        if task:
            tasks.append(task)
    return tasks


# ---------------------------------------------------------------------------
# 跨层合并与动作推导
# ---------------------------------------------------------------------------
def _window_conflicts(existing: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    """揭秘/埋设窗口明显不同时禁止合并（宁可不合并，不误并）。"""
    for field in ("reveal_volume", "planted_volume"):
        existing_value = existing.get(field)
        incoming_value = incoming.get(field)
        if (
            existing_value is not None
            and incoming_value is not None
            and int(existing_value) != int(incoming_value)
        ):
            return True
    return False



def extract_explicit_framework_id(text: Any) -> str:
    raw = str(text or "")
    match = re.search(r"fs_fw_[0-9a-fA-F]{6,}", raw)
    return match.group(0) if match else ""


def _explicit_framework_id(task: Dict[str, Any]) -> str:
    for field in ("framework_id", "id", "content", "chapter_requirement", "evidence"):
        found = extract_explicit_framework_id(task.get(field))
        if found:
            return found
    return ""

def _merge_into(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """将同一条伏笔的另一来源条目合并进已有条目（保守归并）。

    规则：框架层提供窗口与稳定 ID；章节层提供最新执行状态与证据。
    状态只允许向"更已推进"方向覆盖，绝不回退（revealed/recovered 不可被 open 覆盖）。
    """
    status_rank = {
        "planned": 0,
        "planted": 1,
        "open": 1,
        "paving": 2,
        "revealed": 3,
        "recovered": 3,
        "abandoned": 4,
    }
    # ID/来源优先级：framework > volume_outline > chapter_plan
    source_rank = {"framework": 2, "volume_outline": 1, "chapter_plan": 0}
    if source_rank.get(incoming.get("source", ""), 0) > source_rank.get(target.get("source", ""), 0):
        target["id"] = incoming.get("id") or target.get("id")
        target["source"] = incoming.get("source")

    for key in ("planted_volume", "reveal_volume"):
        if target.get(key) is None and incoming.get(key) is not None:
            target[key] = incoming[key]
    if incoming.get("pave_volumes"):
        merged_pave = sorted(set((target.get("pave_volumes") or []) + list(incoming["pave_volumes"])))
        target["pave_volumes"] = merged_pave
    for key in ("planted_chapter", "recovered_chapter", "evidence", "chapter_requirement"):
        if not target.get(key) and incoming.get(key):
            target[key] = incoming[key]
    incoming_rank = status_rank.get(str(incoming.get("status")), 0)
    target_rank = status_rank.get(str(target.get("status")), 0)
    if incoming_rank > target_rank:
        target["status"] = incoming["status"]


def compute_task_action(
    task: Dict[str, Any],
    *,
    current_volume: Optional[int] = None,
    current_chapter: Optional[int] = None,
) -> str:
    """根据伏笔窗口与当前进度推导本章/本卷动作。

    无窗口信息时不做推断（返回 none/continue），避免误判。
    """
    status = str(task.get("status") or "")
    if status in {"revealed", "recovered", "abandoned"}:
        return "none"
    planted_volume = task.get("planted_volume")
    reveal_volume = task.get("reveal_volume")
    pave_volumes = task.get("pave_volumes") or []
    if current_volume is None:
        # 无卷号时不推断窗口动作，未完结条目仅标记持续推进
        return "continue" if status in {"planted", "paving", "open"} else "none"
    if planted_volume is not None and int(planted_volume) == current_volume and status in {"planned", "planted"}:
        return "plant"
    if reveal_volume is not None and int(reveal_volume) == current_volume and status in {"planted", "paving", "open"}:
        return "reveal"
    if current_volume in pave_volumes and status in {"planted", "paving", "open"}:
        return "pave"
    if status in {"planted", "paving", "open"}:
        return "continue"
    return "none"


def build_unified_foreshadow_tasks(
    framework_text: Any = "",
    review_meta: Optional[Dict[str, Any]] = None,
    volume_foreshadow_texts: Optional[List[Any]] = None,
    *,
    framework_items: Optional[List[Dict[str, Any]]] = None,
    current_volume: Optional[int] = None,
    current_chapter: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """合并三层伏笔来源，输出统一任务列表（保守归并 + 动作推导）。

    Args:
        framework_text: 长篇框架原文（用于规则提取框架伏笔）
        review_meta: 项目级 review_meta（读取旧 foreshadow_ledger）
        volume_foreshadow_texts: 卷细纲 new_foreshadowings 摘要字符串列表
        framework_items: 已解析的框架伏笔字典（优先于 framework_text）
        current_volume/current_chapter: 当前进度（用于动作推导）

    Returns:
        按重要性排序的统一任务列表；任何解析失败都不抛异常。
    """
    candidates: List[Dict[str, Any]] = []

    if framework_items:
        for item in framework_items:
            try:
                task = adapt_framework_foreshadowing(item)
            except Exception:
                continue
            if task:
                candidates.append(task)
    elif framework_text:
        candidates.extend(extract_framework_tasks_from_text(framework_text))

    for raw in volume_foreshadow_texts or []:
        task = adapt_volume_foreshadow_text(raw)
        if task:
            candidates.append(task)

    ledger = (review_meta or {}).get("foreshadow_ledger")
    ledger_entries = ledger.get("entries") if isinstance(ledger, dict) else None
    if not isinstance(ledger_entries, list):
        ledger_entries = []
    for entry in ledger_entries:
        if not isinstance(entry, dict):
            continue
        try:
            task = adapt_chapter_ledger_entry(entry)
        except Exception:
            continue
        if task:
            candidates.append(task)

    # 保守归并：规范化文本相同，或显式引用框架 ID，且窗口不冲突才合并
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    id_index: Dict[str, str] = {}
    for task in candidates:
        key = normalize_foreshadow_content(task.get("content"))
        explicit_id = _explicit_framework_id(task)
        if not key and not explicit_id:
            continue
        target_key = ""
        if explicit_id and explicit_id in id_index:
            target_key = id_index[explicit_id]
        elif key and key in merged:
            target_key = key
        if target_key and target_key in merged and _window_conflicts(merged[target_key], task):
            suffix = 1
            while f"{(key or explicit_id)}#{suffix}" in merged:
                suffix += 1
            target_key = f"{(key or explicit_id)}#{suffix}"
            merged[target_key] = task
            order.append(target_key)
        elif target_key and target_key in merged:
            _merge_into(merged[target_key], task)
        else:
            target_key = key or explicit_id
            merged[target_key] = task
            order.append(target_key)
        if explicit_id:
            id_index[explicit_id] = target_key

    tasks = [merged[key] for key in order]
    for task in tasks:
        task["action"] = compute_task_action(
            task,
            current_volume=current_volume,
            current_chapter=current_chapter,
        )

    importance_order = {"critical": 0, "important": 1, "normal": 2, "minor": 3}
    tasks.sort(
        key=lambda t: (
            importance_order.get(str(t.get("importance") or "normal"), 2),
            str(t.get("id") or ""),
        )
    )
    return tasks


# ---------------------------------------------------------------------------
# 提示词投影
# ---------------------------------------------------------------------------
_ACTION_LABELS = {
    "plant": "本章/本卷需埋设",
    "pave": "本章/本卷需铺垫（只暗示，不揭示）",
    "reveal": "本章/本卷需回收",
    "continue": "持续推进中",
}


def format_unified_foreshadow_section(
    tasks: List[Dict[str, Any]],
    *,
    current_chapter: Optional[int] = None,
    max_items: int = 8,
) -> str:
    """将统一任务列表格式化为章节规划提示词区块；无任务时返回空串。"""
    active = [t for t in (tasks or []) if t.get("action") in _ACTION_LABELS]
    open_ledger = [
        t for t in (tasks or [])
        if t.get("action") == "none" and t.get("status") in _UNSETTLED_STATUSES
    ]
    if not active and not open_ledger:
        return ""

    lines: List[str] = []
    shown = 0
    for action in ("reveal", "plant", "pave", "continue"):
        for task in active:
            if shown >= max_items:
                break
            if task.get("action") != action:
                continue
            window = _format_task_window(task)
            lines.append(f"- [{_ACTION_LABELS[action]}] {task.get('content')}{window}")
            shown += 1
    for task in open_ledger:
        if shown >= max_items:
            break
        planted = task.get("planted_chapter")
        age_hint = ""
        if planted and current_chapter:
            age = int(current_chapter) - int(planted)
            if age >= 10:
                age_hint = "（⚠️埋设已久，尽快安排回收）"
        planted_hint = f"（第{planted}章埋设）" if planted else ""
        lines.append(f"- [未回收] {task.get('content')}{planted_hint}{age_hint}")
        shown += 1
    return "\n".join(lines)


def _format_task_window(task: Dict[str, Any]) -> str:
    parts: List[str] = []
    if task.get("planted_volume") is not None:
        parts.append(f"埋设第{task['planted_volume']}卷")
    if task.get("reveal_volume") is not None:
        parts.append(f"揭秘第{task['reveal_volume']}卷")
    if task.get("chapter_requirement"):
        parts.append(f"要求：{task['chapter_requirement']}")
    return f"（{'，'.join(parts)}）" if parts else ""
