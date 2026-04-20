from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model, llm_stream_context
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_frame_ratio,
)
from pipeline.style_presets import ensure_style_payload

def _build_rule_storyboard(
    *,
    source_text: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entities: Any,
    max_segments: int,
    min_segments: int = 0,
    uses_video_containers: bool = False,
) -> List[Dict[str, Any]]:
    raw_segments = _split_into_segments(source_text, max_segments=max_segments, min_segments=min_segments)
    if not raw_segments:
        raw_segments = ["空场景：无输入文本，请补充章节内容。"]

    min_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 3.0)
    max_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 10.0)
    base_s = _env_float("DREAMWEAVER_STORYBOARD_BASE_S", 2.0)
    cps = _env_float("DREAMWEAVER_STORYBOARD_CHARS_PER_SECOND", 20.0)
    storyboard: List[Dict[str, Any]] = []

    segments: List[Dict[str, Any]] = []
    if uses_video_containers and _looks_like_script(source_text):
        container_cap = int(max(1, int(max_segments)))
        max_beats = min(240, max(12, container_cap * 6))
        min_beats = 0
        try:
            min_beats = max(0, min(int(min_segments) * 4, max_beats))
        except Exception:  # noqa: BLE001
            min_beats = 0
        beats = _split_into_segments(source_text, max_segments=max_beats, min_segments=min_beats)
        prefer_container_s = _env_float(
            "DREAMWEAVER_WAN_VIDEO_PREFERRED_CONTAINER_S",
            _env_float("DREAMWEAVER_WAN_I2V_PREFERRED_CONTAINER_S", 15.0),
        )
        packed = _pack_video_containers_from_segments(
            beats,
            entities=entities,
            max_containers=container_cap,
            prefer_container_s=prefer_container_s,
        )
        for plan in packed:
            if not isinstance(plan, dict):
                continue
            beats_list = plan.get("beats") if isinstance(plan.get("beats"), list) else []
            beats_list = [str(b).strip() for b in beats_list if isinstance(b, str) and str(b).strip()]
            merged_text = str(plan.get("merged_text") or "\n".join(beats_list)).strip()
            duration_s = float(plan.get("duration_s") or 15.0)
            subshots = plan.get("subshots") if isinstance(plan.get("subshots"), list) else []
            entity_matches = plan.get("entity_matches") if isinstance(plan.get("entity_matches"), dict) else None
            if entity_matches is None:
                entity_matches = _match_entities_in_text(merged_text, entities, max_characters=6, max_scenes=2, max_props=4)
            segments.append(
                {
                    "text": merged_text,
                    "duration_s": duration_s,
                    "subshots": subshots,
                    "beats": beats_list,
                    "entity_matches": entity_matches,
                }
            )
    else:
        for seg in raw_segments:
            segments.append({"text": str(seg), "duration_s": None, "subshots": [], "beats": [], "entity_matches": None})

    for idx, seg_obj in enumerate(segments, 1):
        seg = str(seg_obj.get("text") or "").strip()
        if not seg:
            continue
        shot_id = f"S1-{idx}"
        profile = _shot_profile(idx)
        beats_list = seg_obj.get("beats") if isinstance(seg_obj.get("beats"), list) else []
        first_beat = str(beats_list[0]).strip() if beats_list else seg
        last_beat = str(beats_list[-1]).strip() if beats_list else seg
        visual_desc = _build_visual_desc(seg)
        head_visual_desc = _build_visual_desc(first_beat)
        tail_visual_desc = _build_visual_desc(last_beat)
        dynamic = _detect_dynamic(seg)
        entity_matches = seg_obj.get("entity_matches") if isinstance(seg_obj.get("entity_matches"), dict) else None
        if entity_matches is None:
            entity_matches = _match_entities_in_text(seg, entities)
        vis_chars = [name for name, _desc in (entity_matches.get("characters") or []) if name]
        duration_override = seg_obj.get("duration_s")
        if duration_override is None:
            duration_s = _estimate_shot_duration_s(seg, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        else:
            try:
                duration_s = float(duration_override)
            except Exception:  # noqa: BLE001
                duration_s = _estimate_shot_duration_s(seg, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        
        narrative_context = _analyze_narrative_context(seg, storyboard=storyboard, shot_index=idx - 1)
        profile = _shot_profile(idx, narrative_context=narrative_context)
        
        audio_sync_info = _build_audio_sync_info(seg, shot_id, idx, duration_s)
        audio_desc = audio_sync_info.get("audio_desc", "")
        audio_markers = audio_sync_info.get("audio_markers", [])

        head_prompt = _build_frame_prompt(
            visual_desc=head_visual_desc or visual_desc,
            profile=profile,
            stage="head",
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entity_matches=entity_matches,
            dynamic=dynamic,
            narrative_context=narrative_context,
        )
        tail_prompt = _build_frame_prompt(
            visual_desc=tail_visual_desc or visual_desc,
            profile=profile,
            stage="tail",
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entity_matches=entity_matches,
            dynamic=dynamic,
            narrative_context=narrative_context,
        )
        motion_desc = _build_motion_desc(visual_desc=visual_desc, profile=profile, dynamic=dynamic)
        variation_type, variation_reason = _infer_variation_type(
            ff_desc=head_prompt,
            lf_desc=tail_prompt,
            ff_vis_char_ids=vis_chars,
            lf_vis_char_ids=vis_chars,
            state_before="",
            state_after="",
        )

        subject_x = _clamp_01(profile.get("subject_x"), default=0.5)
        subject_y = _clamp_01(profile.get("subject_y"), default=0.5)
        subshots = seg_obj.get("subshots") if isinstance(seg_obj.get("subshots"), list) else []
        storyboard.append(
            {
                "scene_id": "S1",
                "shot_id": shot_id,
                "desc": seg[:200],
                "duration_s": duration_s,
                # ShotSchemaV2 对齐字段（用于持久化与后续视频模型 prompt）
                "camera_index": idx,
                "cam_idx": idx,
                "visual_desc": visual_desc,
                "variation_type": variation_type,
                "variation_reason": variation_reason,
                "ff_desc": head_prompt,
                "lf_desc": tail_prompt,
                "motion_desc": motion_desc,
                "audio_desc": audio_desc,
                "audio_markers": audio_markers,
                "state_before": "",
                "state_after": "",
                "ff_vis_char_ids": vis_chars,
                "lf_vis_char_ids": vis_chars,
                "subshots": subshots,
                "head_frame": {
                    "prompt": head_prompt,
                    "ratio": normalize_frame_ratio(ratio),
                    "subject_pos": {"x": subject_x, "y": subject_y},
                },
                "tail_frame": {
                    "prompt": tail_prompt,
                    "ratio": normalize_frame_ratio(ratio),
                    "subject_pos": {"x": subject_x, "y": subject_y},
                },
            }
        )
    return storyboard


def _llm_storyboard(
    ctx: Any,
    *,
    source_text: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entities: Any,
    max_shots: Optional[int],
    safety_max_shots: int,
    min_shots_hint: int,
    hint_max_shots: int,
    target_total_s: Optional[float],
    uses_video_containers: bool,
    min_shot_s: float,
    max_shot_s: float,
    retry_reason: Optional[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    character_profiles: Optional[List[Dict[str, Any]]] = None,
    audio_markers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    entities_text = _entities_summary(entities)
    ratio_norm = normalize_frame_ratio(ratio)
    hard_cap = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    max_shots_line = f"- storyboard 数量 <= {hard_cap}\n"
    min_shots = max(0, int(min_shots_hint))
    min_shots_line = f"- storyboard 数量 >= {min_shots}\n" if min_shots > 0 else ""
    hint_max = max(0, int(hint_max_shots))
    hint_line = f"- 建议 storyboard 数量约 {min_shots}~{hint_max}\n" if (min_shots > 0 and hint_max > 0) else ""
    total_line = ""
    if target_total_s is not None and float(target_total_s) > 0.0:
        total_line = f"- 所有镜头 duration_s 之和约 {float(target_total_s):.1f} 秒（允许±20%）\n"
    duration_line = f"- duration_s 建议在 {float(min_shot_s):.1f}~{float(max_shot_s):.1f} 秒之间（可小数）\n"
    if uses_video_containers:
        duration_line = (
            "- duration_s 必须是 5/10/15 之一（对应 Wan2.7 单次视频生成容器时长），并且优先使用 15 秒以增强一致性。\n"
            "- 只有在以下情况才降级使用 10/5 秒：\n"
            "  - 需要引入新固定角色/新造型/新关键道具（需要先锁定外观）\n"
            "  - 明显场景/时间/光源逻辑切换（室内→室外、白天→夜晚等）\n"
            "  - 高风险大幅动作/高速运镜（更易漂移，缩短容器降低失败成本）\n"
        )

    character_profiles_text = ""
    if character_profiles and isinstance(character_profiles, list):
        character_profiles_text = "【角色档案】（用于通义万相2.6角色一致性）：\n"
        for profile in character_profiles:
            if isinstance(profile, dict):
                char_id = profile.get("character_id", "")
                name = profile.get("name", "")
                appearance = profile.get("appearance_description", "")
                personality = ", ".join(profile.get("personality_traits", []))
                voice_style = profile.get("voice_style", "natural")
                importance = profile.get("importance", "secondary")
                character_profiles_text += f"- {name}（{char_id}，{importance}）：{appearance}\n"
                if personality:
                    character_profiles_text += f"  性格：{personality}\n"
                if voice_style:
                    character_profiles_text += f"  声音风格：{voice_style}\n"
        character_profiles_text += "\n"

    audio_markers_text = ""
    if audio_markers and isinstance(audio_markers, list):
        audio_markers_text = "【音频标记】（用于通义万相2.6声画同步）：\n"
        for marker in audio_markers:
            if isinstance(marker, dict):
                marker_type = marker.get("marker_type", "")
                time_s = marker.get("time_s", 0)
                description = marker.get("description", "")
                character_name = marker.get("character_name", "")
                audio_markers_text += f"- {marker_type}（{time_s:.1f}秒）：{description}"
                if character_name:
                    audio_markers_text += f" - {character_name}"
                audio_markers_text += "\n"
        audio_markers_text += "\n"

    system = (
        "你是专业短剧/漫剧导演与分镜师，精通通义万相2.6视频生成技术。\n"
        "任务：把【剧本/章节文本】转换为可直接用于通义万相2.6生成分镜故事板。\n"
        "只输出严格 JSON（不要 Markdown/代码块/解释文字）。\n\n"
        "专业要求（针对通义万相2.6优化）：\n"
        "1. 镜头设计：根据场景内容选择合适的景别、角度和运镜方式，确保视觉表达准确\n"
        "2. 风格统一：所有镜头必须保持风格一致性，包括色彩、光影、质感、氛围\n"
        "3. 节奏控制：根据情节紧张程度调整镜头时长和运动强度\n"
        "4. 视觉连贯：确保相邻镜头之间构图、主体位置、光影的连贯性\n"
        "5. 细节丰富：描述要包含光照、氛围、质感等视觉细节\n"
        "6. 动作分解：动态场景要描述动作的起势、过程和结束\n"
        "7. 焦点明确：每个镜头都要有清晰的视觉焦点和构图意图\n"
        "8. 角色一致性：使用角色档案确保角色外观、服装、发型等在所有镜头中保持一致\n"
        "9. 多镜头叙事：合理运用不同景别和角度，增强叙事表现力\n"
        "10. 声画同步：根据音频标记设计镜头节奏和画面内容，确保声画同步"
    )

    subshots_schema_hint = ""
    multishot_requirements = ""
    if uses_video_containers:
        subshots_schema_hint = (
            '      "subshots": [\n'
            "        {\n"
            '          "start_s": 0,\n'
            '          "end_s": 3,\n'
            '          "transition": "hard_cut",\n'
            '          "shot_type": "wide_shot",\n'
            '          "camera_angle": "eye_level",\n'
            '          "camera_movement": "dolly_in",\n'
            '          "desc": "子分镜内容摘要（<=160字）",\n'
            '          "visual_desc": "画面要点（<=120字）"\n'
            "        }\n"
            "      ],\n"
        )
        multishot_requirements = (
            "- Wan2.7 多镜头叙事（单 prompt 多分镜）要求：\n"
            "  - 每个 storyboard 镜头是一个“视频容器”（duration_s=5/10/15），容器内部用 subshots 表达多个分镜。\n"
            "  - subshots 时间轴必须覆盖 [0, duration_s]，无重叠、无空洞，最后一个 end_s 必须等于 duration_s。\n"
            "  - 子分镜数量建议：5秒=2个，10秒=3个，15秒=4~6个；单个子分镜建议 2~5 秒。\n"
            "  - head_frame 必须对应第一个子分镜的开始画面；tail_frame 必须对应最后一个子分镜的结束画面。\n"
            "  - 若需要引入新固定角色/新造型/新关键道具，请新起一个 5/10 秒容器先锁定外观，再进入 15 秒连续容器。\n\n"
        )

    user = (
        "请输出如下 JSON 对象：\n"
        "{\n"
        '  "storyboard": [\n'
        "    {\n"
        '      "scene_id": "S1",\n'
        '      "shot_id": "S1-1",\n'
        '      "desc": "镜头内容摘要（<=200字）",\n'
        '      "duration_s": 3.0,\n'
        '      "cam_idx": 1,\n'
        '      "visual_desc": "画面要点（<=140字）",\n'
        '      "ff_desc": "首帧提示词（单格分镜 prompt：主体/环境/镜头构图/风格/可选动效）",\n'
        '      "lf_desc": "尾帧提示词（与首帧连续，保持主体与环境一致）",\n'
        '      "motion_desc": "运镜/动作/变化描述（用于图生视频）",\n'
        '      "audio_desc": "",\n'
        '      "ff_vis_char_ids": ["角色名1","角色名2"],\n'
        '      "lf_vis_char_ids": ["角色名1","角色名2"],\n'
        f"{subshots_schema_hint}"
        f'      "head_frame": {{"prompt":"...", "ratio":"{ratio_norm}", "subject_pos":{{"x":0.5,"y":0.5}}}},\n'
        f'      "tail_frame": {{"prompt":"...", "ratio":"{ratio_norm}", "subject_pos":{{"x":0.5,"y":0.5}}}}\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "硬性约束：\n"
        f"{max_shots_line}"
        f"{min_shots_line}"
        "- shot_id 必须唯一，按顺序递增（S1-1, S1-2 ...）\n"
        f"- head_frame/tail_frame 的 ratio 固定为 {ratio_norm}，subject_pos 的 x/y 必须在 0~1 之间\n"
        "- 首尾帧 prompt/head_frame.prompt/tail_frame.prompt 必须是“单格分镜”用的文生图提示词：\n"
        "  - 画面主体：角色/动作/表情（明确谁在做什么）\n"
        "  - 环境背景：场景/时段/氛围/光影（明确在哪里）\n"
        "  - 构图镜头：景别/角度/焦段/主体位置（可和 subject_pos 一致）\n"
        "  - 风格媒介：必须贯穿并与 style_prompt 一致\n"
        "  - 可选动效：仅在强动作镜头时使用（例如速度线/动感线/动态模糊），但不允许任何文字元素\n"
        "- 严禁生成任何文字：无对白、无拟声词、无字幕、无水印、无 logo、无边框、无拼贴、多格漫画页\n\n"
        f"{duration_line}"
        f"{hint_line}"
        f"{total_line}{multishot_requirements}"
        "- ff_vis_char_ids/lf_vis_char_ids：为首帧/尾帧可见人物名单（字符串数组），尽量从“已抽取实体-角色”中选取；没有人物则留空数组\n\n"
        f"风格预设：{style_preset}\n"
        f"风格（必须贯穿所有镜头）：{style_prompt}\n\n"
        + (f"【重试原因】上一次分镜不满足要求：{retry_reason}请显著提高拆分密度，保证总时长与镜头数达标。" + "\n\n" if retry_reason else "")
        + (f"已抽取实体（尽量在画面中体现一致性）：\n{entities_text}" + "\n\n" if entities_text else "")
        + character_profiles_text
        + audio_markers_text
        + "剧本/章节文本：\n"
        + f"{source_text[:12000]}"
    )

    user += (
        "\n\n补充输出字段（用于逻辑连续性与自动质检）：\n"
        "- state_before：本镜头开始时的关键状态（门开/关、人物站位、道具持有等），简短字符串\n"
        "- state_after：本镜头结束时的关键状态，简短字符串\n"
        "- variation_type：首尾画面变化幅度（small/medium/large）\n"
        "- variation_reason：选择该变化幅度的原因（简短说明）\n"
        "- shot_type：镜头类型（wide_shot/medium_shot/close_up/extreme_close_up等）\n"
        "- camera_angle：镜头角度（eye_level/high_angle/low_angle等）\n"
        "- camera_movement：镜头运动（static/pan/tilt/dolly/zoom等）\n"
        "- emotion：镜头情感氛围（neutral/happy/sad/tense/romantic等）\n"
        "- audio_sync：音频同步标记（用于声画同步，可选）\n"
        "- character_ids：本镜头涉及的角色ID列表（用于角色一致性，可选）\n"
        + ("- subshots：容器内子分镜数组（Wan2.7 视频场景），用于单提示词内时间戳分镜控制\n" if uses_video_containers else "")
        + '要求：state_before/state_after 尽量用"键=值；键=值"格式，长度控制在 80 字以内；若无明显变化可与上一镜头保持一致。\n'
    )

    with llm_stream_context(ctx, stage="storyboard", stream_key="storyboard") as on_chunk:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout_s=timeout_s,
            on_chunk=on_chunk,
        )
    obj = extract_json_object(content)
    items = obj.get("storyboard") if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("invalid storyboard JSON: missing storyboard list")

    normalized: List[Dict[str, Any]] = []
    limit = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    for idx, raw in enumerate(items[:limit], 1):
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or raw.get("shot_key") or f"S1-{idx}").strip() or f"S1-{idx}"
        scene_id = str(raw.get("scene_id") or "S1").strip() or "S1"
        desc = str(raw.get("desc") or raw.get("visual_desc") or "").strip()
        duration_s = raw.get("duration_s")
        try:
            duration = float(duration_s) if duration_s is not None else 3.0
        except Exception:  # noqa: BLE001
            duration = 3.0
        if duration <= 0.0:
            duration = 3.0
        cam_idx = raw.get("cam_idx") or raw.get("camera_index") or idx
        try:
            cam_idx_int = int(cam_idx)
        except Exception:  # noqa: BLE001
            cam_idx_int = idx

        visual_desc = str(raw.get("visual_desc") or desc or "").strip()[:140]
        ff_desc = str(raw.get("ff_desc") or "").strip()
        lf_desc = str(raw.get("lf_desc") or "").strip()

        head_prompt = ff_desc or visual_desc
        tail_prompt = lf_desc or (ff_desc or visual_desc)
        head = _normalize_frame_spec(raw.get("head_frame"), default_prompt=head_prompt, default_ratio=ratio_norm)
        tail = _normalize_frame_spec(raw.get("tail_frame"), default_prompt=tail_prompt, default_ratio=ratio_norm)

        motion_desc = str(raw.get("motion_desc") or "").strip()
        audio_desc = str(raw.get("audio_desc") or "").strip()
        state_before = str(raw.get("state_before") or "").replace("\n", " ").strip()
        state_after = str(raw.get("state_after") or "").replace("\n", " ").strip()
        if len(state_before) > 120:
            state_before = state_before[:120]
        if len(state_after) > 120:
            state_after = state_after[:120]

        variation_type_raw = raw.get("variation_type")
        variation_reason = str(raw.get("variation_reason") or "").replace("\n", " ").strip()
        if len(variation_reason) > 240:
            variation_reason = variation_reason[:240]

        def _norm_char_ids(value: Any) -> List[str]:
            if not isinstance(value, list):
                return []
            out: List[str] = []
            for item in value:
                if not isinstance(item, (str, int)):
                    continue
                name = str(item).strip()
                if not name or name in out:
                    continue
                out.append(name)
                if len(out) >= 8:
                    break
            return out

        ff_vis_char_ids = _norm_char_ids(raw.get("ff_vis_char_ids"))
        lf_vis_char_ids = _norm_char_ids(raw.get("lf_vis_char_ids"))

        profile = _shot_profile(cam_idx_int)
        dynamic = _detect_dynamic(" ".join([desc, visual_desc, ff_desc, lf_desc, motion_desc]))
        entity_matches = _match_entities_in_text(" ".join([desc, visual_desc]), entities)
        inferred_chars = [name for name, _d in (entity_matches.get("characters") or []) if name]
        if not ff_vis_char_ids:
            ff_vis_char_ids = inferred_chars
        if not lf_vis_char_ids:
            lf_vis_char_ids = inferred_chars

        def _need_rebuild(p: str) -> bool:
            s = str(p or "").strip()
            if not s:
                return True
            if len(s) < 20:
                return True
            if s == visual_desc.strip():
                return True
            return False

        head_p = str(head.get("prompt") or "").strip()
        tail_p = str(tail.get("prompt") or "").strip()
        if _need_rebuild(head_p):
            head_p = _build_frame_prompt(
                visual_desc=visual_desc,
                profile=profile,
                stage="head",
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio_norm,
                entity_matches=entity_matches,
                dynamic=dynamic,
            )
        else:
            head_p = _postprocess_frame_prompt(head_p, style_preset=style_preset, ratio=ratio_norm)
            if style_preset == "anime" and dynamic and "速度线" not in head_p and "动感线" not in head_p:
                head_p = f"{head_p}，漫画动效：速度线，动感线，轻微运动模糊（无文字）"
        if _need_rebuild(tail_p):
            tail_p = _build_frame_prompt(
                visual_desc=visual_desc,
                profile=profile,
                stage="tail",
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio_norm,
                entity_matches=entity_matches,
                dynamic=dynamic,
            )
        else:
            tail_p = _postprocess_frame_prompt(tail_p, style_preset=style_preset, ratio=ratio_norm)
            if style_preset == "anime" and dynamic and "速度线" not in tail_p and "动感线" not in tail_p:
                tail_p = f"{tail_p}，漫画动效：速度线，动感线，轻微运动模糊（无文字）"

        head["prompt"] = head_p
        tail["prompt"] = tail_p
        if not ff_desc:
            ff_desc = head_p
        if not lf_desc:
            lf_desc = tail_p
        if not motion_desc:
            motion_desc = _build_motion_desc(visual_desc=visual_desc, profile=profile, dynamic=dynamic)

        variation_type = _normalize_variation_type(variation_type_raw)
        inferred_type, inferred_reason = _infer_variation_type(
            ff_desc=ff_desc,
            lf_desc=lf_desc,
            ff_vis_char_ids=ff_vis_char_ids,
            lf_vis_char_ids=lf_vis_char_ids,
            state_before=state_before,
            state_after=state_after,
        )
        if not variation_type:
            variation_type = inferred_type
        if not variation_reason:
            variation_reason = inferred_reason

        shot_type = str(raw.get("shot_type") or "").strip()
        camera_angle = str(raw.get("camera_angle") or "").strip()
        camera_movement = str(raw.get("camera_movement") or "").strip()
        emotion = str(raw.get("emotion") or "").strip()
        audio_sync = str(raw.get("audio_sync") or "").strip()
        character_ids = raw.get("character_ids")
        if not isinstance(character_ids, list):
            character_ids = []
        subshots = _normalize_video_subshots(raw.get("subshots"), duration_s=duration) if uses_video_containers else []

        normalized.append(
            {
                "scene_id": scene_id,
                "shot_id": shot_id,
                "desc": desc[:200],
                "duration_s": duration,
                "cam_idx": cam_idx_int,
                "visual_desc": visual_desc,
                "variation_type": variation_type,
                "variation_reason": variation_reason,
                "ff_desc": ff_desc,
                "lf_desc": lf_desc,
                "motion_desc": motion_desc,
                "audio_desc": audio_desc,
                "state_before": state_before,
                "state_after": state_after,
                "ff_vis_char_ids": ff_vis_char_ids,
                "lf_vis_char_ids": lf_vis_char_ids,
                "subshots": subshots,
                "head_frame": head,
                "tail_frame": tail,
                "shot_type": shot_type,
                "camera_angle": camera_angle,
                "camera_movement": camera_movement,
                "emotion": emotion,
                "audio_sync": audio_sync,
                "character_ids": character_ids,
            }
        )

    if not normalized:
        raise RuntimeError("invalid storyboard JSON: empty normalized storyboard")
    return normalized


