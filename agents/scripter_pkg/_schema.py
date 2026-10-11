# -*- coding: utf-8 -*-
"""ScriptDocument 数据模型：结构化剧本 schema、校验、兼容渲染与派生产物。

设计依据（知识单元）：
  - script_generator_compatibility：生成器友好约束 + HOOK/CTA + 语速预算（150wpm，词数≈时长×2.5）
  - dialogue_coverage：信息拥有者原则 + Shot Purpose 六问
  - beat 七族（beat_family_routing.json）为 family 合法域

兼容契约（不可破坏，供 2.3 之前的旧 storyboarder / 前端消费）：
  - render_markdown 输出必须含 旧校验标记：## 概要 / ## 分场 / ### 场N / 节拍 / 对白 / 视觉锚点
  - derive_entities 输出旧 schema：characters[{name,descriptor,importance}]/scenes/props
  - derive_character_profiles / derive_audio_markers 输出 CharacterProfile/AudioMarker 契约
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.scripter_pkg._compat import AudioMarker, CharacterProfile

SCHEMA_VERSION = "2.0"

# beat 七族（与 knowledge 载入的一致性由 _run 校验；此处为兜底常量）
FALLBACK_FAMILIES = [
    "信息揭示族", "情绪爆发族", "关系状态族", "冲突动作族",
    "开场建置族", "收尾定格族", "交互细节族",
]

SHOT_PURPOSES = ["传递信息", "展示反应", "建立关系", "强调情绪", "揭示变化", "建立空间"]
BEAT_TYPES = ["dialogue", "action", "reaction", "reveal", "transition"]

# 语速预算：150 wpm ≈ 2.5 词/秒（script_generator_compatibility）
WORDS_PER_SECOND = 2.5
MIN_BEAT_DURATION_S = 2.0
MAX_BEAT_DURATION_S = 15.0

# 生成端对白上限（script_generator_compatibility 台词长度约束）：
# 视频模型原生音频 ~2 句内可靠（Vidu Q3 实测：复杂对话 >2 句口型浮漂）。
# 旁白走后期 TTS 无口型约束，不受此限。
NARRATION_SPEAKERS = {"旁白", "narrator", "NARRATOR"}
DIALOGUE_LINES_PER_BEAT_MAX = 2

# 闭合动作词典基础集（closed_action_lexicon 知识单元的机器可读投影；题材扩展走注册）
BASE_ACTIONS = [
    "站", "坐", "走", "跑", "伸手", "转身", "点头", "摇头", "拥抱", "挥手",
    "跌倒", "跃起", "后退", "鞠躬", "站起", "坐下", "回头", "抬头", "低头",
    "闭眼", "睁眼", "流泪", "微笑", "皱眉", "停", "看", "盯", "指", "握",
    "松开", "递", "接", "推", "拉", "敲门", "开门", "关门", "打电话", "喝水",
    "拿起", "放下", "擦拭", "颤抖", "深呼吸", "后退一步", "上前一步",
]


# ---------------------------------------------------------------- 校验
def _beat_issues(beat: Dict[str, Any], beat_id: str, families: List[str]) -> List[str]:
    issues: List[str] = []
    family = str(beat.get("family") or "")
    if family and families and family not in families:
        issues.append(f"{beat_id}: family『{family}』不在七族注册表")
    btype = str(beat.get("type") or "")
    if btype and btype not in BEAT_TYPES:
        issues.append(f"{beat_id}: type『{btype}』非法（合法：{'/'.join(BEAT_TYPES)}）")
    dialogue = beat.get("dialogue")
    if dialogue and not isinstance(dialogue, list):
        issues.append(f"{beat_id}: dialogue 必须是数组")
    if not str(beat.get("description") or "").strip():
        issues.append(f"{beat_id}: 缺 description（节拍内容）")
    return issues


def validate_document(doc: Dict[str, Any], families: Optional[List[str]] = None) -> List[str]:
    """Examine 用结构校验：返回问题清单（空列表=通过）。"""
    issues: List[str] = []
    fam_list = families or FALLBACK_FAMILIES
    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["剧本缺 scenes 或为空"]

    for si, scene in enumerate(scenes):
        sid = str(scene.get("scene_id") or f"S{si + 1}")
        if not isinstance(scene, dict):
            issues.append(f"{sid}: 场必须是对象")
            continue
        beats = scene.get("beats")
        if not isinstance(beats, list) or not beats:
            issues.append(f"{sid}: 场内无 beat")
            continue
        for bi, beat in enumerate(beats):
            if not isinstance(beat, dict):
                issues.append(f"{sid}-B{bi + 1}: beat 必须是对象")
                continue
            bid = str(beat.get("beat_id") or f"{sid}-B{bi + 1}")
            issues.extend(_beat_issues(beat, bid, fam_list))

    hooks = doc.get("hooks")
    if not isinstance(hooks, dict) or not str(hooks.get("opening_hook") or "").strip():
        issues.append("缺开场钩子 hooks.opening_hook（resonance_design: Click/Stop 3 秒原则）")
    if not isinstance(hooks, dict) or not str(hooks.get("ending_hook") or "").strip():
        issues.append("缺结尾钩子 hooks.ending_hook（悬念钩，对齐小说层伏笔账本）")
    return issues


# ---------------------------------------------------------------- 词典校验
def _split_action_terms(action: str) -> List[str]:
    return [t for t in re.split(r"[→/·、，,；;\s]+", action) if t.strip()]


def check_action_lexicon(doc: Dict[str, Any], extra_actions: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """闭合动作词典校验：beat.action 中的每个动作词须命中词典，否则报『词典外动作』。

    词典外动作不阻断（CCV 修正轮处理：改写为词典内动作或登记新动作）。
    """
    known = set(BASE_ACTIONS)
    for extra in extra_actions or []:
        known.add(str(extra).strip())
    violations: List[Dict[str, str]] = []
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            action = str(beat.get("action") or "").strip()
            if not action:
                continue
            terms = _split_action_terms(action)
            unknown = [t for t in terms if t not in known]
            if unknown:
                violations.append({
                    "beat_id": str(beat.get("beat_id") or ""),
                    "unknown_actions": "、".join(unknown),
                    "action": action,
                })
    return violations


# ---------------------------------------------------------------- 预算
def count_words(line: str) -> int:
    """台词词数：CJK 按字计数，拉丁按词计数（150wpm 语的『词』对中文即字）。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", line))
    latin = len(re.findall(r"[A-Za-z]+", line))
    return cjk + latin


