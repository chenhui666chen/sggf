# -*- coding: utf-8 -*-
"""结构化剧本生成：prompt 组装（知识注入）+ LLM 调用 + 解析重试。

Prompt 注入的知识（设计时编译，运行时不做全库检索——需求拉动原则）：
  - script_generator_compatibility：生成器友好约束 / HOOK-CTA / 语速预算
  - beat 七族（注册表+关键词）与 dialogue_coverage 信息拥有者原则
  - resonance_design：Click→Watch→Share 三层钩子
  - closed_action_lexicon：动作词典（生成期约束 + 生成后 CCV 校验）
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agents.llm_client import chat_completions, extract_json_object
from agents.scripter_pkg._schema import (
    BEAT_TYPES,
    SHOT_PURPOSES,
    WORDS_PER_SECOND,
)
from pipeline.media_presets import dreamweaver_beat_duration_bounds_s

_DOCUMENT_JSON_SPEC = """{
  "schema_version": "2.0",
  "title": "剧名",
  "logline": "一句话故事",
  "synopsis": "2-4 行概要",
  "hooks": {"opening_hook": "开场 3 秒钩子（视觉异常/情绪悬念/信息缺口）",
            "ending_hook": "结尾悬念钩", "share_emotion": "可转发的情绪表达"},
  "scenes": [
    {"scene_id": "S1", "number": 1, "title": "场标题", "interior": "内景|外景",
     "location": "地点", "time_of_day": "日|夜|黄昏",
     "characters": ["角色名"], "summary": "本场一句话",
     "beats": [
       {"beat_id": "S1-B1", "family": "七族之一", "type": "dialogue|action|reaction|reveal|transition",
        "description": "这个节拍发生什么（一句话）",
        "action": "词典内动作链，如：伸手→停在触碰前→收回（无动作的对话节拍留空）",
        "shot_purpose": "六问之一：传递信息|展示反应|建立关系|强调情绪|揭示变化|建立空间",
        "dialogue": [{"speaker": "角色名", "line": "台词", "emotion": "neutral|happy|sad|angry|fearful|surprised|tense|calm|excited"}],
        "visual_anchor": "本节拍视觉锚点（一个具体画面细节）",
        "hook": false, "duration_hint_s": 6.0}
     ]}
  ]
}"""


def build_system_prompt(knowledge: Dict[str, Any]) -> str:
    families = knowledge.get("beat_families") or []
    family_block = "\n".join(
        f"- {f['family']}（关键词：{'、'.join(f['keywords'][:6])}）" for f in families
    ) or "- （七族注册表缺失，按内容判断）"

    rules = knowledge.get("compat_rules") or []
    compat_block = "\n".join(f"- {r}" for r in rules)
    dialogue_block = "\n".join(f"- {r}" for r in knowledge.get("dialogue_coverage_rules") or [])
    resonance_block = "\n".join(f"- {r}" for r in knowledge.get("resonance_rules") or [])
    lexicon_line = next(
        (l for l in knowledge.get("action_lexicon_lines") or [] if "基础动作词典" in l),
        "基础动作词典：站/坐/走/跑/伸手/转身/点头/摇头/拥抱/挥手/跌倒/跃起/后退/鞠躬",
    )
    beat_low_s, beat_high_s = dreamweaver_beat_duration_bounds_s()
    beat_duration_window = f"{beat_low_s:g}-{beat_high_s:g}s"

    return (
        "你是 AI 短剧管线的剧本引擎（AI Director OS）。把冻结章节改编为结构化短剧剧本 JSON。\n"
        "剧本是生成器的输入规格而非文学文本。只输出 JSON，不输出任何解释。\n\n"
        "【改编纪律】\n"
        f"{compat_block}\n\n"
        "【beat 七族注册表】（beat.family 必须取自此表；无法归类留空由后续 L3 兜底）\n"
        f"{family_block}\n\n"
        "【对白覆盖：信息拥有者原则】\n"
        f"{dialogue_block}\n"
        f"每个 beat 必须给 shot_purpose（六选一：{'、'.join(SHOT_PURPOSES)}）。\n\n"
        "【共鸣设计：三层钩子】\n"
        f"{resonance_block}\n\n"
        "【闭合动作词典】\n"
        f"{lexicon_line}\n"
        "beat.action 只用词典内动作词（用→连接因果链）；词典外动作会被校验打回。\n\n"
        "【语速预算】150wpm：台词词数 ≈ duration_hint_s × "
        f"{WORDS_PER_SECOND:.1f}；时长不足先删词再加秒；beat 时长 {beat_duration_window}。\n\n"
        "【输出 JSON 规格】\n"
        f"{_DOCUMENT_JSON_SPEC}"
    )


def build_user_prompt(
    *,
    source_text: str,
    graph_view: str,
    style_prompt: str,
    max_scenes: int,
    min_scenes_hint: int,
    quality_mode: bool,
) -> str:
    parts: List[str] = []
    if style_prompt.strip():
        parts.append(f"【风格要求】\n{style_prompt.strip()}\n")
    parts.append(f"【场景预算】建议 {min_scenes_hint}-{max_scenes} 场（每场 3-6 个 beat）。\n")
    if quality_mode:
        parts.append("【质量模式】对白与节拍质量优先，允许更多场与更完整的情绪递进。\n")
    parts.append("【故事图（结构化输入，改编以此为准）】\n" + graph_view + "\n")
    parts.append("【冻结章节（唯一文本源，只读）】\n" + source_text[:20000])
    return "\n".join(parts)


def generate_script_document(
    *,
    source_text: str,
    graph_view: str,
    knowledge: Dict[str, Any],
    style_prompt: str,
    max_scenes: int,
    min_scenes_hint: int,
    quality_mode: bool,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    retries: int = 1,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """生成 ScriptDocument JSON（含重试）。失败抛异常（由 _run 决定降级或中断）。"""
    warnings = warnings if warnings is not None else []
    system = build_system_prompt(knowledge)
    user = build_user_prompt(
        source_text=source_text,
        graph_view=graph_view,
        style_prompt=style_prompt,
        max_scenes=max_scenes,
        min_scenes_hint=min_scenes_hint,
        quality_mode=quality_mode,
    )

    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            content = chat_completions(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout_s=timeout_s,
                temperature=temperature,
            )
            doc = extract_json_object(content)
            if not isinstance(doc, dict) or not doc.get("scenes"):
                raise ValueError("剧本响应缺 scenes")
            scenes = doc.get("scenes")
            if isinstance(scenes, list) and scenes and max_scenes > 0 and len(scenes) > max_scenes:
                warnings.append(f"场数 {len(scenes)} 超预算 {max_scenes}，截断")
                doc["scenes"] = scenes[:max_scenes]
            return doc
        except Exception as exc:  # noqa: BLE001 — 重试后仍失败则上抛
            last_error = exc
    raise RuntimeError(f"剧本生成失败（{retries} 次尝试）：{last_error}")


def json_compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
