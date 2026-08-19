"""复制合同持久化服务（GUIDE §2.1，验收 25）。

切换引擎后新建另一引擎批次时，把源批次已审批剧本复制为新批次不可变快照，
并持久化来源审计字段：
- ``source_audiobook_project_id`` / ``source_chapter_audio_id``：来源批次与章节音频
- ``source_script_hash``：源 script_json 的确定性 sha256（复制后与源一致）
- ``source_script_review_version``：源审定版本
- ``source_provenance_json``：完整来源证据（batch/chapter_audio/复制时点）

复制后新批次可无阻碍执行 ``audio_from_scripts``（script_status 保持 approved），
运行期与源批次互不依赖。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudio
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


def _script_hash(script_json: Optional[str]) -> Optional[str]:
    """源 script_json 确定性 sha256（JSON 归一化后计算）。"""
    if not script_json:
        return None
    import json

    try:
        parsed = json.loads(script_json)
    except (json.JSONDecodeError, TypeError):
        parsed = script_json
    try:
        canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = str(parsed)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def copy_approved_script(
    db: Session,
    *,
    source_audiobook_project_id: int,
    source_chapter_audio_id: int,
    target_audiobook_project_id: int,
    target_chapter_id: int,
) -> Dict[str, Any]:
    """把源批次已审批剧本复制到目标批次章节音频（验收 25 复制合同）。

    幂等：目标已含指向同一来源的 provenance 时跳过（不覆盖）。
    返回 ``{"copied": bool, "reason": str, "source_script_hash": str}``。
    """
    source = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.id == source_chapter_audio_id,
            ChapterAudio.audiobook_project_id == source_audiobook_project_id,
            ChapterAudio.deleted_at.is_(None),
        )
        .first()
    )
    if source is None:
        return {"copied": False, "reason": "source_chapter_audio_not_found"}

    target = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == target_audiobook_project_id,
            ChapterAudio.chapter_id == target_chapter_id,
            ChapterAudio.deleted_at.is_(None),
        )
        .first()
    )
    if target is None:
        return {"copied": False, "reason": "target_chapter_audio_not_found"}

    # 幂等：已复制且来源一致 → 跳过
    existing_provenance = target.source_provenance_json
    if (
        isinstance(existing_provenance, dict)
        and existing_provenance.get("source_chapter_audio_id") == source_chapter_audio_id
        and existing_provenance.get("source_audiobook_project_id") == source_audiobook_project_id
    ):
        return {
            "copied": False,
            "reason": "already_copied",
            "source_script_hash": target.source_script_hash,
        }

    source_script = str(source.script_json or "").strip()
    source_hash = _script_hash(source_script)

    target.script_json = source.script_json
    target.script_review_json = source.script_review_json
    target.script_review_version = source.script_review_version
    # 复制后保持已审定状态（可无阻碍执行 audio_from_scripts）
    target.script_status = str(source.script_status or "pending").strip() or "pending"
    target.source_audiobook_project_id = int(source_audiobook_project_id)
    target.source_chapter_audio_id = int(source_chapter_audio_id)
    target.source_script_hash = source_hash
    target.source_script_review_version = source.script_review_version
    target.source_provenance_json = {
        "source_audiobook_project_id": int(source_audiobook_project_id),
        "source_chapter_audio_id": int(source_chapter_audio_id),
        "source_script_hash": source_hash,
        "source_script_review_version": source.script_review_version,
        "copied_at": utc_now().isoformat(),
        "copy_contract_version": 1,
    }
    db.flush()
    logger.info(
        "复制合同持久化: target_chapter_audio=%s <- source=%s hash=%s",
        target.id,
        source_chapter_audio_id,
        source_hash,
    )
    return {
        "copied": True,
        "reason": "copied",
        "source_script_hash": source_hash,
    }


__all__ = [
    "copy_approved_script",
]