def dialogue_budget_issues(doc: Dict[str, Any]) -> List[str]:
    """语速预算校验：对白词数与 duration_hint_s 的偏差超过 ±40% 报警。"""
    issues: List[str] = []
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            dialogue = beat.get("dialogue") or []
            if not dialogue:
                continue
            words = sum(count_words(str(d.get("line") or "")) for d in dialogue if isinstance(d, dict))
            dur = beat.get("duration_hint_s")
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                dur = 0.0
            if words <= 0 or dur <= 0:
                continue
            expected = dur * WORDS_PER_SECOND
            if expected > 0 and abs(words - expected) / expected > 0.4:
                bid = str(beat.get("beat_id") or "")
                issues.append(
                    f"{bid}: 对白 {words} 词 vs 时长预算 {expected:.0f} 词（{dur:.0f}s×2.5）偏差>40%"
                )
    return issues


def dialogue_line_limit_issues(doc: Dict[str, Any]) -> List[str]:
    """生成端台词长度约束：每 beat 角色对白 ≤2 句（超出拆 beat 或转旁白）。

    视频模型原生音频 ~2 句内可靠（Vidu Q3 实测 >2 句口型浮漂）；
    旁白走后期 TTS 轨，无口型约束，不计入。
    """
    issues: List[str] = []
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            dialogue = beat.get("dialogue") or []
            character_lines = [
                d for d in dialogue
                if isinstance(d, dict) and str(d.get("speaker") or "").strip() not in NARRATION_SPEAKERS
                and str(d.get("line") or "").strip()
            ]
            if len(character_lines) > DIALOGUE_LINES_PER_BEAT_MAX:
                bid = str(beat.get("beat_id") or "")
                issues.append(
                    f"{bid}: 角色对白 {len(character_lines)} 句 >{DIALOGUE_LINES_PER_BEAT_MAX} 句/镜"
                    "（生成端长台词口型截断风险，拆 beat 或转旁白）"
                )
    return issues


