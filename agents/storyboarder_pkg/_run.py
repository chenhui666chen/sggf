from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import env_flag, pick_model, resolve_llm_runtime_config
from agents.storyboarder_pkg._contract import (
    SHOT_SIZE_LEVEL,
    SHOT_SIZE_POS,
    build_shot_contracts,
)
from agents.storyboarder_pkg._entities import _match_entities_in_text
from agents.storyboarder_pkg._env_helpers import (
    _auto_storyboard_targets,
    _env_float,
    _env_int,
)
from agents.storyboarder_pkg._frame_prompt import build_frame_prompt
from agents.storyboarder_pkg._knowledge import load_storyboard_knowledge
from agents.storyboarder_pkg._precheck import precheck_contracts
from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
from agents.storyboarder_pkg._prompts import _build_visual_desc, _split_into_segments
from agents.storyboarder_pkg._variation import _infer_variation_type
from agents.storyboarder_pkg._video_subshots import _ensure_video_subshots_for_storyboard
from agents.storyboarder_pkg._audio_sync import _build_audio_sync_info
from agents.storyboarder_pkg._duration import (
    _auto_max_shots_from_script,
    _rebalance_storyboard_total_duration,
    _storyboard_safety_max_shots,
    _sum_storyboard_duration_s,
)
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    dreamweaver_beat_duration_bounds_s,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
)
from pipeline.style_presets import ensure_style_payload


def _fallback_document_from_script_text(script_text: str, max_scenes: int) -> Dict[str, Any]:
    """兼容路径：无 script_document（旧剧本/人工改稿）时按 ### 场N 切分转伪 beat。"""
    segments = _split_into_segments(script_text, max_segments=max_scenes) if script_text else []
    scenes: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments or ["（空剧本）"], start=1):
        beats = []
        lines = [ln.strip("-• \t") for ln in (seg or "").split("\n") if ln.strip()]
        desc_lines = [ln for ln in lines if ln][:6]
        for bi, ln in enumerate(desc_lines, start=1):
            speaker, line = _parse_dialogue_line(ln)
            beats.append({
                "beat_id": f"S{i}-B{bi}",
                "family": "",
                "type": "dialogue" if speaker else "action",
                "description": ln[:80],
                "action": "",
                "shot_purpose": "传递信息",
                "dialogue": [{"speaker": speaker, "line": line, "emotion": "neutral"}] if speaker else [],
                "visual_anchor": "",
                "hook": bi == 1 and i == 1,
                "duration_hint_s": 0.0,
            })
        scenes.append({
            "scene_id": f"S{i}", "number": i, "title": f"场{i}",
            "interior": "内景", "location": "", "time_of_day": "日",
            "characters": [], "summary": "", "beats": beats,
        })
    return {"schema_version": "2.0", "scenes": scenes, "hooks": {}}


def _parse_dialogue_line(line: str) -> Tuple[str, str]:
    m = re.match(r"^([^：:]{1,12})[：:](.+)$", line)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", line


