"""有声小说改编保真审计工具。"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from ._dataclasses import ScriptSegment


HIGH_RISK_FACT_TERMS = {
    "刀": ("刀", "长刀", "短刀"),
    "剑": ("剑", "长剑", "飞剑"),
    "鞭": ("鞭", "长鞭", "软鞭"),
    "枪": ("枪", "长枪"),
    "弓": ("弓", "弓箭"),
    "箭": ("箭", "弓箭"),
}


def audit_script_fidelity(source_text: str, segments: Iterable[ScriptSegment]) -> Dict[str, Any]:
    """审计生成剧本相对原文的高风险保真问题，仅报告，不自动修文。"""
    source = str(source_text or "")
    generated_text = _join_segment_text(segments)
    source_compact = _compact_text(source)
    generated_compact = _compact_text(generated_text)

    missing_source_quotes = [
        quote
        for quote in _extract_source_quotes(source)
        if quote and quote not in generated_compact
    ]
    unsupported_terms = _find_unsupported_terms(source, generated_text)
    unsupported_dialogue = _find_unsupported_dialogue(source_compact, segments)

    return {
        "has_issues": bool(missing_source_quotes or unsupported_terms or unsupported_dialogue),
        "missing_source_quotes": missing_source_quotes,
        "unsupported_terms": unsupported_terms,
        "unsupported_dialogue": unsupported_dialogue,
        "generated_chars": len(generated_text),
        "source_chars": len(source),
    }


def _join_segment_text(segments: Iterable[ScriptSegment]) -> str:
    return "".join(str(getattr(segment, "text", "") or "") for segment in segments or [])


def _extract_source_quotes(source_text: str) -> List[str]:
    quotes: List[str] = []
    for pattern in (r"“([^”]+)”", r"「([^」]+)」", r"『([^』]+)』", r'"([^"]+)"'):
        for match in re.finditer(pattern, source_text or ""):
            quote = _compact_text(match.group(1))
            if quote:
                quotes.append(quote)
    return quotes


def _find_unsupported_terms(source_text: str, generated_text: str) -> List[Dict[str, Any]]:
    source_compact = _compact_text(source_text)
    generated_compact = _compact_text(generated_text)
    issues: List[Dict[str, Any]] = []

    for base_term, variants in HIGH_RISK_FACT_TERMS.items():
        if base_term in source_compact:
            continue
        generated_variants: List[str] = []
        for variant in sorted(variants, key=len, reverse=True):
            if variant not in generated_compact:
                continue
            if any(variant in selected for selected in generated_variants):
                continue
            generated_variants.append(variant)
        if generated_variants:
            issues.append({"term": base_term, "generated_variants": generated_variants})

    return issues


def _find_unsupported_dialogue(source_compact: str, segments: Iterable[ScriptSegment]) -> List[str]:
    unsupported: List[str] = []
    for segment in segments or []:
        if str(getattr(segment, "type", "") or "") != "dialogue":
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        if _compact_text(text) not in source_compact:
            unsupported.append(text)
    return unsupported


def _compact_text(text: str) -> str:
    return re.sub(r"[\s，。、“”‘’'\"：:；;！？?!—…·,.]+", "", str(text or ""))
