from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.dreamweaver import (
    DreamweaverAsset,
    DreamweaverEpisode,
    DreamweaverProject,
    DreamweaverShot,
)
from app.schemas.dreamweaver_contract import (
    DREAMWEAVER_SCHEMA_VERSION,
    AssetRef,
    AutoQCFailure,
    AutoQCReport,
    AutoQCRoute,
    AutoQCScores,
    AutoQCShotReport,
    ContinuityConstraints,
    CostBudget,
    FrameAnchorConstraints,
    FrameSpec,
    Project,
    Episode,
    Shot,
    ShotConstraints,
)

try:
    from app.services.monitoring import metrics_collector

    _METRICS_ENABLED = True
except Exception:  # noqa: BLE001
    metrics_collector = None  # type: ignore[assignment]
    _METRICS_ENABLED = False


def _dreamweaver_metric_labels(contract: Project, *, status: str) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    status_lower = str(status or "").strip().lower()
    if status_lower:
        labels["status"] = status_lower

    runtime = contract.runtime_config if isinstance(contract.runtime_config, dict) else {}
    quality_mode = runtime.get("quality_mode")
    if isinstance(quality_mode, str) and quality_mode.strip():
        labels["quality_mode"] = quality_mode.strip().lower()
    smart_tuning = runtime.get("smart_tuning")
    if isinstance(smart_tuning, bool):
        labels["smart_tuning"] = "1" if smart_tuning else "0"

    image_cfg = runtime.get("image_config") if isinstance(runtime.get("image_config"), dict) else {}
    ratio = image_cfg.get("ratio")
    if isinstance(ratio, str) and ratio.strip():
        labels["ratio"] = ratio.strip()
    resolution = image_cfg.get("resolution")
    if isinstance(resolution, str) and resolution.strip():
        labels["resolution"] = resolution.strip()

    variant = runtime.get("ab_variant")
    if not (isinstance(variant, str) and variant.strip()):
        experiment = runtime.get("experiment") if isinstance(runtime.get("experiment"), dict) else {}
        variant = experiment.get("variant")
    if isinstance(variant, str) and variant.strip():
        labels["variant"] = variant.strip()

    return labels