def _contracts_to_storyboard(
    *,
    contracts: List[Dict[str, Any]],
    script_document: Dict[str, Any],
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entities: Any,
    character_profiles: Any,
) -> List[Dict[str, Any]]:
    """Contract → ShotSchemaV2 兼容 storyboard item（下游 painter/dreamweaver/autoqc/persistence 消费）。"""
    scenes_by_id = {
        str(s.get("scene_id")): s for s in script_document.get("scenes", []) if isinstance(s, dict)
    }
    # 角色 name → character_id（ff_vis_char_ids 用）
    char_id_by_name: Dict[str, str] = {}
    if isinstance(character_profiles, list):
        for p in character_profiles:
            if isinstance(p, dict) and p.get("name"):
                char_id_by_name[str(p["name"])] = str(p.get("character_id") or "")

    storyboard: List[Dict[str, Any]] = []
    for idx, c in enumerate(contracts):
        scene = scenes_by_id.get(c.get("scene_id"), {})
        scene_meta = {
            "location": scene.get("location"), "time_of_day": scene.get("time_of_day"),
            "interior": scene.get("interior"),
        }
        entity_matches = _match_entities_in_text(
            " ".join([str(c.get("visual_anchor") or ""), str(c.get("action") or ""),
                      " ".join(str(ch) for ch in c.get("characters") or [])]),
            entities,
        )
        vis_chars = [char_id_by_name[n] for n in c.get("characters", []) if n in char_id_by_name]
        if not vis_chars:
            vis_chars = [n for n in c.get("characters", [])]

        visual_desc = _build_visual_desc(str(c.get("visual_anchor") or c.get("action") or "")) or "（待补全画面）"
        ff_desc = build_frame_prompt(
            contract=c, stage="head", style_preset=style_preset, style_prompt=style_prompt,
            ratio=ratio, entity_matches=entity_matches, scene_meta=scene_meta,
        )
        lf_desc = build_frame_prompt(
            contract=c, stage="tail", style_preset=style_preset, style_prompt=style_prompt,
            ratio=ratio, entity_matches=entity_matches, scene_meta=scene_meta,
        )

        # 对白 beat → 音画同步（复用 _audio_sync）
        audio_info = {"has_audio": False, "audio_markers": [], "audio_desc": ""}
        if c.get("dialogue"):
            first = c["dialogue"][0] if isinstance(c["dialogue"][0], dict) else {}
            audio_info = _build_audio_sync_info(
                f"{first.get('speaker', '')}：{first.get('line', '')}",
                shot_id=c["shot_id"],
                shot_index=idx,
                duration_s=float(c.get("duration_s") or 0),
            )

        pos = SHOT_SIZE_POS.get(c.get("shot_size", "MS"), (0.5, 0.6))
        cam_idx = SHOT_SIZE_LEVEL.get(c.get("shot_size", "MS"), 1)

        variation_type, variation_reason = _infer_variation_type(
            ff_desc=ff_desc, lf_desc=lf_desc,
            ff_vis_char_ids=vis_chars, lf_vis_char_ids=vis_chars,
            state_before=str(c.get("state_before") or ""),
            state_after=str(c.get("state_after") or ""),
        )

        item = {
            "scene_id": c.get("scene_id"),
            "shot_id": c["shot_id"],
            "desc": str(c.get("visual_anchor") or "")[:200] or "（待补全）",
            "duration_s": float(c.get("duration_s") or 0),
            "camera_index": cam_idx,
            "cam_idx": cam_idx,
            "visual_desc": visual_desc,
            "variation_type": variation_type,
            "variation_reason": variation_reason or f"contract:{c['shot_id']} beat:{c.get('beat_id')}",
            "ff_desc": ff_desc,
            "lf_desc": lf_desc,
            "motion_desc": str(c.get("movement_model_lang") or c.get("camera_movement") or ""),
            "audio_desc": audio_info.get("audio_desc") or "",
            "audio_markers": audio_info.get("audio_markers") or [],
            "state_before": str(c.get("state_before") or "")[:120],
            "state_after": str(c.get("state_after") or "")[:120],
            "ff_vis_char_ids": vis_chars[:8],
            "lf_vis_char_ids": vis_chars[:8],
            "subshots": [],
            "head_frame": {"prompt": ff_desc, "ratio": ratio or "16:9",
                           "subject_pos": {"x": pos[0], "y": pos[1]}},
            "tail_frame": {"prompt": lf_desc, "ratio": ratio or "16:9",
                           "subject_pos": {"x": pos[0], "y": pos[1]}},
            # meta（ShotSchemaV2 透传，dreamweaver/persistence 消费）
            "shot_type": c.get("shot_size_zh"),
            "camera_angle": c.get("camera_angle"),
            "camera_movement": c.get("camera_movement"),
            "emotion": c.get("emotion"),
            "audio_sync": bool(c.get("dialogue")),
            "character_ids": vis_chars[:8],
            "beat_id": c.get("beat_id"),
            "family": c.get("family"),
            "r_pre_eligible": c.get("r_pre_eligible"),
            "keyframe_source": c.get("keyframe_source"),
            # 四轨声音决策（O4：dialogue/ambience/narration/bgm × native/post）
            "sound_track": c.get("sound_track"),
            "lip_sync_sensitive": bool(c.get("lip_sync_sensitive")),
        }
        storyboard.append(item)
    return storyboard


