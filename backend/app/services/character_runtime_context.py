from __future__ import annotations

import json
import re
from typing import Any, Iterable


RELATION_LABEL_PREFIXES = (
    "\u3010\u5173\u952e\u5173\u7cfb\u3011",
    "\u3010\u5173\u952e\u5173\u7cfb\u00b7\u8865\u5145\u3011",
    "\u5173\u952e\u5173\u7cfb",
)
MAINLINE_ROLE_PREFIXES = (
    "\u5267\u60c5\u804c\u8d23",
    "\u4e3b\u7ebf\u804c\u8d23",
)
MAINLINE_CLUE_PREFIXES = (
    "\u5173\u8054\u7ebf\u7d22",
    "\u4e3b\u7ebf\u7ebf\u7d22",
)

RELATION_ACTIVE_KEYWORDS = (
    "\u4e3b\u89d2",
    "\u76df\u53cb",
    "\u5bfc\u5e08",
    "\u5bf9\u624b",
    "\u654c\u4eba",
    "\u96c7\u4e3b",
    "\u5e87\u62a4\u8005",
    "\u76d1\u89c6\u8005",
    "\u8ffd\u6355",
    "\u8ffd\u6740",
    "\u5408\u4f5c",
    "\u9886\u8896",
    "\u652f\u6301\u8005",
    "\u89c2\u5bdf\u8005",
    "\u5a01\u80c1",
    "\u6311\u6218\u8005",
    "\u5408\u4f5c\u8005",
    "\u5f15\u8def\u4eba",
    "\u540c\u76df",
    "\u540c\u4f34",
    "\u5b88\u62a4",
    "\u5ba1\u89c6\u8005",
    "\u5173\u952e\u6218\u529b",
)
RELATION_RESOLVED_KEYWORDS = (
    "\u5df2\u51fb\u6740",
    "\u5df2\u6b7b\u4ea1",
    "\u5df2\u5904\u7406",
    "\u5df2\u89e3\u51b3",
    "\u5df2\u6e05\u9664",
    "\u6b7b\u4ea1\u63ed\u793a",
    "\u5f15\u53d1\u7684\u8fde\u9501\u53cd\u5e94\u5df2\u88ab\u5904\u7406",
)
RELATION_INDIRECT_KEYWORDS = (
    "\u95f4\u63a5",
    "\u6f5c\u5728",
    "\u53ef\u80fd",
    "\u66f4\u5371\u9669",
    "\u89c2\u5bdf\u6837\u672c",
    "\u4fe1\u606f\u6e90",
    "\u77e5\u8bc6\u6765\u6e90",
)
MAINLINE_ACTIVE_KEYWORDS = (
    "\u5f53\u524d",
    "\u672c\u5377",
    "\u5e94\u5bf9",
    "\u5904\u7406",
    "\u6574\u5408",
    "\u6784\u5efa",
    "\u5e26\u961f",
    "\u63a2\u7d22",
    "\u57f9\u517b",
    "\u9886\u5bfc\u8005",
    "\u65b0\u589e",
    "\u9996\u6b21",
    "\u9700",
)
MAINLINE_RESOLVED_KEYWORDS = (
    "\u5df2\u5b8c\u6210",
    "\u5df2\u5904\u7406",
    "\u5df2\u88ab\u5904\u7406",
    "\u5df2\u89e3\u51b3",
    "\u6b7b\u4ea1\u63ed\u793a",
)

_INLINE_SPLIT_PATTERN = re.compile(r"[;\uff1b\n]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)\u3001]\s*)")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return _WHITESPACE_PATTERN.sub(" ", text)


def _truncate_text(text: str, limit: int) -> str:
    normalized = _clean_text(text)
    if not normalized or limit <= 0 or len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return normalized[:limit]
    return normalized[: limit - 3].rstrip() + "..."


def _strip_prefixes(text: str, prefixes: Iterable[str]) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    for prefix in prefixes:
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix):].lstrip("\uff1a: ")
            if stripped:
                return stripped
    return normalized