def _emit_dreamweaver_terminal_metrics(
    *,
    contract: Project,
    status: str,
    prev_status: Optional[str],
    error_type: Optional[str],
) -> None:
    if not _METRICS_ENABLED or metrics_collector is None:
        return

    status_lower = str(status or "").strip().lower()
    prev_lower = str(prev_status or "").strip().lower()
    if status_lower not in {"completed", "failed"}:
        return
    if prev_lower == status_lower:
        return

    labels = _dreamweaver_metric_labels(contract, status=status_lower)
    metrics_collector.increment_counter("dreamweaver.run.count", labels=labels)

    runtime = contract.runtime_config if isinstance(contract.runtime_config, dict) else {}
    telemetry = runtime.get("telemetry") if isinstance(runtime.get("telemetry"), dict) else {}
    started_at = telemetry.get("run_started_at")
    finished_at = telemetry.get("run_finished_at")
    if isinstance(started_at, (int, float)) and isinstance(finished_at, (int, float)) and finished_at >= started_at:
        metrics_collector.record_histogram(
            "dreamweaver.run.duration_s",
            float(finished_at - started_at),
            labels=labels,
        )

    stages = telemetry.get("stages") if isinstance(telemetry.get("stages"), dict) else {}
    for stage_name, item in stages.items():
        if not isinstance(stage_name, str) or not stage_name.strip():
            continue
        if not isinstance(item, dict):
            continue
        total_s = item.get("total_s")
        if not isinstance(total_s, (int, float)):
            continue
        if total_s < 0:
            continue
        metrics_collector.record_histogram(
            "dreamweaver.stage.duration_s",
            float(total_s),
            labels={**labels, "stage": stage_name.strip()},
        )

    rework_count = telemetry.get("rework_count")
    if isinstance(rework_count, (int, float)) and rework_count >= 0:
        metrics_collector.record_histogram(
            "dreamweaver.run.rework_count",
            float(rework_count),
            labels=labels,
        )
    rework_by_type = telemetry.get("rework_by_type") if isinstance(telemetry.get("rework_by_type"), dict) else {}
    for reason_type, count in rework_by_type.items():
        if not isinstance(reason_type, str) or not reason_type.strip():
            continue
        if not isinstance(count, (int, float)) or count <= 0:
            continue
        metrics_collector.increment_counter(
            "dreamweaver.rework.count",
            value=float(count),
            labels={**labels, "type": reason_type.strip()},
        )

    if status_lower == "failed" and error_type:
        metrics_collector.increment_counter(
            "dreamweaver.run.error_type",
            labels={**labels, "error_type": str(error_type).strip() or "unknown"},
        )

    shot_count = len(contract.episodes[0].shots) if contract.episodes else 0
    metrics_collector.record_histogram(
        "dreamweaver.storyboard.shot_count",
        float(shot_count),
        labels=labels,
    )
    if contract.autoqc is not None:
        metrics_collector.increment_counter(
            "dreamweaver.autoqc.count",
            labels={**labels, "passed": "1" if bool(contract.autoqc.passed) else "0"},
        )
        metrics_collector.record_histogram(
            "dreamweaver.autoqc.overall_score",
            float(contract.autoqc.overall_score),
            labels=labels,
        )

    # 关键帧/中间帧命中缓存情况（仅统计 meta.cache_hit 明确的条目）
    cache_hits: Dict[str, int] = {"head": 0, "tail": 0, "mid": 0}
    cache_misses: Dict[str, int] = {"head": 0, "tail": 0, "mid": 0}
    selector_counts: Dict[str, int] = {}
    via_counts: Dict[str, int] = {}

    for ep in contract.episodes or []:
        for shot in ep.shots:
            for asset in shot.assets:
                if str(asset.asset_type) != "image":
                    continue
                role = str(asset.role or "").strip()
                frame = "head" if role == "head_frame" else "tail" if role == "tail_frame" else "mid" if role == "mid_frame" else None
                if frame is None:
                    continue
                meta = asset.meta if isinstance(asset.meta, dict) else {}
                cache_hit = meta.get("cache_hit")
                if cache_hit is True:
                    cache_hits[frame] = cache_hits.get(frame, 0) + 1
                elif cache_hit is False:
                    cache_misses[frame] = cache_misses.get(frame, 0) + 1

                selector = meta.get("selector")
                if isinstance(selector, str) and selector.strip() and len(selector.strip()) <= 32:
                    key = selector.strip()
                    selector_counts[key] = selector_counts.get(key, 0) + 1

                via = meta.get("via")
                if isinstance(via, str) and via.strip() and len(via.strip()) <= 32:
                    key = via.strip()
                    via_counts[key] = via_counts.get(key, 0) + 1

                candidate_count = meta.get("candidate_count")
                if isinstance(candidate_count, (int, float)) and candidate_count > 0:
                    metrics_collector.record_histogram(
                        "dreamweaver.image.candidate_count",
                        float(candidate_count),
                        labels={**labels, "frame": frame},
                    )

    for frame, count in cache_hits.items():
        if count > 0:
            metrics_collector.increment_counter(
                "dreamweaver.image.cache.hit",
                value=float(count),
                labels={**labels, "frame": frame},
            )
    for frame, count in cache_misses.items():
        if count > 0:
            metrics_collector.increment_counter(
                "dreamweaver.image.cache.miss",
                value=float(count),
                labels={**labels, "frame": frame},
            )
    for selector, count in selector_counts.items():
        if count > 0:
            metrics_collector.increment_counter(
                "dreamweaver.image.selector.count",
                value=float(count),
                labels={**labels, "selector": selector},
            )
    for via, count in via_counts.items():
        if count > 0:
            metrics_collector.increment_counter(
                "dreamweaver.image.via.count",
                value=float(count),
                labels={**labels, "via": via},
            )


