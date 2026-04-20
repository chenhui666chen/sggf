"""
恢复相关函数
"""
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.project import Chapter
from app.services.chapter_adaptation_assets import build_drama_source_text
from pipeline.restart_reset import apply_restart_reset as _apply_restart_reset_impl


def _build_source_text(session: Session, *, project_id: int, chapter_ids: List[int]) -> str:
    if not chapter_ids:
        return ""
    chapters = (
        session.query(Chapter)
        .filter(Chapter.project_id == project_id)
        .filter(Chapter.id.in_(chapter_ids))
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    return build_drama_source_text(chapters)


def _resume_payload_from_contract(
    contract: Dict[str, Any],
    *,
    project_id: int,
    schema_version: str,
    fallback_chapter_ids: List[int],
    fallback_source_text: str,
) -> Dict[str, Any]:
    episodes = contract.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise RuntimeError("resume contract missing episodes")

    shots = episodes[0].get("shots") if isinstance(episodes[0], dict) else []
    if not isinstance(shots, list):
        shots = []

    storyboard: List[Dict[str, Any]] = []
    keyframes: List[Dict[str, Any]] = []
    midframes: List[Dict[str, Any]] = []
    video_clips: List[Dict[str, Any]] = []

    for idx, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            continue
        shot_key = str(shot.get("shot_key") or "")
        if not shot_key:
            continue
        head_frame = shot.get("head_frame") if isinstance(shot.get("head_frame"), dict) else {}
        tail_frame = shot.get("tail_frame") if isinstance(shot.get("tail_frame"), dict) else {}
        schema_v2 = shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else {}
        schema_meta = schema_v2.get("meta") if isinstance(schema_v2.get("meta"), dict) else {}
        storyboard_item = {
            "scene_id": str(shot.get("scene_id") or ""),
            "shot_id": shot_key,
            "desc": str(shot.get("desc") or ""),
            "duration_s": float(shot.get("duration_s") or 3.0),
            "cam_idx": int(schema_v2.get("cam_idx") or idx),
            "visual_desc": str(schema_v2.get("visual_desc") or ""),
            "ff_desc": str(schema_v2.get("ff_desc") or ""),
            "lf_desc": str(schema_v2.get("lf_desc") or ""),
            "motion_desc": str(schema_v2.get("motion_desc") or ""),
            "audio_desc": str(schema_v2.get("audio_desc") or ""),
            "state_before": str(schema_v2.get("state_before") or ""),
            "state_after": str(schema_v2.get("state_after") or ""),
            "ff_vis_char_ids": [str(i) for i in (schema_v2.get("ff_vis_char_ids") or []) if isinstance(i, (str, int))],
            "lf_vis_char_ids": [str(i) for i in (schema_v2.get("lf_vis_char_ids") or []) if isinstance(i, (str, int))],
            "head_frame": head_frame,
            "tail_frame": tail_frame,
            "shot_schema_v2_meta": schema_meta,
        }

        def _apply_schema_field(key: str, target_key: Optional[str] = None) -> None:
            value = schema_v2.get(key)
            if (value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)) and isinstance(schema_meta, dict):
                value = schema_meta.get(key)
            if value is None:
                return
            if isinstance(value, str) and not value.strip():
                return
            if isinstance(value, (list, dict)) and not value:
                return
            storyboard_item[target_key or key] = value

        for field in (
            "shot_type",
            "camera_angle",
            "camera_movement",
            "composition_notes",
            "composition",
            "location",
            "time",
            "atmosphere",
            "audio_sync",
            "character_ids",
            "subshots",
            "motion_level",
            "emotion",
            "variation_type",
            "variation_reason",
            "video_prompt_override",
            "video_prompt_generated",
        ):
            _apply_schema_field(field)

        storyboard.append(storyboard_item)

        assets = shot.get("assets") if isinstance(shot.get("assets"), list) else []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            role = str(asset.get("role") or "")
            uri = asset.get("uri")
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            if not isinstance(uri, str) or not uri:
                continue

            if role in {"head_frame", "tail_frame"}:
                keyframes.append(
                    {
                        "path": uri,
                        "ratio": meta.get("ratio") or (head_frame.get("ratio") if role == "head_frame" else tail_frame.get("ratio")),
                        "spec": meta.get("spec"),
                        "meta": meta,
                    }
                )
            elif role == "mid_frame":
                midframes.append({"path": uri, "ratio": meta.get("ratio"), "spec": meta.get("spec"), "meta": meta})
            elif role == "video_clip":
                video_clips.append(
                    {
                        "path": uri,
                        "duration": meta.get("duration"),
                        "head": meta.get("head"),
                        "tail": meta.get("tail"),
                        "mid": meta.get("mid"),
                        "meta": meta,
                    }
                )

    merged_video: str | None = None
    anchor_sets_ref = contract.get("anchor_sets_ref")
    if isinstance(anchor_sets_ref, dict):
        merged = anchor_sets_ref.get("merged_video")
        if isinstance(merged, dict) and isinstance(merged.get("uri"), str) and merged.get("uri"):
            merged_video = str(merged["uri"])

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    plan = runtime_cfg.get("plan") if isinstance(runtime_cfg, dict) and isinstance(runtime_cfg.get("plan"), dict) else None
    plan_text = runtime_cfg.get("plan_text") if isinstance(runtime_cfg, dict) and isinstance(runtime_cfg.get("plan_text"), str) else ""

    payload: Dict[str, Any] = {
        "project_id": project_id,
        "chapter_ids": fallback_chapter_ids,
        "source_text": fallback_source_text,
        "schema_version": schema_version,
        "plan": plan or {"text": plan_text.strip() or "resume"},
        "storyboard": storyboard,
        "keyframes": keyframes,
        "midframes": midframes,
        "video_clips": video_clips,
    }
    if merged_video:
        payload["merged_video"] = merged_video

    if isinstance(runtime_cfg, dict):
        payload.update(
            {
                k: v
                for k, v in runtime_cfg.items()
                if k
                in {
                    "plan",
                    "quality_mode",
                    "smart_tuning",
                    "smart_tuning_snapshot",
                    "chapter_ids",
                    "style_preset",
                    "style_prompt",
                    "image_config",
                    "qc_config",
                    "video_config",
                    "video_clip_jobs",
                    "asset_library_config",
                    "asset_library_spec",
                    "asset_library_review",
                    "asset_library_scope",
                    "script_text",
                    "script_entities",
                    "script_generation",
                    "script_review",
                    "script_requires_review",
                    "prompt_review_required",
                    "prompt_review",
                    "storyboard_generation",
                    "camera_tree_generation",
                    "camera_tree",
                    "camera_states",
                    "camera_scenes",
                }
            }
        )

    return payload


def _apply_restart_reset(payload: Dict[str, Any], *, start_state: str, reset_policy: str) -> None:
    _apply_restart_reset_impl(payload, start_state=start_state, reset_policy=reset_policy)
