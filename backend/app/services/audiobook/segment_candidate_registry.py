"""片段候选音频资产的登记与生命周期回收。

候选文件签发时登记为 ChapterAudioRun 记录（run_type="segment_candidate"），
到期后由 temp_segment_janitor 定时任务按 checkpoint 资产清单物理回收；
同一片段的候选被新候选顶替时立即回收旧文件。

temp_asset_prefix 刻意留空：同一章节的多个候选共享前缀目录，
前缀级回收会误删其他仍有效的候选，因此回收始终按登记的资产清单
逐个删除（本地文件逐个 unlink，OSS 对象按清单 DELETE）。
"""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudioRun
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.segment_candidate_token import CANDIDATE_TOKEN_TTL_SECONDS
from app.services.audiobook.segment_synthesis_contract import (
    CANDIDATE_CONTRACT_REVISION,
    compute_compiled_segment_fingerprint,
)
from app.services.audiobook.temp_segment_janitor import (
    build_expired_checkpoint_cleanup_document,
    finalize_completed_chapter_run_temp_assets,
)
from app.services.audiobook.temp_segment_store import (
    TempSegmentStoreError,
    delete_temp_segment_prefix,
    extract_cached_segment_paths,
)
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

CANDIDATE_RUN_TYPE = "segment_candidate"


def _extract_candidate_asset_ref(run: ChapterAudioRun, *, segment_index: int) -> str:
    checkpoint_json = getattr(run, "checkpoint_json", None)
    if not isinstance(checkpoint_json, dict):
        return ""
    return str(extract_cached_segment_paths(checkpoint_json).get(segment_index) or "").strip()


def _extract_candidate_preview_type(run: ChapterAudioRun) -> str:
    checkpoint_json = getattr(run, "checkpoint_json", None)
    if not isinstance(checkpoint_json, dict):
        return "voice"
    preview_type = str(checkpoint_json.get("candidate_preview_type") or "").strip().lower()
    if not preview_type:
        contract = checkpoint_json.get("candidate_contract")
        if isinstance(contract, dict):
            preview_type = str(contract.get("preview_type") or "").strip().lower()
    # 兼容上线前没有轨道字段的候选登记；历史候选按 voice 处理。
    return preview_type if preview_type in {"voice", "sfx", "bgm", "mix"} else "voice"


def segment_candidate_contract_revision_is_current(
    candidate_contract: Any,
    *,
    candidate_payload: Any = None,
) -> bool:
    if not isinstance(candidate_contract, Mapping):
        return False
    contract_revision = str(candidate_contract.get("revision") or "").strip()
    if contract_revision != CANDIDATE_CONTRACT_REVISION:
        return False
    if candidate_payload is None:
        return True
    if not isinstance(candidate_payload, Mapping):
        return False
    return str(candidate_payload.get("rev") or "").strip() == contract_revision


def segment_candidate_contract_matches_token(
    candidate_payload: Any,
    candidate_contract: Any,
) -> bool:
    """Validate the current revision and immutable token/registry binding."""
    if not segment_candidate_contract_revision_is_current(
        candidate_contract,
        candidate_payload=candidate_payload,
    ):
        return False

    token_preview_type = str(candidate_payload.get("pt") or "").strip().lower()
    contract_preview_type = str(
        candidate_contract.get("preview_type") or ""
    ).strip().lower()
    token_base_fingerprint = str(candidate_payload.get("fp") or "").strip()
    token_effective_fingerprint = str(candidate_payload.get("efp") or "").strip()
    token_synthesis_fingerprint = str(candidate_payload.get("sfp") or "").strip()
    contract_base_fingerprint = str(
        candidate_contract.get("base_segment_fingerprint") or ""
    ).strip()
    contract_effective_fingerprint = str(
        candidate_contract.get("effective_segment_fingerprint") or ""
    ).strip()
    contract_synthesis_fingerprint = str(
        candidate_contract.get("synthesis_fingerprint") or ""
    ).strip()
    effective_segment = candidate_contract.get("effective_segment")

    return bool(
        token_preview_type
        and token_base_fingerprint
        and token_effective_fingerprint
        and token_synthesis_fingerprint
        and token_preview_type == contract_preview_type
        and token_base_fingerprint == contract_base_fingerprint
        and token_effective_fingerprint == contract_effective_fingerprint
        and token_synthesis_fingerprint == contract_synthesis_fingerprint
        and isinstance(effective_segment, dict)
        and compute_compiled_segment_fingerprint(effective_segment)
        == token_effective_fingerprint
    )


def _list_active_candidate_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> List[ChapterAudioRun]:
    return (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
            ChapterAudioRun.run_type == CANDIDATE_RUN_TYPE,
            ChapterAudioRun.resumable.is_(True),
        )
        .order_by(ChapterAudioRun.id.desc())
        .all()
    )


def _mark_candidate_run_superseded(run: ChapterAudioRun, *, now, removed_files: int) -> None:
    document = build_expired_checkpoint_cleanup_document(
        getattr(run, "checkpoint_json", None) or {},
        expired_at=now,
        removed_files=removed_files,
    )
    document["last_error"] = "candidate_superseded"
    run.checkpoint_json = document
    run.status = "expired"
    run.current_stage = "expired"
    run.resumable = False
    run.error_message = "candidate_superseded"
    run.expires_at = now
    if getattr(run, "finished_at", None) is None:
        run.finished_at = now
    logger.info(
        "♻️ 候选音频被新候选顶替，已回收: run_id=%s removed_files=%s",
        getattr(run, "id", None),
        removed_files,
    )