def _parse_asset_role_from_filename(path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从 runs/{run_id}/{shot_key}_{role}.png 或 runs/{run_id}/{shot_key}.mp4 解析出 (shot_key, role)。
    """
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        if stem.endswith("_head"):
            return stem[: -len("_head")], "head_frame"
        if stem.endswith("_tail"):
            return stem[: -len("_tail")], "tail_frame"
        if stem.endswith("_mid"):
            return stem[: -len("_mid")], "mid_frame"
        return None, None

    if suffix in {".mp4", ".mov", ".mkv"}:
        # clip：文件名为 shot_key.mp4
        return stem, "video_clip"

    return None, None


_CANDIDATE_RE = re.compile(r"^(?P<shot>.+)_(?P<kind>head|tail|mid)_c(?P<idx>\d+)$")


def _parse_candidate_from_filename(path: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    从 runs/{run_id}/candidates/{shot_key}_{kind}_c{idx}.png 解析出 (shot_key, kind, idx)。
    说明：shot_key 可能包含下划线，因此用正则匹配最后的 _{kind}_c{idx}。
    """
    p = Path(path)
    if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None, None, None
    m = _CANDIDATE_RE.match(p.stem)
    if not m:
        return None, None, None
    shot_key = str(m.group("shot") or "").strip()
    kind = str(m.group("kind") or "").strip()
    raw_idx = str(m.group("idx") or "").strip()
    if not shot_key or kind not in {"head", "tail", "mid"} or not raw_idx.isdigit():
        return None, None, None
    return shot_key, kind, int(raw_idx)


def build_contract_from_payload(
    *,
    run_id: str,
    source_project_id: int,
    user_id: int,
    payload: Dict[str, Any],
    schema_version: str = DREAMWEAVER_SCHEMA_VERSION,
) -> Project:
    """
    将现有 pipeline payload（dict）转换为强类型契约模型。
    """
    storyboard = payload.get("storyboard") or []
    shots: List[Shot] = []

    autoqc_payload = payload.get("autoqc") if isinstance(payload.get("autoqc"), dict) else None
    autoqc_shots = autoqc_payload.get("shots") if isinstance(autoqc_payload, dict) else None

    def _try_build_autoqc_failure(obj: Any) -> Optional[AutoQCFailure]:
        if not isinstance(obj, dict):
            return None
        try:
            return AutoQCFailure(
                schema_version=schema_version,
                failure_type=str(obj.get("failure_type") or ""),
                severity=str(obj.get("severity") or ""),
                message=str(obj.get("message") or ""),
                shot_key=str(obj.get("shot_key")) if isinstance(obj.get("shot_key"), str) else None,
                meta=obj.get("meta") if isinstance(obj.get("meta"), dict) else {},
            )
        except Exception:  # noqa: BLE001
            return None

    def _try_build_autoqc_scores(obj: Any) -> Optional[AutoQCScores]:
        if not isinstance(obj, dict):
            return None
        try:
            return AutoQCScores(
                schema_version=schema_version,
                identity=float(obj.get("identity") or 0.0),
                structure=float(obj.get("structure") or 0.0),
                style=float(obj.get("style") or 0.0),
                overall=float(obj.get("overall") or 0.0),
                weights=obj.get("weights") if isinstance(obj.get("weights"), dict) else {},
            )
        except Exception:  # noqa: BLE001
            return None

    def _try_build_autoqc_shot_report(obj: Any) -> Optional[AutoQCShotReport]:
        if not isinstance(obj, dict):
            return None
        scores = _try_build_autoqc_scores(obj.get("scores"))
        if not scores:
            return None
        failures = [f for f in (_try_build_autoqc_failure(i) for i in (obj.get("failures") or [])) if f]
        try:
            return AutoQCShotReport(
                schema_version=schema_version,
                shot_key=str(obj.get("shot_key") or ""),
                passed=bool(obj.get("pass")),
                scores=scores,
                failures=failures,
            )
        except Exception:  # noqa: BLE001
            return None

    def _try_build_autoqc_route(obj: Any) -> Optional[AutoQCRoute]:
        if not isinstance(obj, dict):
            return None
        try:
            return AutoQCRoute(
                schema_version=schema_version,
                target_state=str(obj.get("target_state") or ""),
                action=str(obj.get("action") or ""),
                reason=str(obj.get("reason") or ""),
                failure_types=[str(i) for i in (obj.get("failure_types") or []) if isinstance(i, str)],
            )
        except Exception:  # noqa: BLE001
            return None

    autoqc_report: Optional[AutoQCReport] = None
    if isinstance(autoqc_payload, dict):
        try:
            failures = [f for f in (_try_build_autoqc_failure(i) for i in (autoqc_payload.get("failures") or [])) if f]
            route = _try_build_autoqc_route(autoqc_payload.get("route"))
            shots_map: Dict[str, AutoQCShotReport] = {}
            if isinstance(autoqc_shots, dict):
                for k, v in autoqc_shots.items():
                    sr = _try_build_autoqc_shot_report(v)
                    if sr and k:
                        shots_map[str(k)] = sr
            autoqc_report = AutoQCReport(
                schema_version=schema_version,
                passed=bool(autoqc_payload.get("pass")),
                overall_score=float(autoqc_payload.get("overall_score") or 0.0),
                shots=shots_map,
                failures=failures,
                route=route,
                config=autoqc_payload.get("config") if isinstance(autoqc_payload.get("config"), dict) else {},
            )
        except Exception:  # noqa: BLE001
            autoqc_report = None

    # 以 storyboard 为主构建 Shot
    for idx, item in enumerate(storyboard, 1):
        if not isinstance(item, dict):
            continue

        head = item.get("head_frame") or {}
        tail = item.get("tail_frame") or {}

        constraints = ShotConstraints(
            schema_version=schema_version,
            frame_anchor=FrameAnchorConstraints(schema_version=schema_version),
            continuity=ContinuityConstraints(schema_version=schema_version),
            cost_budget=CostBudget(schema_version=schema_version),
        )
        shot_key = str(item.get("shot_id") or "")
        shot_autoqc = None
        if isinstance(autoqc_shots, dict):
            shot_autoqc = _try_build_autoqc_shot_report(autoqc_shots.get(shot_key))

        shot_schema_v2 = None
        try:
            variation_type = str(item.get("variation_type") or "").strip().lower()
            if variation_type not in {"small", "medium", "large"}:
                variation_type = "medium"
            shot_schema_v2 = Shot.ShotSchemaV2(
                schema_version=schema_version,
                cam_idx=int(item.get("cam_idx") or item.get("camera_index") or 0),
                visual_desc=str(item.get("visual_desc") or item.get("desc") or ""),
                variation_type=variation_type,
                variation_reason=str(item.get("variation_reason") or ""),
                ff_desc=str(item.get("ff_desc") or head.get("prompt") or ""),
                lf_desc=str(item.get("lf_desc") or tail.get("prompt") or ""),
                motion_desc=str(item.get("motion_desc") or ""),
                audio_desc=str(item.get("audio_desc") or ""),
                state_before=str(item.get("state_before") or ""),
                state_after=str(item.get("state_after") or ""),
                ff_vis_char_ids=[str(i) for i in (item.get("ff_vis_char_ids") or []) if isinstance(i, (str, int))],
                lf_vis_char_ids=[str(i) for i in (item.get("lf_vis_char_ids") or []) if isinstance(i, (str, int))],
                meta=item.get("shot_schema_v2_meta") if isinstance(item.get("shot_schema_v2_meta"), dict) else {},
            )
        except Exception:  # noqa: BLE001
            shot_schema_v2 = None
        shot = Shot(
            schema_version=schema_version,
            shot_index=idx,
            scene_id=str(item.get("scene_id") or ""),
            shot_key=shot_key,
            desc=str(item.get("desc") or ""),
            duration_s=float(item.get("duration_s") or 3.0),
            head_frame=FrameSpec(**{**head, "schema_version": schema_version}),
            tail_frame=FrameSpec(**{**tail, "schema_version": schema_version}),
            constraints=constraints,
            autoqc=shot_autoqc,
            shot_schema_v2=shot_schema_v2,
            assets=[],
        )
        shots.append(shot)

    # 收集资产（按文件名反推 shot_key）
    assets_by_shot: Dict[str, List[AssetRef]] = {}
    seen_candidate_uris: set[str] = set()

    def push_asset(shot_key: str, asset: AssetRef) -> None:
        assets_by_shot.setdefault(shot_key, []).append(asset)

    for frame in payload.get("keyframes") or []:
        if not isinstance(frame, dict):
            continue
        path = frame.get("path")
        if not isinstance(path, str):
            continue
        frame_meta = frame.get("meta") if isinstance(frame.get("meta"), dict) else {}
        shot_key, role = _parse_asset_role_from_filename(path)
        if not shot_key or not role:
            continue
        push_asset(
            shot_key,
            AssetRef(
                schema_version=schema_version,
                asset_type="image",
                role=role,
                uri=path,
                meta={**frame_meta, "ratio": frame.get("ratio"), "spec": frame.get("spec")},
            ),
        )
        kind = "head" if role == "head_frame" else "tail" if role == "tail_frame" else None
        candidates = frame_meta.get("candidates")
        selected = frame_meta.get("selected")
        selected_idx = int(selected) if isinstance(selected, int) else None
        if kind and isinstance(candidates, list) and candidates:
            for cand_uri in candidates:
                if not isinstance(cand_uri, str) or not cand_uri.strip():
                    continue
                cand_uri = cand_uri.strip()
                if cand_uri in seen_candidate_uris:
                    continue
                cand_shot_key, cand_kind, cand_idx = _parse_candidate_from_filename(cand_uri)
                if cand_shot_key != shot_key or cand_kind != kind or cand_idx is None:
                    continue
                if not cand_uri.replace("\\", "/").startswith(f"runs/{run_id}/"):
                    continue
                seen_candidate_uris.add(cand_uri)
                push_asset(
                    shot_key,
                    AssetRef(
                        schema_version=schema_version,
                        asset_type="image",
                        role=f"{cand_kind}_candidate_{cand_idx}",
                        uri=cand_uri,
                        meta={
                            "index": cand_idx,
                            "selected": (selected_idx == cand_idx) if selected_idx is not None else False,
                            "source_role": role,
                            "selector": frame_meta.get("selector"),
                        },
                    ),
                )

    for frame in payload.get("midframes") or []:
        if not isinstance(frame, dict):
            continue
        path = frame.get("path")
        if not isinstance(path, str):
            continue
        frame_meta = frame.get("meta") if isinstance(frame.get("meta"), dict) else {}
        shot_key, role = _parse_asset_role_from_filename(path)
        if not shot_key or role != "mid_frame":
            continue
        push_asset(
            shot_key,
            AssetRef(
                schema_version=schema_version,
                asset_type="image",
                role=role,
                uri=path,
                meta={**frame_meta, "ratio": frame.get("ratio"), "spec": frame.get("spec")},
            ),
        )
        candidates = frame_meta.get("candidates")
        selected = frame_meta.get("selected")
        selected_idx = int(selected) if isinstance(selected, int) else None
        if isinstance(candidates, list) and candidates:
            for cand_uri in candidates:
                if not isinstance(cand_uri, str) or not cand_uri.strip():
                    continue
                cand_uri = cand_uri.strip()
                if cand_uri in seen_candidate_uris:
                    continue
                cand_shot_key, cand_kind, cand_idx = _parse_candidate_from_filename(cand_uri)
                if cand_shot_key != shot_key or cand_kind != "mid" or cand_idx is None:
                    continue
                if not cand_uri.replace("\\", "/").startswith(f"runs/{run_id}/"):
                    continue
                seen_candidate_uris.add(cand_uri)
                push_asset(
                    shot_key,
                    AssetRef(
                        schema_version=schema_version,
                        asset_type="image",
                        role=f"{cand_kind}_candidate_{cand_idx}",
                        uri=cand_uri,
                        meta={
                            "index": cand_idx,
                            "selected": (selected_idx == cand_idx) if selected_idx is not None else False,
                            "source_role": role,
                            "selector": frame_meta.get("selector"),
                        },
                    ),
                )

    for clip in payload.get("video_clips") or []:
        if not isinstance(clip, dict):
            continue
        path = clip.get("path")
        if not isinstance(path, str):
            continue
        shot_key, role = _parse_asset_role_from_filename(path)
        if not shot_key or role != "video_clip":
            continue
        extra_meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
        push_asset(
            shot_key,
            AssetRef(
                schema_version=schema_version,
                asset_type="video",
                role=role,
                uri=path,
                meta={
                    "duration": clip.get("duration"),
                    "head": clip.get("head"),
                    "mid": clip.get("mid"),
                    "tail": clip.get("tail"),
                    **extra_meta,
                },
            ),
        )

    merged_video = payload.get("merged_video")
    merged_asset = None
    if isinstance(merged_video, str) and merged_video:
        merged_asset = AssetRef(
            schema_version=schema_version,
            asset_type="video",
            role="merged_video",
            uri=merged_video,
            meta={},
        )

    project_assets: List[AssetRef] = []
    for asset in payload.get("project_assets") or []:
        if not isinstance(asset, dict):
            continue
        asset_type = asset.get("asset_type")
        role = asset.get("role")
        uri = asset.get("uri")
        if not isinstance(asset_type, str) or not isinstance(role, str) or not isinstance(uri, str):
            continue
        try:
            project_assets.append(
                AssetRef(
                    schema_version=schema_version,
                    asset_type=asset_type,  # type: ignore[arg-type]
                    role=role,
                    uri=uri,
                    meta=asset.get("meta") if isinstance(asset.get("meta"), dict) else {},
                )
            )
        except Exception:  # noqa: BLE001
            continue

    runtime_config: Dict[str, Any] = {}
    if isinstance(payload.get("quality_mode"), str) and str(payload.get("quality_mode") or "").strip():
        runtime_config["quality_mode"] = str(payload.get("quality_mode")).strip()
    if isinstance(payload.get("smart_tuning"), bool):
        runtime_config["smart_tuning"] = payload.get("smart_tuning")
    if isinstance(payload.get("smart_tuning_snapshot"), dict):
        runtime_config["smart_tuning_snapshot"] = payload.get("smart_tuning_snapshot")
    if isinstance(payload.get("chapter_ids"), list):
        runtime_config["chapter_ids"] = payload.get("chapter_ids")
    if isinstance(payload.get("style_preset"), str) and payload.get("style_preset").strip():
        runtime_config["style_preset"] = payload.get("style_preset").strip()
    if isinstance(payload.get("style_prompt"), str) and payload.get("style_prompt").strip():
        runtime_config["style_prompt"] = payload.get("style_prompt").strip()
    if isinstance(payload.get("image_config"), dict):
        runtime_config["image_config"] = payload["image_config"]
    if isinstance(payload.get("qc_config"), dict):
        runtime_config["qc_config"] = payload["qc_config"]
    if isinstance(payload.get("video_config"), dict):
        runtime_config["video_config"] = payload["video_config"]
    if isinstance(payload.get("video_clip_jobs"), list):
        runtime_config["video_clip_jobs"] = payload.get("video_clip_jobs")
    if isinstance(payload.get("asset_library_config"), dict):
        runtime_config["asset_library_config"] = payload["asset_library_config"]
    if isinstance(payload.get("plan"), dict):
        runtime_config["plan"] = payload.get("plan")
    if isinstance(payload.get("script_text"), str) and payload.get("script_text").strip():
        runtime_config["script_text"] = payload.get("script_text")
    if isinstance(payload.get("script_entities"), dict):
        runtime_config["script_entities"] = payload.get("script_entities")
    if isinstance(payload.get("script_generation"), dict):
        runtime_config["script_generation"] = payload.get("script_generation")
    if isinstance(payload.get("script_review"), dict):
        runtime_config["script_review"] = payload.get("script_review")
    if isinstance(payload.get("script_requires_review"), bool):
        runtime_config["script_requires_review"] = payload.get("script_requires_review")
    if isinstance(payload.get("storyboard_generation"), dict):
        runtime_config["storyboard_generation"] = payload.get("storyboard_generation")
    if isinstance(payload.get("camera_tree_generation"), dict):
        runtime_config["camera_tree_generation"] = payload.get("camera_tree_generation")
    if isinstance(payload.get("camera_tree"), list):
        runtime_config["camera_tree"] = payload.get("camera_tree")
    if isinstance(payload.get("camera_states"), list):
        runtime_config["camera_states"] = payload.get("camera_states")
    if isinstance(payload.get("camera_scenes"), list):
        runtime_config["camera_scenes"] = payload.get("camera_scenes")
    if isinstance(payload.get("telemetry"), dict):
        runtime_config["telemetry"] = payload.get("telemetry")
    if isinstance(payload.get("experiment"), dict):
        runtime_config["experiment"] = payload.get("experiment")
    if isinstance(payload.get("ab_variant"), str) and payload.get("ab_variant").strip():
        runtime_config["ab_variant"] = payload.get("ab_variant").strip()

    # 绑定资产到 Shot
    shot_by_key = {s.shot_key: s for s in shots}
    for shot_key, assets in assets_by_shot.items():
        if shot_key in shot_by_key:
            shot_by_key[shot_key].assets.extend(assets)

    ep = Episode(schema_version=schema_version, episode_index=1, title="Episode 1", shots=shots)
    proj = Project(
        schema_version=schema_version,
        run_id=run_id,
        source_project_id=source_project_id,
        user_id=user_id,
        episodes=[ep],
        assets=project_assets,
        runtime_config=runtime_config,
        autoqc=autoqc_report,
    )
    if merged_asset:
        # 项目级资产放在 Episode 0 的 shot assets 中并不合适，先挂到 Project 的 episodes[0] 的第一个 shot 的 assets meta 中。
        # 持久化层会单独写 project-level DreamweaverAsset。
        proj.anchor_sets_ref = {"merged_video": merged_asset.model_dump()}
    return proj


def persist_contract(
    session: Session,
    *,
    contract: Project,
    status: str,
    state: Optional[str],
    stage: Optional[str],
    progress: int,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """
    Upsert DreamweaverProject/Episode/Shot/Asset。
    返回 DreamweaverProject.id。
    """
    dw_project = (
        session.query(DreamweaverProject).filter(DreamweaverProject.run_id == contract.run_id).first()
    )
    if not dw_project:
        prev_status = None
        dw_project = DreamweaverProject(
            run_id=contract.run_id,
            source_project_id=contract.source_project_id,
            user_id=contract.user_id,
            schema_version=contract.schema_version,
        )
        session.add(dw_project)
        session.flush()
    else:
        prev_status = str(dw_project.status or "").strip()
        dw_project.schema_version = contract.schema_version

    dw_project.status = status
    dw_project.state = state
    dw_project.stage = stage
    dw_project.progress = int(progress)
    dw_project.error_type = error_type
    dw_project.error_message = error_message
    dw_project.contract_json = contract.model_dump(mode="json")

    # 目前 MVP：每个 run 固定 1 个 Episode
    ep = contract.episodes[0]
    dw_episode = (
        session.query(DreamweaverEpisode)
        .filter(
            DreamweaverEpisode.dreamweaver_project_id == dw_project.id,
            DreamweaverEpisode.episode_index == ep.episode_index,
        )
        .first()
    )
    if not dw_episode:
        dw_episode = DreamweaverEpisode(
            dreamweaver_project_id=dw_project.id,
            episode_index=ep.episode_index,
            title=ep.title,
            schema_version=ep.schema_version,
        )
        session.add(dw_episode)
        session.flush()
    else:
        dw_episode.title = ep.title
        dw_episode.schema_version = ep.schema_version

    # Shots + Assets
    shot_rows: Dict[str, DreamweaverShot] = {}
    desired_assets_by_shot_id: Dict[int, set[tuple[str, str]]] = {}
    for shot in ep.shots:
        row = (
            session.query(DreamweaverShot)
            .filter(DreamweaverShot.episode_id == dw_episode.id, DreamweaverShot.shot_key == shot.shot_key)
            .first()
        )
        if not row:
            row = DreamweaverShot(
                episode_id=dw_episode.id,
                shot_index=shot.shot_index,
                scene_id=shot.scene_id,
                shot_key=shot.shot_key,
                schema_version=shot.schema_version,
            )
            session.add(row)
            session.flush()
        else:
            row.schema_version = shot.schema_version
        row.shot_index = shot.shot_index
        row.scene_id = shot.scene_id
        row.description = shot.desc
        row.duration_s = shot.duration_s
        row.head_frame_json = shot.head_frame.model_dump(mode="json")
        row.tail_frame_json = shot.tail_frame.model_dump(mode="json")
        row.constraints_json = shot.constraints.model_dump(mode="json")
        shot_rows[shot.shot_key] = row

        desired: set[tuple[str, str]] = set()
        for asset in shot.assets:
            desired.add((str(asset.asset_type), str(asset.role)))
            _upsert_asset(
                session,
                dreamweaver_project_id=dw_project.id,
                episode_id=dw_episode.id,
                shot_id=row.id,
                asset=asset,
            )
        desired_assets_by_shot_id[int(row.id)] = desired

    # project-level merged video（从 anchor_sets_ref 中取）
    if contract.anchor_sets_ref and isinstance(contract.anchor_sets_ref, dict):
        merged = contract.anchor_sets_ref.get("merged_video")
        if isinstance(merged, dict) and isinstance(merged.get("uri"), str):
            merged_asset = AssetRef(**merged)
            _upsert_asset(
                session,
                dreamweaver_project_id=dw_project.id,
                episode_id=dw_episode.id,
                shot_id=None,
                asset=merged_asset,
            )

    for asset in contract.assets:
        _upsert_asset(
            session,
            dreamweaver_project_id=dw_project.id,
            episode_id=dw_episode.id,
            shot_id=None,
            asset=asset,
        )

    # Prune orphan shots/assets (覆盖式重跑时，确保 DB 与最新契约一致)
    keep_shot_keys = set(shot_rows.keys())
    existing_shots = session.query(DreamweaverShot).filter(DreamweaverShot.episode_id == dw_episode.id).all()
    orphan_shot_ids: List[int] = [
        int(s.id) for s in existing_shots if str(getattr(s, "shot_key", "") or "") not in keep_shot_keys
    ]
    if orphan_shot_ids:
        session.query(DreamweaverAsset).filter(
            DreamweaverAsset.dreamweaver_project_id == dw_project.id,
            DreamweaverAsset.episode_id == dw_episode.id,
            DreamweaverAsset.shot_id.in_(orphan_shot_ids),
        ).delete(synchronize_session=False)
        session.query(DreamweaverShot).filter(DreamweaverShot.id.in_(orphan_shot_ids)).delete(synchronize_session=False)

    for shot in shot_rows.values():
        desired = desired_assets_by_shot_id.get(int(shot.id), set())
        rows = session.query(DreamweaverAsset).filter(
            DreamweaverAsset.dreamweaver_project_id == dw_project.id,
            DreamweaverAsset.episode_id == dw_episode.id,
            DreamweaverAsset.shot_id == shot.id,
        )
        for asset_row in rows.all():
            key = (str(getattr(asset_row, "asset_type", "") or ""), str(getattr(asset_row, "role", "") or ""))
            if key not in desired:
                session.delete(asset_row)

    # project-level merged_video：当最新契约不再包含时，清理旧记录（文件仍是 overwrite 模式，由后续阶段覆盖）
    has_merged = bool(
        isinstance(contract.anchor_sets_ref, dict)
        and isinstance(contract.anchor_sets_ref.get("merged_video"), dict)
        and isinstance(contract.anchor_sets_ref.get("merged_video", {}).get("uri"), str)
        and str(contract.anchor_sets_ref.get("merged_video", {}).get("uri") or "").strip()
    )
    if not has_merged:
        session.query(DreamweaverAsset).filter(
            DreamweaverAsset.dreamweaver_project_id == dw_project.id,
            DreamweaverAsset.episode_id == dw_episode.id,
            DreamweaverAsset.shot_id.is_(None),
            DreamweaverAsset.role == "merged_video",
        ).delete(synchronize_session=False)

    try:
        _emit_dreamweaver_terminal_metrics(
            contract=contract,
            status=status,
            prev_status=prev_status,
            error_type=error_type,
        )
    except Exception:  # noqa: BLE001
        pass

    session.commit()
    return int(dw_project.id)


def _upsert_asset(
    session: Session,
    *,
    dreamweaver_project_id: int,
    episode_id: int,
    shot_id: Optional[int],
    asset: AssetRef,
) -> None:
    row = (
        session.query(DreamweaverAsset)
        .filter(
            DreamweaverAsset.dreamweaver_project_id == dreamweaver_project_id,
            DreamweaverAsset.episode_id == episode_id,
            DreamweaverAsset.shot_id == shot_id,
            DreamweaverAsset.asset_type == asset.asset_type,
            DreamweaverAsset.role == asset.role,
        )
        .first()
    )
    if not row:
        row = DreamweaverAsset(
            dreamweaver_project_id=dreamweaver_project_id,
            episode_id=episode_id,
            shot_id=shot_id,
            asset_type=asset.asset_type,
            role=asset.role,
            uri=asset.uri,
            schema_version=asset.schema_version,
            meta_json=asset.meta,
        )
        session.add(row)
        session.flush()
    else:
        row.uri = asset.uri
        row.meta_json = asset.meta
        row.schema_version = asset.schema_version
