import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook import segment_candidate_registry, temp_segment_janitor
from app.services.audiobook.segment_candidate_registry import (
    CANDIDATE_RUN_TYPE,
    finalize_segment_candidate_runs,
    register_segment_candidate_asset,
)


def _current_candidate_revision():
    from app.services.audiobook import segment_synthesis_contract

    return getattr(segment_synthesis_contract, "CANDIDATE_CONTRACT_REVISION", "2:missing")


def build_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            Chapter.__table__,
            AudiobookProject.__table__,
            ChapterAudio.__table__,
            ChapterAudioRun.__table__,
        ],
    )
    return session_factory


def seed_context(db):
    user = User(
        username="candidate_registry_user",
        email="candidate_registry@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Candidate Registry Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="content",
    )
    db.add(chapter)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="processing",
        total_chapters=1,
    )
    db.add(audiobook_project)
    db.flush()

    chapter_audio = ChapterAudio(
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter.id,
    )
    db.add(chapter_audio)
    db.commit()

    return {
        "audiobook_project": audiobook_project,
        "chapter": chapter,
        "chapter_audio": chapter_audio,
    }


def test_register_candidate_creates_reclaimable_run_record():
    session_factory = build_session_factory()
    with session_factory() as db:
        context = seed_context(db)
        run = register_segment_candidate_asset(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=3,
            temp_segment_cache={
                "cached_audio_paths": {3: "backend/data/tmp/audiobook_runs/run_x/chapter_00001/segment_00003_ab.mp3"},
                "output_format": "mp3",
            },
            ttl_seconds=3600,
        )

        assert run is not None
        assert run.run_type == CANDIDATE_RUN_TYPE
        assert run.resumable is True
        # temp_asset_prefix 必须留空：同章节候选共享前缀目录，前缀级回收会误删其他候选
        assert run.temp_asset_prefix is None
        assert run.checkpoint_json["cached_audio_paths"]["3"].endswith(".mp3")
        assert run.expires_at is not None
        assert run.started_at is not None
        assert run.expires_at - run.started_at == timedelta(seconds=3600)


def test_register_candidate_satisfies_contract_not_null_constraints(monkeypatch):
    """Contract 收窄后 celery_task_id NOT NULL+UNIQUE、chapter_audio_id NOT NULL：
    同步候选登记路径必须携带每 run 独立 celery_task_id 与运行作用域（§5.27/§5.34）。

    monkeypatch 说明：真实 helper 走全局 Table 对象查询，套件内其他测试的
    残留内存库会污染结果；此处用会话内直查等价替换，契约断言不受影响。
    """
    from app.models.audiobook import ChapterAudio as _ChapterAudio

    def _resolve_active(db, *, audiobook_project_id, chapter_id):
        return (
            db.query(_ChapterAudio)
            .filter(
                _ChapterAudio.audiobook_project_id == audiobook_project_id,
                _ChapterAudio.chapter_id == chapter_id,
                _ChapterAudio.deleted_at.is_(None),
            )
            .first()
        )

    import app.services.audiobook.task_support as _task_support

    monkeypatch.setattr(
        _task_support, "_ensure_active_chapter_audio", _resolve_active
    )

    session_factory = build_session_factory()
    with session_factory() as db:
        context = seed_context(db)
        first = register_segment_candidate_asset(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=1,
            temp_segment_cache={
                "cached_audio_paths": {1: "backend/data/tmp/audiobook_runs/run_a/chapter_00001/segment_00001_ab.mp3"},
            },
        )
        second = register_segment_candidate_asset(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=2,
            temp_segment_cache={
                "cached_audio_paths": {2: "backend/data/tmp/audiobook_runs/run_a/chapter_00001/segment_00002_ab.mp3"},
            },
        )

        assert first is not None and second is not None
        assert first.celery_task_id
        assert second.celery_task_id
        # UNIQUE 约束要求每 run 独立，不能共用占位值
        assert first.celery_task_id != second.celery_task_id
        assert first.chapter_audio_id == context["chapter_audio"].id
        assert second.chapter_audio_id == context["chapter_audio"].id


