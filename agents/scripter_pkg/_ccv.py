# -*- coding: utf-8 -*-
"""CCV 协作环（Critique-Correct-Verify，知识源：10.5 collaboration_protocols + FilmAgent）。

流程：代码侧先跑结构/词典/预算校验（Critique 输入）→ LLM 一次调用完成
批评+修正（返回 issues 与 revised_document）→ 代码侧复验（Verify）。
词典外动作等代码可判定的问题优先交给 LLM 归一化；仍残留则记录不阻断
（人工审核门 script_requires_review 兜底）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agents.llm_client import chat_completions, extract_json_object
from agents.scripter_pkg._schema import (
    check_action_lexicon,
    dialogue_budget_issues,
    dialogue_line_limit_issues,
    validate_document,
)

_CCV_SYSTEM = (
    "你是剧本引擎的 Critique-Correct-Verify 协作环。输入：结构化剧本 JSON + 问题清单。\n"
    "职责：①逐条修复问题清单（词典外动作改写为词典内动作链；family 归一到七族；"
    "补开场/结尾钩子；对白超预算先删词；shot_purpose 六选一；beat 描述补全）；"
    "②不改变场数与整体结构，只做定向修正；③保持 JSON 规格不变。\n"
    "只输出 JSON：{\"issues_fixed\":[\"修了什么\"],\"issues_remaining\":[\"无法修的及原因\"],"
    "\"revised_document\":{...完整修正后的剧本...}}"
)


def collect_issues(doc: Dict[str, Any], families: List[str]) -> List[str]:
    """代码侧 Critique 输入：结构 + 词典 + 语速预算 + 钩子。"""
    issues: List[str] = []
    issues.extend(validate_document(doc, families))

    for v in check_action_lexicon(doc):
        issues.append(
            f"{v['beat_id']}: 词典外动作『{v['unknown_actions']}』（原文：{v['action']}）"
            "——改写为词典内动作链或删除"
        )

    issues.extend(dialogue_budget_issues(doc))
    issues.extend(dialogue_line_limit_issues(doc))

    # beat 总量与场分布 sanity
    total_beats = 0
    for scene in doc.get("scenes") or []:
        if isinstance(scene, dict) and isinstance(scene.get("beats"), list):
            total_beats += len(scene["beats"])
    if total_beats == 0:
        issues.append("全剧本无 beat")
    return issues


def run_ccv(
    *,
    document: Dict[str, Any],
    families: List[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    max_rounds: int = 1,
    warnings: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """执行 CCV。返回 (document, ccv_report)。无 LLM 时只跑代码侧校验。"""
    warnings = warnings if warnings is not None else []
    report: Dict[str, Any] = {
        "protocol": "critique_correct_verify",
        "rounds": [],
        "llm_used": False,
        "initial_issues": 0,
        "remaining_issues": [],
    }

    doc = document
    issues = collect_issues(doc, families)
    report["initial_issues"] = len(issues)
    if not issues:
        report["status"] = "pass_on_entry"
        return doc, report

    if not (api_key and base_url):
        report["status"] = "code_only"
        report["remaining_issues"] = issues
        warnings.append("CCV 无 LLM 可用，仅代码校验（问题保留给人工审核门）")
        return doc, report

    report["llm_used"] = True
    for round_no in range(1, max(1, max_rounds) + 1):
        try:
            content = chat_completions(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=[
                    {"role": "system", "content": _CCV_SYSTEM},
                    {"role": "user", "content": (
                        "【问题清单】\n"
                        + "\n".join(f"- {i}" for i in issues)
                        + "\n\n【剧本 JSON】\n"
                        + _dump(doc)
                    )},
                ],
                timeout_s=timeout_s,
                temperature=temperature,
            )
            data = extract_json_object(content)
            if not isinstance(data, dict):
                raise ValueError("CCV 响应不是 JSON 对象")
            revised = data.get("revised_document")
            if isinstance(revised, dict) and revised.get("scenes"):
                doc = revised
            round_info = {
                "round": round_no,
                "issues_input": len(issues),
                "fixed": [str(x) for x in data.get("issues_fixed") or []][:20],
                "declared_remaining": [str(x) for x in data.get("issues_remaining") or []][:20],
            }
        except Exception as exc:  # noqa: BLE001 — CCV 失败降级为代码校验结果
            round_info = {"round": round_no, "error": str(exc)[:200]}
            warnings.append(f"CCV 第 {round_no} 轮失败：{str(exc)[:120]}")

        # Verify：代码复验
        issues = collect_issues(doc, families)
        round_info["issues_after"] = len(issues)
        report["rounds"].append(round_info)
        if not issues:
            break

    report["remaining_issues"] = issues[:20]
    report["status"] = "pass" if not issues else "issues_remain"
    return doc, report


def _dump(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