# ---------------------------------------------------------------- 溯源
def source_provenance(
    *,
    source_text: str,
    chapter_ids: Any,
    run_id: str,
) -> Dict[str, Any]:
    """adaptation_resource_protocol：唯一文本源=冻结章节，provenance 四元组登记。"""
    sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest() if source_text else ""
    ids: List[str] = []
    if isinstance(chapter_ids, (list, tuple)):
        ids = [str(x) for x in chapter_ids]
    elif chapter_ids is not None:
        ids = [str(chapter_ids)]
    return {
        "chapter_ids": ids,
        "source_sha256": sha,
        "chapter_version": f"sha256:{sha[:12]}" if sha else "",
        "provenance": [
            {
                "source_resource_id": "chapter:" + (",".join(ids) if ids else "inline"),
                "source_version": f"sha256:{sha[:12]}" if sha else "",
                "used_in": f"script:{run_id or 'unknown'}",
                "reuse_mode": "read_only_text_source",
            }
        ],
    }


# ---------------------------------------------------------------- 渲染与派生
def render_markdown(doc: Dict[str, Any]) -> str:
    """兼容渲染：旧管线（storyboarder LLM prompt / 前端展示）消费的 Markdown 视图。

    必须包含旧校验标记：## 概要 / ## 分场 / ### 场N / 节拍 / 对白 / 视觉锚点。
    """
    lines: List[str] = ["# 剧本（结构化引擎 v2）", ""]
    lines.append("## 概要")
    synopsis = str(doc.get("synopsis") or "").strip() or "- （待补全）"
    for ln in synopsis.split("\n"):
        lines.append(f"- {ln}" if not ln.startswith("-") else ln)
    hooks = doc.get("hooks") if isinstance(doc.get("hooks"), dict) else {}
    if hooks.get("opening_hook"):
        lines.append(f"- 开场钩子：{hooks.get('opening_hook')}")
    if hooks.get("ending_hook"):
        lines.append(f"- 结尾钩子：{hooks.get('ending_hook')}")
    lines.append("")

    lines.append("## 分场")
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        number = scene.get("number") or _scene_number(scene)
        interior = str(scene.get("interior") or "内景")
        location = str(scene.get("location") or "未知")
        tod = str(scene.get("time_of_day") or "日")
        lines.append(f"### 场{number} | {interior} | {location} | {tod}")
        chars = scene.get("characters") or []
        lines.append("人物：")
        if chars:
            lines.extend(f"- {c}" for c in chars)
        else:
            lines.append("- （待补全）")

        lines.append("节拍：")
        beats = scene.get("beats") or []
        if beats:
            for beat in beats:
                if not isinstance(beat, dict):
                    continue
                family = str(beat.get("family") or "未分类")
                hook_mark = "（钩子）" if beat.get("hook") else ""
                desc = str(beat.get("description") or "").strip()
                lines.append(f"- [{family}]{hook_mark} {desc}")
        else:
            lines.append("- （待补全）")

        dialogue_lines: List[str] = []
        visual_lines: List[str] = []
        action_lines: List[str] = []
        for beat in beats if isinstance(beats, list) else []:
            if not isinstance(beat, dict):
                continue
            for d in beat.get("dialogue") or []:
                if isinstance(d, dict) and str(d.get("line") or "").strip():
                    speaker = str(d.get("speaker") or "旁白")
                    dialogue_lines.append(f"- {speaker}：{d.get('line')}")
            if str(beat.get("visual_anchor") or "").strip():
                visual_lines.append(f"- {beat.get('visual_anchor')}")
            if str(beat.get("action") or "").strip():
                action_lines.append(f"- {beat.get('action')}")

        lines.append("对白：")
        lines.extend(dialogue_lines if dialogue_lines else ["- （无）"])
        if action_lines:
            lines.append("动作：")
            lines.extend(action_lines)
        lines.append("视觉锚点：")
        lines.extend(visual_lines if visual_lines else ["- （待补全）"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _scene_number(scene: Dict[str, Any]) -> int:
    try:
        return int(scene.get("number") or 0)
    except (TypeError, ValueError):
        return 0


def derive_entities(doc: Dict[str, Any], story_graph: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """派生旧 schema 的 script_entities：characters/scenes/props。"""
    graph = story_graph if isinstance(story_graph, dict) else {}
    chars: List[Dict[str, str]] = []
    seen = set()
    for c in graph.get("characters") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            chars.append({
                "name": name,
                "descriptor": str(c.get("description") or ""),
                "importance": str(c.get("importance") or "secondary"),
            })
    # 兜底：剧本场内出现但图里没有的角色
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for name in scene.get("characters") or []:
            name = str(name).strip()
            if name and name not in seen:
                seen.add(name)
                chars.append({"name": name, "descriptor": "", "importance": "secondary"})

    scenes_out: List[Dict[str, str]] = []
    seen_scenes = set()
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        loc = str(scene.get("location") or "").strip()
        if loc and loc not in seen_scenes:
            seen_scenes.add(loc)
            scenes_out.append({"name": loc, "descriptor": str(scene.get("summary") or "")})

    props: List[Dict[str, str]] = []
    seen_props = set()
    for p in graph.get("props") or []:
        if isinstance(p, dict):
            name = str(p.get("name") or "").strip()
            if name and name not in seen_props:
                seen_props.add(name)
                props.append({"name": name, "descriptor": str(p.get("descriptor") or "")})
        elif isinstance(p, str) and p.strip() and p not in seen_props:
            seen_props.add(p)
            props.append({"name": p, "descriptor": ""})

    return {"characters": chars, "scenes": scenes_out, "props": props}


def derive_character_profiles(
    doc: Dict[str, Any],
    story_graph: Optional[Dict[str, Any]] = None,
) -> List[CharacterProfile]:
    """从 Story Graph 角色节点派生 CharacterProfile（省一次 LLM 调用，图内已有描述）。"""
    graph = story_graph if isinstance(story_graph, dict) else {}
    profiles: List[CharacterProfile] = []
    seen = set()
    for c in graph.get("characters") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        importance = str(c.get("importance") or "secondary")
        if importance not in ("main", "secondary", "background"):
            importance = "secondary"
        traits = [str(t) for t in c.get("personality_traits") or [] if str(t).strip()]
        profiles.append(CharacterProfile(
            character_id=f"char_{hashlib.md5(name.encode('utf-8')).hexdigest()[:10]}",
            name=name,
            appearance_description=str(c.get("description") or ""),
            personality_traits=traits,
            voice_style=str(c.get("voice_style") or "natural"),
            importance=importance,
        ))
    return profiles


def derive_audio_markers(doc: Dict[str, Any]) -> List[AudioMarker]:
    """从 beat.dialogue 派生 AudioMarker（声画同步）：start/end 按语速预算累计估算。"""
    markers: List[AudioMarker] = []
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        scene_number = _scene_number(scene) or (len(markers) + 1)
        for beat in scene.get("beats") or []:
            if not isinstance(beat, dict):
                continue
            for d in beat.get("dialogue") or []:
                if not isinstance(d, dict):
                    continue
                line = str(d.get("line") or "").strip()
                if not line:
                    continue
                words = count_words(line)
                duration = max(1.0, words / WORDS_PER_SECOND)
                start = 0.0
                if markers:
                    prev = markers[-1]
                    start = float(prev.end_time or 0.0)
                emotion = str(d.get("emotion") or beat.get("emotion") or "neutral")
                markers.append(AudioMarker(
                    scene_number=int(scene_number),
                    character_name=str(d.get("speaker") or "旁白"),
                    dialogue_line=line,
                    start_time=round(start, 2),
                    end_time=round(start + duration, 2),
                    voice_style=str(d.get("voice_style") or "natural"),
                    emotion=emotion,
                ))
    return markers


def beat_families_used(doc: Dict[str, Any]) -> List[str]:
    used: List[str] = []
    for scene in doc.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("beats") or []:
            if isinstance(beat, dict) and beat.get("family"):
                used.append(str(beat["family"]))
    return used
