# -*- coding: utf-8 -*-
"""3E 完整性门（知识单元 10.5 stage_completeness_3e：Explore/Examine/Enhance）。

- Explore：由生成阶段承担（此处记录候选信息；质量模式可两案对照）
- Examine：结构 schema + 词典 + 预算 + 场数范围 + 钩子的代码校验
- Enhance：对可补全缺口做一次定向 LLM 补全（局部修补，不整稿重生成）

3E 不过 → 不交接：问题写入报告并置 script_requires_review=True（人工门兜底），
不静默放行，也不无限重试（成本纪律）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agents.llm_client import chat_completions, extract_json_object
from agents.scripter_pkg._schema import validate_document

_ENHANCE_SYSTEM = (
    "你是剧本引擎 3E 门的 Enhance 执行者。输入：剧本 JSON + 缺口清单。\n"
    "只做局部补全（补钩子/补 beat 描述/补 shot_purpose/补视觉锚点），"
    "不改变场数、不重写已有内容。只输出 JSON：{\"patched_document\":{...},\"patched\":[\"补了什么\"]}"
)


def _scene_count_issues(doc: Dict[str, Any], max_scenes: int, min_hint: int) -> List[str]:
    issues: List[str] = []
    scenes = doc.get("scenes") or []
    n = len(scenes) if isinstance(scenes, list) else 0
    if n == 0:
        issues.append("场数为 0")
    if max_scenes > 0 and n > max_scenes:
        issues.append(f"场数 {n} 超上限 {max_scenes}")
    if min_hint > 0 and n < min_hint:
        issues.append(f"场数 {n} 低于建议下限 {min_hint}")
    return issues


def examine(
    doc: Dict[str, Any],
    *,
    families: List[str],
    max_scenes: int,
    min_scenes_hint: int,
    extra_checks: Optional[List[str]] = None,
) -> List[str]:
    issues: List[str] = []
    issues.extend(validate_document(doc, families))
    issues.extend(_scene_count_issues(doc, max_scenes, min_scenes_hint))
    if extra_checks:
        issues.extend(extra_checks)
    return issues


def enhance(
    doc: Dict[str, Any],
    *,
    issues: List[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    warnings: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """定向补全。返回 (document, patched_notes)。"""
    warnings = warnings if warnings is not None else []
    if not issues or not (api_key and base_url):
        return doc, []

    import json
    try:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[
                {"role": "system", "content": _ENHANCE_SYSTEM},
                {"role": "user", "content": (
                    "【缺口清单】\n" + "\n".join(f"- {i}" for i in issues)
                    + "\n\n【剧本 JSON】\n" + json.dumps(doc, ensure_ascii=False)
                )},
            ],
            timeout_s=timeout_s,
            temperature=temperature,
        )
        data = extract_json_object(content)
        patched = data.get("patched_document") if isinstance(data, dict) else None
        if isinstance(patched, dict) and patched.get("scenes"):
            notes = [str(x) for x in (data.get("patched") or [])][:20]
            return patched, notes
        return doc, []
    except Exception as exc:  # noqa: BLE001 — Enhance 失败保留缺口给人工门
        warnings.append(f"3E Enhance 失败：{str(exc)[:120]}")
        return doc, []


def run_three_e(
    *,
    document: Dict[str, Any],
    families: List[str],
    max_scenes: int,
    min_scenes_hint: int,
    ccv_remaining_issues: Optional[List[str]] = None,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout_s: int = 120,
    temperature: float = 0.3,
    explore_candidates: int = 1,
    warnings: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """3E 门主入口。返回 (document, three_e_report)。"""
    warnings = warnings if warnings is not None else []

    # Examine（含 CCV 遗留问题的合并视角：遗留多为词典/预算类，Enhance 只补结构性缺口）
    issues = examine(document, families=families, max_scenes=max_scenes, min_scenes_hint=min_scenes_hint)

    report: Dict[str, Any] = {
        "protocol": "3e_stage_completeness",
        "explore": {"stage": "generation", "candidates": int(explore_candidates)},
        "examine_issues": issues[:20],
        "enhance_applied": False,
    }

    doc = document
    if issues:
        structural = [i for i in issues if ("缺" in i or "低于" in i or "无 beat" in i)]
        if structural:
            doc, notes = enhance(
                doc,
                issues=structural,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
                temperature=temperature,
                warnings=warnings,
            )
            if notes:
                report["enhance_applied"] = True
                report["enhance_notes"] = notes
        # 复验
        issues_after = examine(doc, families=families, max_scenes=max_scenes, min_scenes_hint=min_scenes_hint)
    else:
        issues_after = []

    report["remaining_issues"] = issues_after[:20] + [str(x) for x in ccv_remaining_issues or []][:10]
    report["status"] = "pass" if not report["remaining_issues"] else "handoff_blocked_to_human_gate"
    return doc, report