def register_segment_candidate_asset(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    temp_segment_cache: Dict[str, Any],
    candidate_contract: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = CANDIDATE_TOKEN_TTL_SECONDS,
) -> Optional[ChapterAudioRun]:
    """登记候选音频资产并回收同片段、同轨道被顶替的旧候选。

    登记后候选文件受 janitor 管理：token 到期即物理回收，
    不再无限堆积；被顶替的旧候选立即释放（文件内容相同时仅移交归属）。
    """
    cached_audio_paths = temp_segment_cache.get("cached_audio_paths") or {}
    asset_ref = ""
    for key in (segment_index, str(segment_index)):
        value = str(cached_audio_paths.get(key) or "").strip()
        if value:
            asset_ref = value
            break
    if not asset_ref:
        logger.warning(
            "候选资产登记跳过: cached_audio_paths 缺失 segment_index=%s", segment_index
        )
        return None

    now = utc_now()
    contract = copy.deepcopy(candidate_contract or {})
    if contract and not segment_candidate_contract_revision_is_current(contract):
        raise ValueError("candidate contract revision is missing or stale")
    preview_type = str(contract.get("preview_type") or "voice").strip().lower()
    if preview_type not in {"voice", "sfx", "bgm", "mix"}:
        preview_type = "voice"

    # Contract 收窄后 chapter_audio_id NOT NULL（§5.27）：候选 run 同样需要
    # 运行作用域，复用查/建 active ChapterAudio 的既有 helper
    from app.services.audiobook.task_support import _ensure_active_chapter_audio

    chapter_audio = _ensure_active_chapter_audio(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    for stale_run in _list_active_candidate_runs(
        db, audiobook_project_id=audiobook_project_id, chapter_id=chapter_id
    ):
        if _extract_candidate_preview_type(stale_run) != preview_type:
            continue
        stale_ref = _extract_candidate_asset_ref(stale_run, segment_index=segment_index)
        if not stale_ref:
            continue
        if stale_ref == asset_ref:
            # 内容相同的候选共享同一文件，不能删除，仅移交归属给新记录
            _mark_candidate_run_superseded(stale_run, now=now, removed_files=0)
            continue
        try:
            removed_files = int(
                max(
                    delete_temp_segment_prefix(
                        None,
                        {"cached_audio_paths": {str(segment_index): stale_ref}},
                    ),
                    0,
                )
            )
        except (OSError, TempSegmentStoreError) as exc:
            removed_files = 0
            logger.warning("回收被顶替候选音频失败: run_id=%s error=%s", stale_run.id, exc)
        _mark_candidate_run_superseded(stale_run, now=now, removed_files=removed_files)

    return ChapterAudioRunRepository.create_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=CANDIDATE_RUN_TYPE,
        # Contract 收窄后 celery_task_id NOT NULL + UNIQUE（§5.27）：候选为
        # 请求内同步生成，无真实 Celery 任务，用每 run 独立 uuid 占位
        # （与 outbox 逐 run uuid 语义一致）
        celery_task_id=str(uuid4()),
        chapter_audio_id=chapter_audio.id,
        status="completed",
        current_stage="candidate_ready",
        output_format=str(temp_segment_cache.get("output_format") or "") or None,
        resumable=True,
        checkpoint_json={
            "cached_audio_paths": {str(segment_index): asset_ref},
            "segment_candidate": True,
            "candidate_preview_type": preview_type,
            "candidate_contract": contract,
        },
        temp_asset_prefix=None,
        expires_at=now + timedelta(seconds=int(ttl_seconds)),
        started_at=now,
        finished_at=now,
    )


def load_segment_candidate_contract(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    asset_ref: str,
) -> Optional[Dict[str, Any]]:
    """Load the immutable contract registered for an active candidate asset."""
    normalized_ref = str(asset_ref or "").strip()
    if not normalized_ref:
        return None

    for run in _list_active_candidate_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    ):
        if _extract_candidate_asset_ref(run, segment_index=segment_index) != normalized_ref:
            continue
        checkpoint = getattr(run, "checkpoint_json", None)
        if not isinstance(checkpoint, dict):
            return None
        contract = checkpoint.get("candidate_contract")
        return copy.deepcopy(contract) if isinstance(contract, dict) and contract else None
    return None


def finalize_segment_candidate_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    asset_ref: str,
) -> int:
    """候选 apply 成功后结束对应登记记录（文件已由 apply 流程回收）。"""
    normalized_ref = str(asset_ref or "").strip()
    if not normalized_ref:
        return 0

    finalized = 0
    for run in _list_active_candidate_runs(
        db, audiobook_project_id=audiobook_project_id, chapter_id=chapter_id
    ):
        if _extract_candidate_asset_ref(run, segment_index=segment_index) != normalized_ref:
            continue
        finalize_completed_chapter_run_temp_assets(run)
        db.add(run)
        finalized += 1

    if finalized:
        db.commit()
    return finalized


__all__ = [
    "CANDIDATE_RUN_TYPE",
    "finalize_segment_candidate_runs",
    "load_segment_candidate_contract",
    "register_segment_candidate_asset",
    "segment_candidate_contract_matches_token",
    "segment_candidate_contract_revision_is_current",
]