def _smooth_subject_pos(storyboard: List[Dict[str, Any]], max_delta: float) -> None:
    """跨镜 subject_pos 平滑（autoqc cross_shot_continuity_break 预防）。"""
    prev: Optional[Dict[str, float]] = None
    for item in storyboard:
        for key in ("head_frame", "tail_frame"):
            frame = item.get(key)
            if not isinstance(frame, dict) or not isinstance(frame.get("subject_pos"), dict):
                continue
            pos = frame["subject_pos"]
            try:
                x = float(pos.get("x", 0.5))
                y = float(pos.get("y", 0.5))
            except (TypeError, ValueError):
                continue
            if prev is not None:
                x = max(prev["x"] - max_delta, min(prev["x"] + max_delta, x))
                y = max(prev["y"] - max_delta, min(prev["y"] + max_delta, y))
            pos["x"] = round(x, 3)
            pos["y"] = round(y, 3)
            prev = {"x": x, "y": y}


def run(ctx: Any) -> None:
    """Shot Contract 引擎主入口（状态机 STORYBOARD 阶段调用）。"""
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)
    payload = ctx.payload

    style_preset = str(payload.get("style_preset") or "")
    style_prompt = str(payload.get("style_prompt") or "")
    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    ratio = str(image_cfg.get("ratio") or "")
    quality_mode = str(payload.get("quality_mode") or "").strip().lower()
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    video_engine = normalize_dreamweaver_video_engine(
        video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or ""
    )
    uses_i2v = is_dreamweaver_i2v_engine(video_engine)
    uses_t2v = is_dreamweaver_t2v_engine(video_engine)
    uses_auto = is_dreamweaver_auto_engine(video_engine)
    uses_video_containers = bool(uses_i2v or uses_t2v or uses_auto)
    engine_label = (
        DREAMWEAVER_AUTO_ENGINE if uses_auto
        else (DREAMWEAVER_I2V_ENGINE if uses_i2v else (DREAMWEAVER_T2V_ENGINE if uses_t2v else "slideshow"))
    )

    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag(
        "DREAMWEAVER_STORYBOARD_REQUIRE_LLM", default=False
    )
    model = pick_model(
        primary_env="DREAMWEAVER_STORYBOARD_MODEL",
        fallback_env="DREAMWEAVER_SCRIPT_MODEL",
        default="qwen-plus",
    )
    llm_runtime = resolve_llm_runtime_config(model)
    api_key = llm_runtime.api_key
    base_url = llm_runtime.base_url
    if require_llm and not (api_key and base_url):
        raise RuntimeError(
            f"storyboard require LLM but {llm_runtime.api_key_env}/{llm_runtime.base_url_env} missing"
        )
    timeout_s = int(os.getenv("DREAMWEAVER_STORYBOARD_TIMEOUT", "180") or "180")

    # ---- 输入：script_document（2.2 产物）优先，兼容 script_text ----
    script_document = payload.get("script_document") if isinstance(payload.get("script_document"), dict) else None
    script_text = str(payload.get("script_text") or payload.get("source_text") or "")
    input_mode = "script_document"
    if not script_document or not script_document.get("scenes"):
        max_scenes_for_fallback = max(2, _env_int("DREAMWEAVER_SCRIPT_MAX_SCENES", 8))
        script_document = _fallback_document_from_script_text(script_text, max_scenes_for_fallback)
        input_mode = "script_text_fallback"

    # ---- 知识与预算 ----
    knowledge = load_storyboard_knowledge()
    quality = quality_mode == "quality"
    max_shots_raw = _env_int("DREAMWEAVER_STORYBOARD_MAX_SHOTS", 0)
    safety_max_shots = _storyboard_safety_max_shots(quality_mode=quality_mode)

    if uses_video_containers:
        # 容器模式的镜头区间等于引擎档案区间（官方 [2,30]，env 只能在里面收窄）：
        # 剧本阶段的 beat 区间已经由同一个派生函数给定，分镜再写死 5~15 就是第二个
        # 事实源，会把剧本合法规划的 20 秒 beat 静默压回 15 秒。
        min_shot_s, max_shot_s = dreamweaver_beat_duration_bounds_s()
    else:
        # 幻灯片（ffmpeg）模式不受视频引擎区间约束，保留保守档。
        min_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 3.0)
        max_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 10.0)
        if max_shot_s < min_shot_s:
            max_shot_s = min_shot_s

    if input_mode == "script_document":
        # Contract 引擎：beat 数即镜数计划（导演计划优先），时长由 Contract 知识逻辑给定
        # （对白预算/呼吸等待/clamp），不做文本字数反推——仅受安全上限与显式 MAX_SHOTS 约束。
        shot_cap = min(max_shots_raw, int(safety_max_shots)) if max_shots_raw > 0 else int(safety_max_shots)
        max_shots_mode = "beats_driven" if max_shots_raw <= 0 else "fixed"
        targets = {"enabled": False, "basis": "script_document_beats"}
    else:
        # 降级路径（script_text）：沿用旧文本字数启发式
        if max_shots_raw > 0:
            shot_cap = max_shots_raw
        else:
            auto_cap = _auto_max_shots_from_script(script_text=script_text, quality_mode=quality_mode)
            shot_cap = int(auto_cap) if isinstance(auto_cap, int) and auto_cap > 0 else int(safety_max_shots)
        max_shots_mode = "fixed" if max_shots_raw > 0 else "auto"
        targets = _auto_storyboard_targets(
            source_text=script_text,
            quality_mode=quality_mode,
            uses_video_containers=uses_video_containers,
            engine_label=engine_label,
            min_shot_s=float(min_shot_s),
            max_shot_s=float(max_shot_s),
            shot_cap=shot_cap,
        )
    shot_cap = min(shot_cap, int(safety_max_shots))

    # ---- 阶段 1：Contract 生成（确定性，知识编译） ----
    contracts, contract_report = build_shot_contracts(
        script_document=script_document,
        knowledge=knowledge,
        min_shot_s=float(min_shot_s),
        max_shot_s=float(max_shot_s),
    )
    # 镜数预算：超 cap 截断（保留场完整性优先：按场截断尾部 beat）
    if len(contracts) > shot_cap:
        contracts = contracts[:shot_cap]
        contract_report["truncated_to_cap"] = shot_cap
        contract_report["total_contracts"] = len(contracts)

    # ---- 阶段 2：T3 预检 + 自动修复 ----
    if env_flag("DREAMWEAVER_CONTRACT_T3", default=True):
        contracts, precheck_report = precheck_contracts(contracts)
    else:
        precheck_report = {"suite": "t3_precheck", "status": "disabled"}

    # ---- 阶段 2.5：四轨声音决策（O4：dialogue/ambience/narration/bgm × native/post） ----
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    sound_engine = str(
        video_cfg.get("provider_model") or video_cfg.get("engine") or ""
    ).strip()
    sound_track_report = annotate_sound_tracks(
        contracts,
        engine=sound_engine,
        voice_refs=payload.get("voice_reference_audio"),
    )

    # ---- 阶段 3：兼容 storyboard item 生成 ----
    storyboard = _contracts_to_storyboard(
        contracts=contracts,
        script_document=script_document,
        style_preset=style_preset,
        style_prompt=style_prompt,
        ratio=ratio,
        entities=payload.get("script_entities"),
        character_profiles=payload.get("character_profiles"),
    )

    # ---- 阶段 4：时长后处理（保留机制：容器归一 + 总时长 rebalance + subshots） ----
    rebalance: Dict[str, Any] = {"enabled": False}
    if uses_video_containers:
        for item in storyboard:
            item["duration_s"] = normalize_dreamweaver_video_duration_s(
                item.get("duration_s"), default=float(min_shot_s)
            )
        _ensure_video_subshots_for_storyboard(storyboard)
    rebalance = _rebalance_storyboard_total_duration(
        storyboard,
        target_total_s=targets.get("target_total_s") if targets.get("enabled") else None,
        min_s=float(min_shot_s),
        max_s=float(max_shot_s),
        uses_video_containers=uses_video_containers,
        engine_label=engine_label,
        tolerance=0.15,
    )
    # 回写 contract 时长（rebalance 后一致性）
    for c, item in zip(contracts, storyboard):
        c["duration_s"] = item.get("duration_s", c.get("duration_s"))

    # ---- 阶段 5：subject_pos 平滑 + camera_tree/camera_states（保留） ----
    qc_cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}
    try:
        max_pos_delta = float(qc_cfg.get("max_subject_pos_delta") or 0.1)
    except (TypeError, ValueError):
        max_pos_delta = 0.1
    _smooth_subject_pos(storyboard, max_delta=max_pos_delta)
    payload["storyboard_subject_pos"] = {"mode": "smooth", "max_delta": max_pos_delta}

    camera_tree_mode = str(os.getenv("DREAMWEAVER_CAMERA_TREE_MODE", "heuristic") or "heuristic").strip().lower()
    camera_tree = build_camera_tree(storyboard)
    camera_tree_generation: Dict[str, Any] = {"mode": "heuristic", "model": None, "error": None}
    if camera_tree_mode == "llm" and api_key and base_url:
        try:
            llm_tree = build_camera_tree_llm(
                storyboard,
                ctx=ctx,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=min(120, timeout_s),
                max_shots_per_camera=int(os.getenv("DREAMWEAVER_CAMERA_TREE_LLM_MAX_SHOTS_PER_CAMERA", "6") or "6"),
            )
            if llm_tree:
                camera_tree = llm_tree
                camera_tree_generation = {"mode": "llm", "model": model, "error": None}
        except Exception as exc:  # noqa: BLE001
            camera_tree_generation = {"mode": "heuristic_fallback", "model": model, "error": str(exc)}
    if camera_tree:
        payload["camera_tree"] = camera_tree
        payload["camera_tree_generation"] = camera_tree_generation

    camera_states = build_camera_states(storyboard, camera_tree if camera_tree else None)
    if camera_states:
        payload["camera_states"] = camera_states

    # ---- payload 写回 ----
    payload["shot_contracts"] = contracts
    payload["storyboard"] = storyboard
    payload["storyboard_generation"] = {
        "engine": "director_os_contract_v2",
        "mode": "deterministic_knowledge_compiled",
        "input_mode": input_mode,
        "model": model if camera_tree_generation.get("mode") == "llm" else None,
        "llm_error": None,
        "llm_warnings": [],
        "max_shots": shot_cap,
        "max_shots_mode": "fixed" if max_shots_raw > 0 else "auto",
        "safety_max_shots": safety_max_shots,
        "targets": targets,
        "duration_rebalance": rebalance,
        "contract_report": contract_report,
        "precheck": {
            "issues_total": precheck_report.get("issues_total"),
            "auto_fixed": precheck_report.get("auto_fixed"),
            "issue_types": precheck_report.get("issue_types"),
        },
        "total_duration_s": round(_sum_storyboard_duration_s(storyboard) or 0.0, 1),
    }
    payload["sound_track_report"] = sound_track_report
