# -*- coding: utf-8 -*-
"""Phase 1 小说层补强（1.2 机读字段 / 1.3 修订计划补栏 / 1.4 边界门禁）。

落地为小说层的一个增强模块（纯增量，不改动现有调用链），由
backend 的 chapter 路由在评审完成后调用：
  ① build_review_payload(...)      → 响应/落库侧补机读 failure_codes JSON（1.2）
  ② build_revision_plan(...)       → 修订计划补栏：优先级公式 + 删除测试（1.3）
  ③ assert_no_director_knowledge(...) → 边界门禁：短剧 DC/CF/Contract 不得进入小说层（1.4）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
DIRECTOR_KNOWLEDGE_DIR = REPO_ROOT / "config" / "director_knowledge"

# 短剧导演知识的特征标记（出现即视为混注）
_DIRECTOR_MARKERS = re.compile(
    r"(DC-0\d{2}|CF-\d{3}|Shot Contract|shot_contract|beat_?(?:family|七族)|"
    r"信息揭示族|情绪爆发族|关系状态族|冲突动作族|开场建置族|收尾定格族|交互细节族|"
    r"shot_contracts|storyboard_generation|camera_states|R0-R6|R-pre|AM-1[567])"
)

# 优先级公式（对齐指导文档 10.3 Repair Priority：Narrative Severity × Dependency Reach × Edit Cost）
def _priority_formula(severity: str, class_name: str, hits: int) -> float:
    """Revision Priority = Severity × Recurrence × (light 加权 / heavy 直通)。"""
    sev = {"HIGH": 3.0, "MED": 2.0, "LOW": 1.0}.get(str(severity).upper(), 1.0)
    recur = 1.0 + min(hits, 3) * 0.5  # 复发加成：quality_memory 命中 1-3 次
    weight = 1.5 if str(class_name) == "heavy" else 1.0
    return round(sev * recur * weight, 2)


# ---------------------------------------------------------------- ① 机读字段（1.2）
def build_review_payload(
    *,
    review_text: str,
    chapter_number: int,
    revision_mode: str,
    quality_memory: Optional[Dict[str, Any]] = None,
    foreshadow_ledger: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """评审完成后的结构化 payload：机读 failure_codes + 路由 + 记忆摘要（1.2 补强）。

    消费方：WS 完成事件 / project_settings.review_report 落库 / 修订计划构建。
    """
    from backend.app.services.prompts.narrative_quality import extract_failure_codes

    codes = extract_failure_codes(review_text)
    return {
        "chapter_number": int(chapter_number),
        "revision_mode": str(revision_mode),
        "failure_codes": [
            {
                "code": c.get("code"),
                "severity": c.get("severity"),
                "class": c.get("class"),
                "evidence": c.get("evidence", ""),
            }
            for c in codes
        ],
        "failure_codes_count": len(codes),
        "has_heavy": any(str(c.get("class")) == "heavy" for c in codes),
        "quality_memory_top": (quality_memory or {}).get("items", [])[:3],
        "foreshadow_open_count": sum(
            1 for e in (foreshadow_ledger or {}).get("entries", [])
            if isinstance(e, dict) and e.get("status") == "open"
        ),
        "machine_readable": True,
    }


# ---------------------------------------------------------------- ② 修订计划补栏（1.3）
def build_revision_plan(
    *,
    failure_codes: List[Dict[str, Any]],
    quality_memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """修订计划：优先级公式排序 + 删除测试栏（1.3 补强）。

    迭代协调 agent（iteration_coordinator）消费本结构：
      - priority: 公式得分（Severity × Recurrence × Class-Weight），降序
      - delete_test: 无效场景走删除而非修补（对齐指导文档 1.3「删除测试两栏」）
    """
    memory_issues = [str(i.get("issue") or "") for i in (quality_memory or {}).get("items", [])[:20]]

    def _hits(evidence: str) -> int:
        return sum(1 for issue in memory_issues if issue and issue[:8] in str(evidence or ""))

    items: List[Dict[str, Any]] = []
    for c in failure_codes or []:
        evidence = str(c.get("evidence") or "")
        items.append({
            "code": c.get("code"),
            "severity": c.get("severity"),
            "class": c.get("class"),
            "evidence": evidence[:200],
            "priority": _priority_formula(c.get("severity"), c.get("class"), _hits(evidence)),
            # 删除测试栏：此问题对应的场景/段落，删除后叙事是否受损？
            # 若移除后不受损 → 删除（无效场景）；受损 → 修补（有效场景）
            "delete_test": {
                "action": "delete_if_no_damage",
                "question": f"移除『{evidence[:60]}』所涉场景/段落后，叙事链是否受损？",
                "if_damaged": "repair（局部修订或实质重写，按 class）",
                "if_intact": "delete（无效场景，直接删除该段落）",
            },
        })
    items.sort(key=lambda x: -float(x.get("priority") or 0))
    return {
        "formula": "Revision Priority = Severity(HIGH3/MED2/LOW1) × Recurrence(1+0.5×hits) × ClassWeight(heavy1.5/light1.0)",
        "items": items,
        "delete_test_rule": "删除测试不通过的元素（删除后叙事受损）才值得修补；删除后不受损的无效场景直接删除，不浪费修订轮次",
        "top_priority": items[0]["code"] if items else None,
    }


# ---------------------------------------------------------------- ③ 边界门禁（1.4）
def assert_no_director_knowledge(text: str, *, context: str = "novel_prompt") -> None:
    """边界门禁：短剧导演知识标记不得出现在小说层 prompt/评审/产物中。

    触发即抛 ValueError（fail-fast）；由 CI 测试与小说层 prompt 组装调用。
    """
    m = _DIRECTOR_MARKERS.search(str(text or ""))
    if m:
        raise ValueError(
            f"边界门禁[1.4]：小说层 {context} 检测到短剧导演知识标记『{m.group(0)}』"
            "——DC/CF/Shot Contract/七族 不得注入小说创作/修订 agent（指导文档 §1.3 混注禁令）"
        )


def scan_novel_boundary(
    *,
    prompt_text: str = "",
    extra_texts: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """扫描小说层文本的混注情况（CI 测试消费，不抛错只报告）。"""
    violations: List[Dict[str, str]] = []
    sources = {"prompt": prompt_text}
    sources.update(extra_texts or {})
    for name, text in sources.items():
        for m in _DIRECTOR_MARKERS.finditer(str(text or "")):
            violations.append({"source": name, "marker": m.group(0)})
    return {
        "clean": not violations,
        "violations": violations[:20],
        "checked_sources": list(sources.keys()),
        "rule": "短剧 DC/CF/Shot Contract/七族/AM-15+ 不得进入小说层（产物分层铁律）",
    }