def test_register_candidate_persists_and_loads_immutable_candidate_contract():
    session_factory = build_session_factory()
    load_segment_candidate_contract = getattr(
        segment_candidate_registry, "load_segment_candidate_contract", None
    )
    assert callable(load_segment_candidate_contract)
    contract = {
        "revision": _current_candidate_revision(),
        "base_segment_fingerprint": "base-fp",
        "effective_segment": {
            "type": "narration",
            "text": "generated text",
            "voice_params": {"speaker": "voice-b"},
        },
        "effective_segment_fingerprint": "effective-fp",
        "synthesis_fingerprint": "synthesis-fp",
        "preview_type": "voice",
    }
    asset_ref = "tmp/immutable-candidate.mp3"

    with session_factory() as db:
        context = seed_context(db)
        register_segment_candidate_asset(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
            temp_segment_cache={"cached_audio_paths": {0: asset_ref}},
            candidate_contract=contract,
        )

        loaded = load_segment_candidate_contract(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
            asset_ref=asset_ref,
        )

        assert loaded == contract
        loaded["effective_segment"]["text"] = "mutated by caller"
        loaded_again = load_segment_candidate_contract(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
            asset_ref=asset_ref,
        )
        assert loaded_again["effective_segment"]["text"] == "generated text"


def test_register_candidate_rejects_missing_or_stale_contract_revision():
    session_factory = build_session_factory()
    with session_factory() as db:
        context = seed_context(db)
        common = dict(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/stale-candidate.mp3"}},
        )

        with pytest.raises(ValueError, match="revision"):
            register_segment_candidate_asset(
                db,
                candidate_contract={
                    "preview_type": "voice",
                    "revision": "1:4",
                },
                **common,
            )

        with pytest.raises(ValueError, match="revision"):
            register_segment_candidate_asset(
                db,
                candidate_contract={"preview_type": "voice"},
                **common,
            )


def test_register_candidate_supersedes_stale_candidate_and_reclaims_file(monkeypatch):
    session_factory = build_session_factory()
    removed = []
    monkeypatch.setattr(
        segment_candidate_registry,
        "delete_temp_segment_prefix",
        lambda prefix, checkpoint_json=None: removed.append(checkpoint_json) or 1,
    )

    with session_factory() as db:
        context = seed_context(db)
        kwargs = dict(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/old-candidate.mp3"}},
            **kwargs,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/new-candidate.mp3"}},
            **kwargs,
        )

        runs = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.run_type == CANDIDATE_RUN_TYPE)
            .order_by(ChapterAudioRun.id.asc())
            .all()
        )
        assert len(runs) == 2
        old_run, new_run = runs
        # 旧候选被顶替：不可再被 janitor 处理，且文件按清单回收
        assert old_run.resumable is False
        assert old_run.status == "expired"
        assert old_run.error_message == "candidate_superseded"
        assert removed == [{"cached_audio_paths": {"0": "tmp/old-candidate.mp3"}}]
        assert new_run.resumable is True


def test_register_candidate_with_identical_content_keeps_shared_file(monkeypatch):
    session_factory = build_session_factory()
    removed = []
    monkeypatch.setattr(
        segment_candidate_registry,
        "delete_temp_segment_prefix",
        lambda prefix, checkpoint_json=None: removed.append(checkpoint_json) or 1,
    )

    with session_factory() as db:
        context = seed_context(db)
        kwargs = dict(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/shared-candidate.mp3"}},
            **kwargs,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/shared-candidate.mp3"}},
            **kwargs,
        )

        # 内容相同共享同一文件：旧记录仅移交归属，不得删除文件
        assert removed == []
        runs = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.run_type == CANDIDATE_RUN_TYPE)
            .order_by(ChapterAudioRun.id.asc())
            .all()
        )
        assert [run.resumable for run in runs] == [False, True]


