from __future__ import annotations

from pathlib import Path
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
            assets=[],
        )
        shots.append(shot)

    # 收集资产（按文件名反推 shot_key）
    assets_by_shot: Dict[str, List[AssetRef]] = {}

    def push_asset(shot_key: str, asset: AssetRef) -> None:
        assets_by_shot.setdefault(shot_key, []).append(asset)

    for frame in payload.get("keyframes") or []:
        if not isinstance(frame, dict):
            continue
        path = frame.get("path")
        if not isinstance(path, str):
            continue
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
                meta={"ratio": frame.get("ratio"), "spec": frame.get("spec")},
            ),
        )

    for frame in payload.get("midframes") or []:
        if not isinstance(frame, dict):
            continue
        path = frame.get("path")
        if not isinstance(path, str):
            continue
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
                meta={"ratio": frame.get("ratio"), "spec": frame.get("spec")},
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
        push_asset(
            shot_key,
            AssetRef(
                schema_version=schema_version,
                asset_type="video",
                role=role,
                uri=path,
                meta={"duration": clip.get("duration"), "head": clip.get("head"), "tail": clip.get("tail")},
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
        dw_project = DreamweaverProject(
            run_id=contract.run_id,
            source_project_id=contract.source_project_id,
            user_id=contract.user_id,
            schema_version=contract.schema_version,
        )
        session.add(dw_project)
        session.flush()
    else:
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

        for asset in shot.assets:
            _upsert_asset(
                session,
                dreamweaver_project_id=dw_project.id,
                episode_id=dw_episode.id,
                shot_id=row.id,
                asset=asset,
            )

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
