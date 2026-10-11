# -*- coding: utf-8 -*-
"""Story Graph 摄取（知识单元 story_graph_ingestion）。

把冻结章节解析为可查询的故事图：角色-关系-时间线-场景-道具。
剧本生成走图查询而非原文全文复述（图作为生成的结构化输入）。

降级路径（无 LLM / 开关关闭）：从 payload hints 构建最小图，不阻断管线。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from agents.llm_client import chat_completions, extract_json_object

_GRAPH_SYSTEM = (
    "你是小说改编管线的故事图抽取器。从冻结章节文本中抽取可查询的故事图，"
    "只输出 JSON，不要输出任何解释文字。字段规范：\n"
    '{"characters":[{"name":"角色名","description":"外貌与身份一句话",'
    '"importance":"main|secondary|background","personality_traits":["性格词"],'
    '"relationships":[{"with":"对方角色名","relation":"关系一句话"}]}],'
    '"timeline":[{"order":1,"event":"事件一句话","characters":["涉及角色"]}],'
    '"scenes":[{"location":"地点","summary":"该地点发生什么"}],'
    '"props":[{"name":"道具名","descriptor":"一句话"}]}\n'
    "要求：角色 3-8 个（按戏份）；timeline 按原文顺序 5-15 条；"
    "relationships 只写有戏剧意义的关系；scenes 是地点去重后的清单。"
)


def _fallback_graph(source_text: str, hints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """无 LLM 时的最小图：实体 hints + 段落启发。"""
    graph: Dict[str, Any] = {"characters": [], "timeline": [], "scenes": [], "props": []}
    if isinstance(hints, dict):
        for c in hints.get("characters") or []:
            if isinstance(c, dict) and c.get("name"):
                graph["characters"].append({
                    "name": str(c["name"]),
                    "description": str(c.get("descriptor") or ""),
                    "importance": str(c.get("importance") or "secondary"),
                    "personality_traits": [],
                    "relationships": [],
                })
        for p in hints.get("props") or []:
            if isinstance(p, dict) and p.get("name"):
                graph["props"].append({"name": str(p["name"]), "descriptor": str(p.get("descriptor") or "")})
    # 时间线：按段落粗切（每段一件事）
    order = 0
    for para in re.split(r"\n+", source_text or ""):
        para = para.strip()
        if len(para) < 10:
            continue
        order += 1
        if order > 20:
            break
        graph["timeline"].append({"order": order, "event": para[:60], "characters": []})
    return graph


def extract_story_graph(
    *,
    source_text: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    hints: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """抽取故事图。返回 (graph, mode)；mode ∈ {"llm", "fallback"}。"""
    if not (api_key and base_url):
        return _fallback_graph(source_text, hints), "fallback"

    try:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[
                {"role": "system", "content": _GRAPH_SYSTEM},
                {"role": "user", "content": f"【冻结章节】\n{source_text[:20000]}"},
            ],
            timeout_s=timeout_s,
            temperature=temperature,
        )
        data = extract_json_object(content)
        if not isinstance(data, dict):
            raise ValueError("故事图响应不是 JSON 对象")
        graph = {
            "characters": [c for c in data.get("characters") or [] if isinstance(c, dict) and c.get("name")],
            "timeline": [t for t in data.get("timeline") or [] if isinstance(t, dict) and t.get("event")],
            "scenes": [s for s in data.get("scenes") or [] if isinstance(s, dict) and s.get("location")],
            "props": [p for p in data.get("props") or [] if isinstance(p, dict) and p.get("name")],
        }
        if not graph["characters"]:
            raise ValueError("故事图缺角色节点")
        return graph, "llm"
    except Exception:  # noqa: BLE001 — 图抽取失败降级，不阻断管线
        return _fallback_graph(source_text, hints), "fallback"


def graph_summary_for_prompt(graph: Dict[str, Any]) -> str:
    """图 → 生成 prompt 的紧凑视图（生成走图查询而非原文复述的落地形式）。"""
    lines: List[str] = []

    lines.append("【角色-关系】")
    for c in graph.get("characters") or []:
        rels = "；".join(
            f"{r.get('with')}({r.get('relation')})"
            for r in c.get("relationships") or []
            if isinstance(r, dict) and r.get("with")
        )
        desc = str(c.get("description") or "")
        imp = str(c.get("importance") or "secondary")
        entry = f"- {c.get('name')}[{imp}]：{desc}"
        if rels:
            entry += f"｜关系：{rels}"
        lines.append(entry)

    timeline = sorted(
        [t for t in graph.get("timeline") or [] if isinstance(t, dict)],
        key=lambda t: t.get("order") or 0,
    )
    if timeline:
        lines.append("")
        lines.append("【时间线】")
        for t in timeline:
            lines.append(f"- {t.get('event')}")

    scenes = graph.get("scenes") or []
    if scenes:
        lines.append("")
        lines.append("【场景清单】")
        for s in scenes:
            lines.append(f"- {s.get('location')}：{s.get('summary', '')}")

    props = graph.get("props") or []
    if props:
        lines.append("")
        lines.append("【关键道具】")
        lines.extend(f"- {p.get('name')}：{p.get('descriptor', '')}" for p in props)

    return "\n".join(lines)