def test_register_candidate_supersedes_only_the_same_preview_track(monkeypatch):
    session_factory = build_session_factory()
    removed = []
    monkeypatch.setattr(
        segment_candidate_registry,
        "delete_temp_segment_prefix",
        lambda prefix, checkpoint_json=None: removed.append(checkpoint_json) or 1,
    )

    with session_factory() as db:
        context = seed_context(db)
        common = dict(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/voice-old.mp3"}},
            candidate_contract={
                "preview_type": "voice",
                "revision": _current_candidate_revision(),
            },
            **common,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/sfx-current.mp3"}},
            candidate_contract={
                "preview_type": "sfx",
                "revision": _current_candidate_revision(),
            },
            **common,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/voice-new.mp3"}},
            candidate_contract={
                "preview_type": "voice",
                "revision": _current_candidate_revision(),
            },
            **common,
        )

        runs = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.run_type == CANDIDATE_RUN_TYPE)
            .order_by(ChapterAudioRun.id.asc())
            .all()
        )
        assert [run.resumable for run in runs] == [False, True, True]
        assert removed == [{"cached_audio_paths": {"0": "tmp/voice-old.mp3"}}]
        assert runs[1].checkpoint_json["candidate_preview_type"] == "sfx"
        assert runs[2].checkpoint_json["candidate_preview_type"] == "voice"


def test_expired_candidate_run_is_physically_reclaimed_by_janitor(monkeypatch, tmp_path):
    from app.services.audiobook import temp_segment_store

    # 把临时存储根重定向到 tmp_path，验证到期后文件被真实删除
    local_root = tmp_path / "backend" / "data" / "tmp" / "audiobook_runs"
    monkeypatch.setattr(temp_segment_store, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(temp_segment_store, "_LOCAL_TEMP_ROOT_ABS", local_root)

    candidate_dir = local_root / "run_x" / "chapter_00001"
    candidate_dir.mkdir(parents=True)
    candidate_file = candidate_dir / "segment_00000_ab12cd34ef56.mp3"
    candidate_file.write_bytes(b"ID3 expired candidate audio")
    candidate_ref = "backend/data/tmp/audiobook_runs/run_x/chapter_00001/segment_00000_ab12cd34ef56.mp3"

    session_factory = build_session_factory()
    with session_factory() as db:
        context = seed_context(db)
        run = register_segment_candidate_asset(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
            temp_segment_cache={"cached_audio_paths": {0: candidate_ref}},
            ttl_seconds=1,
        )
        # 强制过期，模拟 token TTL 到期
        run.expires_at = run.expires_at - timedelta(seconds=10)
        db.commit()

        summary = temp_segment_janitor.cleanup_expired_temp_segments_in_session(db, limit=10)

        assert summary["processed_runs"] == 1
        assert summary["removed_temp_files"] == 1
        # 候选文件必须被物理回收（按登记清单删除，不依赖前缀目录）
        assert not candidate_file.exists()
        db.refresh(run)
        assert run.status == "expired"
        assert run.resumable is False


def test_finalize_candidate_run_marks_record_completed():
    session_factory = build_session_factory()
    with session_factory() as db:
        context = seed_context(db)
        kwargs = dict(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            segment_index=0,
        )
        register_segment_candidate_asset(
            db,
            temp_segment_cache={"cached_audio_paths": {0: "tmp/applied-candidate.mp3"}},
            **kwargs,
        )

        finalized = finalize_segment_candidate_runs(db, asset_ref="tmp/applied-candidate.mp3", **kwargs)
        assert finalized == 1

        run = (
            db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.run_type == CANDIDATE_RUN_TYPE)
            .first()
        )
        assert run.status == "completed"
        assert run.resumable is False
        assert run.expires_at is None


def test_local_save_cleans_stale_segment_files_across_extensions(monkeypatch, tmp_path):
    from app.services.audiobook import temp_segment_store

    monkeypatch.setattr(temp_segment_store, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        temp_segment_store,
        "_LOCAL_TEMP_ROOT_ABS",
        tmp_path / "backend" / "data" / "tmp" / "audiobook_runs",
    )

    backend = temp_segment_store.LocalFSTempSegmentStorageBackend()
    backend.save_audio_map(run_id="run_x", chapter_id=1, audio_map={0: b"audio-v1"}, extension="mp3")
    first_cache = backend.save_audio_map(
        run_id="run_x", chapter_id=1, audio_map={0: b"audio-v2"}, extension="wav"
    )

    prefix_dir = tmp_path / "backend" / "data" / "tmp" / "audiobook_runs" / "run_x" / "chapter_00001"
    names = sorted(path.name for path in prefix_dir.iterdir())
    # 切换输出格式后，同一片段的旧扩展名文件必须一并清理
    assert len(names) == 1
    assert names[0] == first_cache["cached_audio_paths"][0].rsplit("/", 1)[-1]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