def _split_inline_segments(text: Any) -> list[str]:
    normalized = _clean_text(text)
    if not normalized:
        return []

    segments: list[str] = []
    for chunk in _INLINE_SPLIT_PATTERN.split(normalized.replace("\r", "\n")):
        candidate = _BULLET_PREFIX_PATTERN.sub("", chunk).strip()
        if candidate:
            segments.append(candidate)
    return segments


def _score_text(
    text: str,
    *,
    active_keywords: tuple[str, ...],
    resolved_keywords: tuple[str, ...],
) -> int:
    score = 0
    for keyword in active_keywords:
        if keyword in text:
            score += 6
    for keyword in resolved_keywords:
        if keyword in text:
            score -= 18
    return score


def _dedupe_texts(values: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        text = _clean_text(raw_value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _extract_relation_type_and_description(detail: str) -> tuple[str, str]:
    normalized = _clean_text(detail)
    if not normalized:
        return "", ""

    for separator in ("/", "\uff0f", "|", "\uff5c"):
        if separator in normalized:
            head, tail = normalized.split(separator, 1)
            relation_type = _clean_text(head)
            description = _clean_text(tail)
            if relation_type and description:
                return relation_type, description

    first_fragment = re.split(r"[\uff0c,()\uff08\uff09]", normalized, maxsplit=1)[0].strip()
    if first_fragment and len(first_fragment) <= 18 and len(normalized) > len(first_fragment):
        description = normalized[len(first_fragment):].lstrip("\uff0c,\uff08(").rstrip("\uff09)").strip()
        if description:
            return first_fragment, description

    return _truncate_text(normalized, 18), normalized


def _relation_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    return (-int(item.get("priority") or 0), int(item.get("order") or 0))


def _build_relation_detail(item: dict[str, Any]) -> str:
    detail = _clean_text(item.get("detail"))
    if detail:
        return detail
    relation_type = _clean_text(item.get("type"))
    description = _clean_text(item.get("description"))
    if relation_type and description:
        return f"{relation_type}/{description}"
    return relation_type or description


def _format_relation_summary_item(item: dict[str, Any]) -> str:
    target = _clean_text(item.get("target"))
    relation_text = _build_relation_detail(item)
    if not relation_text:
        return ""
    if target:
        return f"{target}\uff1a{relation_text}"
    return relation_text


def _normalize_mainline_source_text(text: str) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    replacements = (
        (" / \u5173\u8054\u7ebf\u7d22", "\uff1b\u5173\u8054\u7ebf\u7d22"),
        ("/\u5173\u8054\u7ebf\u7d22", "\uff1b\u5173\u8054\u7ebf\u7d22"),
        ("\uff0f\u5173\u8054\u7ebf\u7d22", "\uff1b\u5173\u8054\u7ebf\u7d22"),
        (" / \u5267\u60c5\u804c\u8d23", "\uff1b\u5267\u60c5\u804c\u8d23"),
        ("/\u5267\u60c5\u804c\u8d23", "\uff1b\u5267\u60c5\u804c\u8d23"),
        ("\uff0f\u5267\u60c5\u804c\u8d23", "\uff1b\u5267\u60c5\u804c\u8d23"),
    )
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = _clean_text(text)
    return any(keyword in normalized for keyword in keywords)


def extract_character_relation_items(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = text
        else:
            return extract_character_relation_items(parsed)

        entries: list[dict[str, Any]] = []
        raw_text = _strip_prefixes(parsed, RELATION_LABEL_PREFIXES)
        for index, segment in enumerate(_split_inline_segments(raw_text)):
            target = ""
            detail = segment
            for separator in ("\uff1a", ":"):
                if separator in segment:
                    target, detail = segment.split(separator, 1)
                    target = _clean_text(target)
                    detail = _clean_text(detail)
                    break
            relation_type, description = _extract_relation_type_and_description(detail)
            text_for_score = f"{target} {relation_type} {description or detail}"
            priority = 100 - index
            priority += _score_text(
                text_for_score,
                active_keywords=RELATION_ACTIVE_KEYWORDS,
                resolved_keywords=RELATION_RESOLVED_KEYWORDS,
            )
            for keyword in RELATION_INDIRECT_KEYWORDS:
                if keyword in text_for_score:
                    priority -= 6
            entries.append(
                {
                    "target": target,
                    "type": relation_type,
                    "description": description if description and description != relation_type else "",
                    "detail": detail,
                    "raw_text": segment,
                    "priority": priority,
                    "order": index,
                }
            )
        return entries

    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            entries: list[dict[str, Any]] = []
            for item in value["items"]:
                entries.extend(extract_character_relation_items(item))
            if entries:
                return entries

        raw_text = _clean_text(value.get("text"))
        if raw_text:
            return extract_character_relation_items(raw_text)

        target = _clean_text(value.get("target") or value.get("name"))
        relation_type = _clean_text(value.get("type") or value.get("relation_type"))
        description = _clean_text(
            value.get("description") or value.get("detail") or value.get("notes")
        )
        detail = description or relation_type
        if not (target or detail):
            return []
        priority = int(value.get("priority") or 0)
        if priority <= 0:
            priority = 100 + _score_text(
                f"{target} {relation_type} {detail}",
                active_keywords=RELATION_ACTIVE_KEYWORDS,
                resolved_keywords=RELATION_RESOLVED_KEYWORDS,
            )
        return [
            {
                "target": target,
                "type": relation_type,
                "description": description if description and description != relation_type else "",
                "detail": detail,
                "raw_text": _clean_text(value.get("raw_text")) or "",
                "priority": priority,
                "order": int(value.get("order") or 0),
            }
        ]

    if isinstance(value, list):
        entries: list[dict[str, Any]] = []
        for item in value:
            entries.extend(extract_character_relation_items(item))
        return entries

    return []


def normalize_character_relations_payload(value: Any) -> dict[str, Any] | None:
    if value in (None, "", {}):
        return None

    if isinstance(value, dict):
        if any(key in value for key in ("items", "text", "current_summary", "version")):
            return build_character_relations_payload(value)

        legacy_items: list[dict[str, Any]] = []
        unsupported_keys = 0
        for raw_target, raw_relation in value.items():
            target = _clean_text(raw_target)
            if not target:
                unsupported_keys += 1
                continue

            if isinstance(raw_relation, dict):
                relation_type = _clean_text(
                    raw_relation.get("type") or raw_relation.get("relation_type")
                )
                description = _clean_text(
                    raw_relation.get("description")
                    or raw_relation.get("detail")
                    or raw_relation.get("notes")
                )
                if relation_type or description:
                    legacy_items.append(
                        {
                            "target": target,
                            "type": relation_type,
                            "description": description,
                            "detail": description or relation_type,
                        }
                    )
                    continue
                unsupported_keys += 1
                continue

            relation_text = _clean_text(raw_relation)
            if relation_text:
                legacy_items.append({"target": target, "type": relation_text, "detail": relation_text})
            else:
                unsupported_keys += 1

        if legacy_items and unsupported_keys == 0:
            return build_character_relations_payload({"items": legacy_items})

    return build_character_relations_payload(value)


def build_character_relations_payload(
    value: Any,
    *,
    max_current_items: int = 5,
    max_current_chars: int = 220,
) -> dict[str, Any]:
    if isinstance(value, str):
        raw_text = _strip_prefixes(value, RELATION_LABEL_PREFIXES)
    elif isinstance(value, dict):
        raw_text = _clean_text(value.get("text"))
    else:
        raw_text = ""

    entries = extract_character_relation_items(value)
    deduped_items: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in sorted(entries, key=_relation_sort_key):
        target = _clean_text(item.get("target"))
        relation_type = _clean_text(item.get("type"))
        detail = _build_relation_detail(item)
        if not (target or detail):
            continue
        key = (target, relation_type, detail)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_items.append(
            {
                "target": target,
                "type": relation_type,
                "description": _clean_text(item.get("description")),
                "detail": detail,
                "priority": int(item.get("priority") or 0),
            }
        )

    summary_parts: list[str] = []
    preferred_items = [
        item for item in deduped_items
        if not _contains_any_keyword(_format_relation_summary_item(item), RELATION_RESOLVED_KEYWORDS)
    ] or deduped_items

    for item in preferred_items:
        formatted = _truncate_text(_format_relation_summary_item(item), 72)
        if not formatted:
            continue
        projected = "\uff1b".join(summary_parts + [formatted])
        if summary_parts and len(projected) > max_current_chars:
            break
        summary_parts.append(formatted)
        if len(summary_parts) >= max_current_items:
            break

    if not raw_text and deduped_items:
        raw_text = "\uff1b".join(
            _format_relation_summary_item(item) for item in deduped_items if _format_relation_summary_item(item)
        )

    return {
        "version": 2,
        "text": raw_text,
        "current_summary": "\uff1b".join(summary_parts),
        "items": deduped_items,
    }


def build_current_relationship_summary(
    value: Any,
    *,
    max_items: int = 5,
    max_chars: int = 220,
) -> str:
    payload = build_character_relations_payload(
        value,
        max_current_items=max_items,
        max_current_chars=max_chars,
    )
    return _clean_text(payload.get("current_summary"))


def _append_mainline_segment(
    segment: str,
    *,
    role_segments: list[str],
    clue_segments: list[str],
    bucket: str,
) -> str:
    if bucket == "role":
        role_segments.append(segment)
    elif bucket == "clue":
        clue_segments.append(segment)
    return bucket


def _collect_binding_segments(
    value: Any,
    *,
    role_segments: list[str],
    clue_segments: list[str],
    default_bucket: str = "",
) -> None:
    if value in (None, ""):
        return

    if isinstance(value, dict):
        for candidate in (
            value.get("text"),
            value.get("current_summary"),
            value.get("summary"),
        ):
            _collect_binding_segments(
                candidate,
                role_segments=role_segments,
                clue_segments=clue_segments,
                default_bucket=default_bucket,
            )
        return

    if isinstance(value, list):
        for item in value:
            _collect_binding_segments(
                item,
                role_segments=role_segments,
                clue_segments=clue_segments,
                default_bucket=default_bucket,
            )
        return

    text = _normalize_mainline_source_text(_clean_text(value))
    if not text:
        return

    current_bucket = ""
    for segment in _split_inline_segments(text):
        normalized = _clean_text(segment)
        if not normalized:
            continue

        matched = False
        for prefix in MAINLINE_ROLE_PREFIXES:
            for marker in (f"{prefix}\uff1a", f"{prefix}:"):
                if normalized.startswith(marker):
                    remainder = _clean_text(normalized[len(marker):])
                    if remainder:
                        role_segments.append(remainder)
                    current_bucket = "role"
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue

        for prefix in MAINLINE_CLUE_PREFIXES:
            for marker in (f"{prefix}\uff1a", f"{prefix}:"):
                if normalized.startswith(marker):
                    remainder = _clean_text(normalized[len(marker):])
                    if remainder:
                        clue_segments.append(remainder)
                    current_bucket = "clue"
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue

        current_bucket = _append_mainline_segment(
            normalized,
            role_segments=role_segments,
            clue_segments=clue_segments,
            bucket=current_bucket or default_bucket,
        )


def build_current_mainline_summary(
    mainline_role: Any,
    mainline_clues: Any = None,
    *,
    max_role_items: int = 2,
    max_clue_items: int = 3,
    max_chars: int = 240,
) -> str:
    role_segments: list[str] = []
    clue_segments: list[str] = []

    _collect_binding_segments(
        mainline_role,
        role_segments=role_segments,
        clue_segments=clue_segments,
        default_bucket="role",
    )
    _collect_binding_segments(
        mainline_clues,
        role_segments=role_segments,
        clue_segments=clue_segments,
        default_bucket="clue",
    )

    def _pick_segments(
        raw_segments: list[str],
        *,
        max_items: int,
        active_keywords: tuple[str, ...],
        resolved_keywords: tuple[str, ...],
    ) -> list[str]:
        scored: list[tuple[int, int, str]] = []
        for index, raw_segment in enumerate(_dedupe_texts(raw_segments)):
            priority = 100 - index
            priority += _score_text(
                raw_segment,
                active_keywords=active_keywords,
                resolved_keywords=resolved_keywords,
            )
            scored.append((priority, index, raw_segment))
        scored.sort(key=lambda item: (-item[0], item[1]))
        preferred = [
            item for item in scored
            if not _contains_any_keyword(item[2], resolved_keywords)
        ] or scored
        return [_truncate_text(item[2], 72) for item in preferred[:max_items]]

    selected_roles = _pick_segments(
        role_segments,
        max_items=max_role_items,
        active_keywords=MAINLINE_ACTIVE_KEYWORDS,
        resolved_keywords=MAINLINE_RESOLVED_KEYWORDS,
    )
    selected_clues = _pick_segments(
        clue_segments,
        max_items=max_clue_items,
        active_keywords=MAINLINE_ACTIVE_KEYWORDS,
        resolved_keywords=MAINLINE_RESOLVED_KEYWORDS,
    )

    parts: list[str] = []
    if selected_roles:
        parts.append(f"\u5267\u60c5\u804c\u8d23\uff1a{'\uff1b'.join(selected_roles)}")
    if selected_clues:
        parts.append(f"\u5173\u8054\u7ebf\u7d22\uff1a{'\uff1b'.join(selected_clues)}")
    return _truncate_text("\uff1b".join(parts), max_chars)


def build_character_runtime_brief(
    *,
    name: str,
    role: Any = None,
    role_position: Any = None,
    faction: Any = None,
    motivation: Any = None,
    relationships: Any = None,
    mainline_role: Any = None,
    mainline_clues: Any = None,
    max_length: int = 320,
) -> str:
    name_text = _clean_text(name)
    if not name_text:
        return ""

    identity_parts = [
        _clean_text(role_position),
        _clean_text(role),
    ]
    identity_parts = [part for part in identity_parts if part]
    if len(identity_parts) < 2:
        faction_text = _clean_text(faction)
        if faction_text:
            identity_parts.append(faction_text)

    title = f"{name_text}\uff08{' / '.join(identity_parts[:2])}\uff09" if identity_parts[:2] else name_text

    fragments: list[str] = [title]

    motivation_text = _truncate_text(_clean_text(motivation), 44)
    if motivation_text:
        fragments.append(f"\u52a8\u673a\uff1a{motivation_text}")

    relationship_text = build_current_relationship_summary(
        relationships,
        max_items=4,
        max_chars=160,
    )
    if relationship_text:
        fragments.append(f"\u5f53\u524d\u5173\u7cfb\uff1a{relationship_text}")

    mainline_text = build_current_mainline_summary(
        mainline_role,
        mainline_clues,
        max_role_items=2,
        max_clue_items=2,
        max_chars=160,
    )
    if mainline_text:
        fragments.append(f"\u5f53\u524d\u4e3b\u7ebf\uff1a{mainline_text}")

    return _truncate_text(" | ".join(fragment for fragment in fragments if fragment), max_length)


def build_character_runtime_metadata(name: str, profile_text: Any) -> dict[str, str]:
    from app.services.character_parser import CharacterTextParser

    profile = _clean_text(profile_text)
    if not profile:
        return {}

    parser = CharacterTextParser()
    parse_source = profile
    has_heading = "\u3010\u59d3\u540d\u3011" in parse_source or re.search(r"^\s*###", parse_source, re.MULTILINE)
    if not has_heading:
        fallback_name = _clean_text(name) or "\u672a\u547d\u540d\u89d2\u8272"
        parse_source = f"### \u3010\u59d3\u540d\u3011\uff1a{fallback_name}\n{profile}"

    parsed = parser.parse_all_characters(parse_source)
    if not parsed:
        summary = _truncate_text(profile, 220)
        return {"runtime_summary": f"{_clean_text(name) or '\u89d2\u8272'}\uff1a{summary}" if summary else ""}

    first = parsed[0]
    current_relationships = build_current_relationship_summary(first.relationships)
    current_mainline = build_current_mainline_summary(first.mainline_role, first.mainline_clues)
    runtime_summary = build_character_runtime_brief(
        name=first.name or _clean_text(name),
        role=first.role,
        role_position=first.role_position,
        faction=first.faction,
        motivation=first.motivation,
        relationships=first.relationships,
        mainline_role=first.mainline_role,
        mainline_clues=first.mainline_clues,
    )
    return {
        "runtime_summary": runtime_summary,
        "current_relationships": current_relationships,
        "current_mainline": current_mainline,
    }


def build_character_prompt_context_from_text(
    characters_text: Any,
    *,
    detail_limit: int,
    summary_limit: int = 1800,
    max_characters: int = 8,
) -> str:
    from app.services.character_parser import CharacterTextParser

    content = str(characters_text or "").strip()
    if not content:
        return ""

    parser = CharacterTextParser()
    parsed_characters = parser.parse_all_characters(content)
    if not parsed_characters:
        return _truncate_text(content, max(detail_limit, summary_limit))

    roster_lines: list[str] = []
    for index, character in enumerate(parsed_characters[:max_characters], 1):
        name = _clean_text(character.name)
        position = _clean_text(character.role_position)
        stance = _clean_text(character.role)
        if position:
            roster_lines.append(f"{index}. {name}\uff08{position}\uff09")
        elif stance:
            roster_lines.append(f"{index}. {name}\uff08{stance}\uff09")
        else:
            roster_lines.append(f"{index}. {name}")
    roster_summary = _truncate_text("\n".join(roster_lines), summary_limit)

    detail_lines: list[str] = []
    current_length = 0
    detail_truncated = False
    for character in parsed_characters[:max_characters]:
        brief = build_character_runtime_brief(
            name=character.name,
            role=character.role,
            role_position=character.role_position,
            faction=character.faction,
            motivation=character.motivation,
            relationships=character.relationships,
            mainline_role=character.mainline_role,
            mainline_clues=character.mainline_clues,
            max_length=220,
        )
        if not brief:
            continue
        candidate = f"- {brief}"
        projected_length = current_length + len(candidate) + (1 if detail_lines else 0)
        if detail_lines and projected_length > detail_limit:
            detail_truncated = True
            break
        if not detail_lines and len(candidate) > detail_limit:
            detail_lines.append(_truncate_text(candidate, detail_limit))
            detail_truncated = True
            current_length = len(detail_lines[0])
            break
        detail_lines.append(candidate)
        current_length = projected_length

    if len(parsed_characters) > len(detail_lines):
        detail_truncated = True

    detail_excerpt = "\n".join(detail_lines)
    if not detail_excerpt:
        detail_excerpt = _truncate_text(content, detail_limit)

    if detail_truncated:
        truncation_note = "\uff08\u5df2\u622a\u65ad\uff0c\u4ec5\u4fdd\u7559\u53ef\u8c03\u7528\u7684\u4eba\u7269\u8fd0\u884c\u6458\u8981\uff09"
        if detail_excerpt:
            detail_excerpt = f"{detail_excerpt}\n{truncation_note}"
        else:
            detail_excerpt = truncation_note

    if roster_summary:
        return (
            f"\u3010\u89d2\u8272\u540d\u5355\u6458\u8981\u3011\n{roster_summary}\n\n"
            f"\u3010\u4eba\u7269\u8fd0\u884c\u6458\u8981\u3011\n{detail_excerpt}"
        )
    return detail_excerpt
