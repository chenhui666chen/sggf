from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Sequence


def load_summary_data(summary_data: Any) -> Dict[str, Any]:
    if isinstance(summary_data, dict):
        return dict(summary_data)

    if isinstance(summary_data, str):
        try:
            decoded = json.loads(summary_data)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}

    return {}


def _clean_text(value: Any, *, max_length: int = 120) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def _dict_to_text(value: Dict[str, Any], *, max_length: int = 120) -> str:
    ordered_keys = (
        "name",
        "type",
        "goal",
        "event",
        "content",
        "description",
        "summary",
        "text",
        "hook",
        "stakes",
        "result",
        "status",
    )
    parts: List[str] = []
    for key in ordered_keys:
        item = _clean_text(value.get(key), max_length=max_length)
        if item and item not in parts:
            parts.append(item)

    if not parts:
        for item in value.values():
            normalized = _clean_text(item, max_length=max_length)
            if normalized and normalized not in parts:
                parts.append(normalized)

    return " / ".join(parts[:3])


def _normalize_item(value: Any, *, max_length: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return _dict_to_text(value, max_length=max_length)
    if isinstance(value, list):
        items = _normalize_list(value, max_items=3, max_length=max_length)
        return " / ".join(items)
    return _clean_text(value, max_length=max_length)


def _normalize_list(value: Any, *, max_items: int = 5, max_length: int = 80) -> List[str]:
    if value is None:
        return []

    raw_items: List[Any]
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    items: List[str] = []
    seen = set()
    for raw in raw_items:
        text = _normalize_item(raw, max_length=max_length)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= max_items:
            break
    return items


def _merge_missing(existing: Any, computed: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(existing, dict):
        return computed

    merged = dict(existing)
    for key, value in computed.items():
        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
    return merged


def _first_non_empty(values: Iterable[Any], *, max_length: int = 120) -> str:
    for value in values:
        text = _normalize_item(value, max_length=max_length)
        if text:
            return text
    return ""


def _format_conflict(conflict_arc: Any) -> str:
    if isinstance(conflict_arc, dict):
        parts = [
            _clean_text(conflict_arc.get("type"), max_length=30),
            _clean_text(conflict_arc.get("description"), max_length=80),
            _clean_text(conflict_arc.get("stakes"), max_length=60),
            _clean_text(conflict_arc.get("result"), max_length=40),
            _clean_text(conflict_arc.get("status"), max_length=30),
        ]
        parts = [part for part in parts if part]
        return " / ".join(parts[:4])
    return _normalize_item(conflict_arc, max_length=120)


def _format_highlight(highlight: Any) -> str:
    if isinstance(highlight, dict):
        parts = [
            _clean_text(highlight.get("type"), max_length=30),
            _clean_text(
                highlight.get("description")
                or highlight.get("content")
                or highlight.get("summary"),
                max_length=80,
            ),
        ]
        parts = [part for part in parts if part]
        return " / ".join(parts[:2])
    return _normalize_item(highlight, max_length=100)


def _format_hook(ending_hook: Any, hooks: Any) -> str:
    hook_text = _normalize_item(ending_hook, max_length=100)
    if hook_text:
        return hook_text
    hook_items = _normalize_list(hooks, max_items=2, max_length=80)
    return " / ".join(hook_items)


def build_audio_adaptation_hint(
    summary_data: Any,
    *,
    chapter_title: str = "",
    chapter_summary: str = "",
) -> Dict[str, Any]:
    summary = load_summary_data(summary_data)
    existing_hint = summary.get("audio_adaptation_hint")

    scene_goal = _normalize_item(summary.get("scene_goal"), max_length=80)
    key_events = _normalize_list(summary.get("key_events"), max_items=4, max_length=60)
    characters = _normalize_list(
        summary.get("appearing_characters") or summary.get("key_characters"),
        max_items=6,
        max_length=24,
    )
    conflict_text = _format_conflict(summary.get("conflict_arc"))
    emotion_curve = _normalize_item(summary.get("emotion_curve"), max_length=60)
    highlight_text = _format_highlight(summary.get("highlight"))
    ending_hook = _format_hook(summary.get("ending_hook"), summary.get("hooks"))
    foreshadowing = _normalize_list(summary.get("foreshadowing"), max_items=3, max_length=60)

    highlight_scenes = _normalize_list(
        [scene_goal, *key_events, highlight_text],
        max_items=4,
        max_length=70,
    )
    dialogue_conflicts = _normalize_list(
        [conflict_text, ending_hook, *foreshadowing],
        max_items=4,
        max_length=80,
    )
    soundscape_cues = _normalize_list(
        [highlight_text, scene_goal, *key_events[:2], *foreshadowing[:1]],
        max_items=4,
        max_length=70,
    )

    computed = {
        "narration_focus": _first_non_empty(
            [
                summary.get("core_summary"),
                chapter_summary,
                scene_goal,
                chapter_title,
            ],
            max_length=100,
        ),
        "voice_cast": characters,
        "emotion_curve": emotion_curve,
        "highlight_scenes": highlight_scenes,
        "dialogue_conflicts": dialogue_conflicts,
        "soundscape_cues": soundscape_cues,
        "ending_hook": ending_hook,
    }
    return _merge_missing(existing_hint, computed)


def build_drama_adaptation_hint(
    summary_data: Any,
    *,
    chapter_title: str = "",
    chapter_summary: str = "",
) -> Dict[str, Any]:
    summary = load_summary_data(summary_data)
    existing_hint = summary.get("drama_adaptation_hint")

    scene_goal = _normalize_item(summary.get("scene_goal"), max_length=80)
    key_events = _normalize_list(summary.get("key_events"), max_items=4, max_length=60)
    characters = _normalize_list(
        summary.get("appearing_characters") or summary.get("key_characters"),
        max_items=6,
        max_length=24,
    )
    conflict_text = _format_conflict(summary.get("conflict_arc"))
    emotion_curve = _normalize_item(summary.get("emotion_curve"), max_length=60)
    highlight_text = _format_highlight(summary.get("highlight"))
    ending_hook = _format_hook(summary.get("ending_hook"), summary.get("hooks"))
    foreshadowing = _normalize_list(summary.get("foreshadowing"), max_items=3, max_length=60)
    gains = _normalize_list(summary.get("gains"), max_items=3, max_length=60)

    computed = {
        "episode_premise": _first_non_empty(
            [
                summary.get("core_summary"),
                chapter_summary,
                scene_goal,
                chapter_title,
            ],
            max_length=100,
        ),
        "scene_objective": scene_goal,
        "character_focus": characters,
        "key_beats": _normalize_list(
            [scene_goal, *key_events, highlight_text, *gains],
            max_items=5,
            max_length=70,
        ),
        "visual_hooks": _normalize_list(
            [highlight_text, ending_hook, *foreshadowing],
            max_items=4,
            max_length=70,
        ),
        "core_conflict": conflict_text,
        "emotion_curve": emotion_curve,
        "ending_hook": ending_hook,
    }
    return _merge_missing(existing_hint, computed)


def build_cross_media_adaptation_hints(
    summary_data: Any,
    *,
    chapter_title: str = "",
    chapter_summary: str = "",
) -> Dict[str, Dict[str, Any]]:
    return {
        "audio_adaptation_hint": build_audio_adaptation_hint(
            summary_data,
            chapter_title=chapter_title,
            chapter_summary=chapter_summary,
        ),
        "drama_adaptation_hint": build_drama_adaptation_hint(
            summary_data,
            chapter_title=chapter_title,
            chapter_summary=chapter_summary,
        ),
    }


def attach_cross_media_adaptation_hints(
    summary_data: Any,
    *,
    chapter_title: str = "",
    chapter_summary: str = "",
) -> Dict[str, Any]:
    summary = load_summary_data(summary_data)
    hints = build_cross_media_adaptation_hints(
        summary,
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
    )
    summary.update(hints)
    return summary


def format_audio_adaptation_brief(audio_hint: Any) -> str:
    if not isinstance(audio_hint, dict):
        return ""

    lines = ["【有声书改编提示】"]

    focus = _clean_text(audio_hint.get("narration_focus"), max_length=100)
    if focus:
        lines.append(f"- 叙述重点: {focus}")

    voice_cast = _normalize_list(audio_hint.get("voice_cast"), max_items=6, max_length=24)
    if voice_cast:
        lines.append(f"- 重点角色: {' / '.join(voice_cast)}")

    emotion_curve = _clean_text(audio_hint.get("emotion_curve"), max_length=60)
    if emotion_curve:
        lines.append(f"- 情绪曲线: {emotion_curve}")

    highlight_scenes = _normalize_list(audio_hint.get("highlight_scenes"), max_items=4, max_length=70)
    if highlight_scenes:
        lines.append(f"- 高光场景: {' | '.join(highlight_scenes)}")

    dialogue_conflicts = _normalize_list(audio_hint.get("dialogue_conflicts"), max_items=4, max_length=80)
    if dialogue_conflicts:
        lines.append(f"- 冲突/对白抓手: {' | '.join(dialogue_conflicts)}")

    soundscape_cues = _normalize_list(audio_hint.get("soundscape_cues"), max_items=4, max_length=70)
    if soundscape_cues:
        lines.append(f"- 音效着力点: {' | '.join(soundscape_cues)}")

    ending_hook = _clean_text(audio_hint.get("ending_hook"), max_length=80)
    if ending_hook:
        lines.append(f"- 结尾钩子: {ending_hook}")

    return "\n".join(lines) if len(lines) > 1 else ""


def format_drama_adaptation_brief(drama_hint: Any) -> str:
    if not isinstance(drama_hint, dict):
        return ""

    lines = ["【短剧改编提示】"]

    premise = _clean_text(drama_hint.get("episode_premise"), max_length=100)
    if premise:
        lines.append(f"- 本集驱动: {premise}")

    objective = _clean_text(drama_hint.get("scene_objective"), max_length=80)
    if objective:
        lines.append(f"- 场景目标: {objective}")

    character_focus = _normalize_list(drama_hint.get("character_focus"), max_items=6, max_length=24)
    if character_focus:
        lines.append(f"- 出场角色: {' / '.join(character_focus)}")

    core_conflict = _clean_text(drama_hint.get("core_conflict"), max_length=90)
    if core_conflict:
        lines.append(f"- 核心冲突: {core_conflict}")

    key_beats = _normalize_list(drama_hint.get("key_beats"), max_items=5, max_length=70)
    if key_beats:
        lines.append(f"- 剧情节拍: {' | '.join(key_beats)}")

    visual_hooks = _normalize_list(drama_hint.get("visual_hooks"), max_items=4, max_length=70)
    if visual_hooks:
        lines.append(f"- 视觉钩子: {' | '.join(visual_hooks)}")

    emotion_curve = _clean_text(drama_hint.get("emotion_curve"), max_length=60)
    if emotion_curve:
        lines.append(f"- 情绪推进: {emotion_curve}")

    ending_hook = _clean_text(drama_hint.get("ending_hook"), max_length=80)
    if ending_hook:
        lines.append(f"- 集尾悬念: {ending_hook}")

    return "\n".join(lines) if len(lines) > 1 else ""


def build_drama_source_text(chapters: Sequence[Any]) -> str:
    sections: List[str] = []

    for chapter in chapters:
        title = _clean_text(getattr(chapter, "title", "") or "Untitled Chapter", max_length=120)
        content = str(getattr(chapter, "content", "") or "").strip()
        summary = _clean_text(getattr(chapter, "summary", ""), max_length=120)
        raw_summary_data = getattr(chapter, "summary_data", None)

        summary_data = attach_cross_media_adaptation_hints(
            raw_summary_data,
            chapter_title=title,
            chapter_summary=summary,
        )
        drama_brief = format_drama_adaptation_brief(summary_data.get("drama_adaptation_hint"))

        parts = [title]
        if summary:
            parts.append(f"【核心摘要】\n{summary}")
        if drama_brief:
            parts.append(drama_brief)
        if content:
            parts.append(f"【正文】\n{content}")

        section = "\n".join(part for part in parts if part).strip()
        if section:
            sections.append(section)

    return "\n\n".join(sections)
