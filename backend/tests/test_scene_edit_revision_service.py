"""场景编辑 revision 双表服务单元测试（GUIDE §2.9/§3.2/§3.3）。

覆盖：hash 公式确定性、幂等短路（同 base 同内容重复提交返回原 revision）、
base 失配 409、链式推进、head 投影与 revision_set_hash、voice_binding 双写
（audio_config 默认值 + 当前章节 stale）、SAVEPOINT 恢复协议（IntegrityError
后仅回滚到 SAVEPOINT 并重读 head）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
    ChapterAudioRun,
    SceneEditRevision,
    SceneEditRevisionHead,
)
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.scene_edit_revision_service import (  # noqa: E402
    RevisionConflictError,
    append_scene_edit_revision,
    append_voice_binding_revision,
    build_scene_editor_document,
    canonical_json,
    compute_input_signature,
    compute_revision_hash,
    compute_revision_set_hash,
    get_revision_heads_projection,
)
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model  # noqa: E402


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def ctx(db):
    user = User(username="scene_editor_tester", email="scene_editor_tester@example.com")
    db.add(user)
    db.flush()
    project = Project(
        display_no=1,
        user_id=user.id,
        title="场景编辑器测试项目",
        audio_config=json.dumps(
            {"audio_engine_mode": "seed_scene", "engines": {"seed_scene": {}}},
            ensure_ascii=False,
        ),
    )
    db.add(project)
    db.flush()
    audiobook_project = AudiobookProject(project_id=project.id, engine_mode="seed_scene")
    db.add(audiobook_project)
    db.flush()
    chapter = Chapter(project_id=project.id, title="第一章", chapter_number=1)
    db.add(chapter)
    db.flush()
    chapter_audio = ChapterAudio(
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter.id,
        script_json=json.dumps(
            [
                {
                    "type": "narration",
                    "text": "原文",
                    "speaker": "旁白",
                    "segment_key": "seg_alpha",
                }
            ],
            ensure_ascii=False,
        ),
    )
    db.add(chapter_audio)
    db.flush()
    db.commit()
    return {
        "user": user,
        "project": project,
        "audiobook_project": audiobook_project,
        "chapter": chapter,
        "chapter_audio": chapter_audio,
    }


def _base(ctx):
    return {
        "audiobook_project_id": ctx["audiobook_project"].id,
        "chapter_id": ctx["chapter"].id,
        "chapter_audio_id": ctx["chapter_audio"].id,
    }


# ——— hash 公式（§2.9） ———


class TestHashFormulas:
    def test_canonical_json_is_deterministic(self):
        a = canonical_json({"b": 2, "a": [1, "中"], "nested": {"z": 1, "y": 2}})
        b = canonical_json({"nested": {"y": 2, "z": 1}, "a": [1, "中"], "b": 2})
        assert a == b
        assert " " not in a and "\n" not in a

    def test_input_signature_ignores_parent(self):
        payload = {"scene_id": "scene_0001", "overrides": [{"direction_type": "sfx", "content": "雷声"}]}
        anchors = ["seg_alpha"]
        sig = compute_input_signature(edit_type="director_override", payload=payload, affected_anchors=anchors)
        assert isinstance(sig, str) and len(sig) == 64
        # input_signature 只覆盖编辑内容：父引用变化不影响
        sig2 = compute_input_signature(edit_type="director_override", payload=payload, affected_anchors=anchors)
        assert sig == sig2

    def test_revision_hash_parent_participates(self):
        payload = {"scene_id": "scene_0001"}
        common = dict(
            audiobook_project_id=1,
            chapter_id=2,
            edit_type="director_override",
            payload=payload,
            affected_anchors=["seg_alpha"],
        )
        h1 = compute_revision_hash(**common, parent_revision_hash="")
        h2 = compute_revision_hash(**common, parent_revision_hash="parent-hash")
        assert h1 != h2
        assert len(h1) == 64 and len(h2) == 64

    def test_revision_set_hash_projection(self):
        projection = {
            "dialogue": {"revision_hash": "a" * 64},
            "director_override": None,
            "voice_binding": {"revision_hash": "c" * 64},
        }
        s1 = compute_revision_set_hash(projection)
        s2 = compute_revision_set_hash(
            {"voice_binding": {"revision_hash": "c" * 64}, "director_override": None, "dialogue": {"revision_hash": "a" * 64}}
        )
        assert s1 == s2
        assert compute_revision_set_hash(
            {"dialogue": {"revision_hash": "b" * 64}, "director_override": None, "voice_binding": {"revision_hash": "c" * 64}}
        ) != s1


# ——— append 语义（§2.9 幂等 / base 比对 / 链式推进） ———


class TestAppendRevision:
    def test_first_append_creates_revision_and_head(self, db, ctx):
        revision = append_scene_edit_revision(
            db,
            **_base(ctx),
            edit_type="director_override",
            payload={"scene_id": "scene_0001", "overrides": [{"direction_type": "sfx", "content": "雷声"}]},
            affected_anchors=["seg_alpha"],
            base_revision_hash=None,
            operator_user_id=ctx["user"].id,
        )
        db.commit()
        assert revision.parent_revision_id is None
        assert revision.edit_type == "director_override"
        head = (
            db.query(SceneEditRevisionHead)
            .filter(
                SceneEditRevisionHead.audiobook_project_id == ctx["audiobook_project"].id,
                SceneEditRevisionHead.chapter_id == ctx["chapter"].id,
                SceneEditRevisionHead.edit_type == "director_override",
            )
            .one()
        )
        assert head.head_revision_id == revision.id
        # 幂等判定：候选 hash 以请求 base（None→空串）为 parent，与 head 一致
        assert revision.revision_hash == compute_revision_hash(
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            edit_type="director_override",
            payload={"scene_id": "scene_0001", "overrides": [{"direction_type": "sfx", "content": "雷声"}]},
            affected_anchors=["seg_alpha"],
            parent_revision_hash=None,
        )

    def test_idempotent_retry_returns_original_revision(self, db, ctx):
        kwargs = dict(
            **_base(ctx),
            edit_type="dialogue",
            payload={"script_segments": [], "semantic_fingerprint": "fp"},
            affected_anchors=[],
            base_revision_hash=None,
        )
        first = append_scene_edit_revision(db, **kwargs)
        db.commit()
        second = append_scene_edit_revision(db, **kwargs)
        db.commit()
        assert second.id == first.id
        assert db.query(SceneEditRevision).count() == 1

    def test_base_mismatch_raises_conflict(self, db, ctx):
        append_scene_edit_revision(
            db,
            **_base(ctx),
            edit_type="dialogue",
            payload={"script_segments": [], "semantic_fingerprint": "fp1"},
            affected_anchors=[],
            base_revision_hash=None,
        )
        db.commit()
        with pytest.raises(RevisionConflictError) as exc_info:
            append_scene_edit_revision(
                db,
                **_base(ctx),
                edit_type="dialogue",
                payload={"script_segments": [], "semantic_fingerprint": "fp2"},
                affected_anchors=[],
                base_revision_hash="stale-base-hash",
            )
        assert exc_info.value.current_head_hash is not None

    def test_chain_progression_parent_link(self, db, ctx):
        base = None
        previous = None
        for index in range(3):
            revision = append_scene_edit_revision(
                db,
                **_base(ctx),
                edit_type="director_override",
                payload={"scene_id": f"scene_{index}", "overrides": []},
                affected_anchors=[f"seg_{index}"],
                base_revision_hash=base,
            )
            db.commit()
            assert revision.parent_revision_id == previous
            previous = revision.id
            base = revision.revision_hash
        chain = (
            db.query(SceneEditRevision)
            .filter(
                SceneEditRevision.edit_type == "director_override",
                SceneEditRevision.audiobook_project_id == ctx["audiobook_project"].id,
            )
            .order_by(SceneEditRevision.id.asc())
            .all()
        )
        assert [revision.parent_revision_id for revision in chain] == [None, chain[0].id, chain[1].id]

    def test_base_on_first_edit_raises_conflict(self, db, ctx):
        with pytest.raises(RevisionConflictError):
            append_scene_edit_revision(
                db,
                **_base(ctx),
                edit_type="voice_binding",
                payload={"scope": "chapter"},
                affected_anchors=[],
                base_revision_hash="some-base",
            )

    def test_heads_projection_and_set_hash(self, db, ctx):
        append_scene_edit_revision(
            db,
            **_base(ctx),
            edit_type="director_override",
            payload={"scene_id": "scene_0001", "overrides": []},
            affected_anchors=["seg_alpha"],
            base_revision_hash=None,
        )
        db.commit()
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
        )
        assert set(heads.keys()) == {"dialogue", "director_override", "voice_binding"}
        assert heads["dialogue"] is None
        assert heads["director_override"]["revision_hash"]
        assert heads["voice_binding"] is None
        set_hash = compute_revision_set_hash(heads)
        assert isinstance(set_hash, str) and len(set_hash) == 64


# ——— voice_binding 双写（§2.6/§3.2） ———


class TestVoiceBindingDoubleWrite:
    def test_double_write_updates_config_and_stales_current_chapter(self, db, ctx):
        characters = [
            {"character_name": "主角", "voice_id": "voice-a", "reference_source": "seed"},
        ]
        revision = append_voice_binding_revision(
            db,
            **_base(ctx),
            project_id=ctx["project"].id,
            engine_mode="seed_scene",
            tts_model="seed-audio-1.0-multilingual",
            characters=characters,
            base_revision_hash=None,
            operator_user_id=ctx["user"].id,
        )
        db.commit()
        assert revision.edit_type == "voice_binding"

        # 双写：audio_config 写入未来批次默认值（键经 normalize_audiobook_tts_model 归一化）
        db.refresh(ctx["project"])
        config = json.loads(ctx["project"].audio_config)
        model_key = normalize_audiobook_tts_model("seed-audio-1.0-multilingual")
        saved = (
            config.get("engines", {})
            .get("seed_scene", {})
            .get("tts_models", {})
            .get(model_key, {})
            .get("characters")
        )
        assert saved == characters

        # 仅当前章节置 stale：updated_at 推进 + render_status_detail 记录原因
        db.refresh(ctx["chapter_audio"])
        detail = ctx["chapter_audio"].render_status_detail or {}
        assert detail.get("stale_reason") == "voice_binding_changed"

        # 链上可投影
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
        )
        assert heads["voice_binding"] is not None

    def test_voice_binding_concurrent_edits_serialized_by_head(self, db, ctx):
        append_voice_binding_revision(
            db,
            **_base(ctx),
            project_id=ctx["project"].id,
            engine_mode="seed_scene",
            tts_model="seed-audio-1.0-multilingual",
            characters=[{"character_name": "主角", "voice_id": "voice-a"}],
            base_revision_hash=None,
        )
        db.commit()
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
        )
        # 后提交者携带过期 base → 409（不同章节并发双写被 head 锁串行化）
        with pytest.raises(RevisionConflictError):
            append_voice_binding_revision(
                db,
                **_base(ctx),
                project_id=ctx["project"].id,
                engine_mode="seed_scene",
                tts_model="seed-audio-1.0-multilingual",
                characters=[{"character_name": "主角", "voice_id": "voice-b"}],
                base_revision_hash="stale-base",
            )

    def test_editor_document_projects_current_voice_binding_for_echo(self, db, ctx):
        # 音色编辑表单需要回显当前生效绑定，否则用户面对空表单无从下手
        characters = [
            {
                "character_name": "林晚",
                "voice_id": "voice_pool:pub-1",
                "reference_source": "public_pool",
                "reference_audio_url": "https://example.com/ref.mp3",
            },
        ]
        append_voice_binding_revision(
            db,
            **_base(ctx),
            project_id=ctx["project"].id,
            engine_mode="seed_scene",
            tts_model="seed-tts-2.0-expressive",
            characters=characters,
            base_revision_hash=None,
        )
        db.commit()
        document = build_scene_editor_document(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            chapter_audio=ctx["chapter_audio"],
        )
        assert document.voice_binding_current == {
            "tts_model": "seed-tts-2.0-expressive",
            "characters": characters,
        }

    def test_editor_document_voice_binding_current_is_none_without_revision(self, db, ctx):
        document = build_scene_editor_document(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            chapter_audio=ctx["chapter_audio"],
        )
        assert document.voice_binding_current is None


# ——— editor-document 提示词投影（P1 透明化） ———


class TestEditorDocumentPromptProjection:
    def _checkpoint(self, *, with_prompt: bool) -> dict:
        scene_entry = {
            "scene_id": "scene_0001",
            "status": "passed",
            "source_segment_indices": [0],
            "attempts": 1,
            "prompt_hash": "hash-scene-0001",
        }
        if with_prompt:
            scene_entry["prompt"] = "场景：潮湿水牢。\n按顺序生成：\n1. 旁白说：\"原文\"（自然）"
        return {"scene_checkpoints": {"scene_0001": scene_entry}}

    def _document(self, db, ctx, checkpoint: dict):
        run = ChapterAudioRun(
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            chapter_audio_id=ctx["chapter_audio"].id,
            run_type="full",
            status="completed",
            checkpoint_json=checkpoint,
        )
        db.add(run)
        db.flush()
        ctx["chapter_audio"].desired_run_id = run.id
        db.commit()
        return build_scene_editor_document(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            chapter_audio=ctx["chapter_audio"],
        )

    def test_projects_scene_prompt_from_checkpoint(self, db, ctx):
        document = self._document(db, ctx, self._checkpoint(with_prompt=True))
        assert len(document.scenes) == 1
        scene = document.scenes[0]
        assert scene.scene_id == "scene_0001"
        # P1：场景条目携带渲染提示词全文与指纹，前端可直接展示
        assert scene.prompt == "场景：潮湿水牢。\n按顺序生成：\n1. 旁白说：\"原文\"（自然）"
        assert scene.prompt_hash == "hash-scene-0001"

    def test_legacy_checkpoint_without_prompt_projects_none(self, db, ctx):
        document = self._document(db, ctx, self._checkpoint(with_prompt=False))
        scene = document.scenes[0]
        # 旧 checkpoint 无 prompt 字段：不报错，投影为 None（前端提示重渲染后可见）
        assert scene.prompt is None
        assert scene.prompt_hash == "hash-scene-0001"


# ——— SAVEPOINT 恢复协议（R8/R9） ———


class TestSavepointRecovery:
    def test_idempotent_retry_after_other_transaction_committed(self, db, ctx, session_factory):
        """并发 loser：另一事务已提交同 scope head → 本事务重试同 base 同内容 →
        幂等短路返回原 revision（R7 闭环），不产生分叉链。"""
        kwargs = dict(
            **_base(ctx),
            edit_type="director_override",
            payload={"scene_id": "scene_0001", "overrides": []},
            affected_anchors=["seg_alpha"],
            base_revision_hash=None,
        )
        # 事务 A 先提交
        append_scene_edit_revision(db, **kwargs)
        db.commit()

        # 事务 B（独立 session，同一内存库）：同 base 同内容重试 → 幂等成功
        other = session_factory()
        try:
            replay = append_scene_edit_revision(other, **kwargs)
            other.commit()
            original = (
                db.query(SceneEditRevision)
                .filter(
                    SceneEditRevision.audiobook_project_id == ctx["audiobook_project"].id,
                    SceneEditRevision.edit_type == "director_override",
                )
                .one()
            )
            assert replay.id == original.id
        finally:
            other.close()

    def test_integrity_error_rolls_back_to_savepoint_only(self, db, ctx, session_factory):
        """SAVEPOINT 恢复协议（R8/R9）：首次编辑并发窗口——事务内已存在同
        scope 同 hash 的 revision（head 未建）时，插入撞 uq_scene_edit_revision_hash
        → IntegrityError → 仅回滚到 SAVEPOINT 后重读 head，不抛
        PendingRollbackError，外层事务保持可用。"""
        payload_a = {"scene_id": "scene_0001", "overrides": [{"direction_type": "sfx", "content": "雷声"}]}
        pre = SceneEditRevision(
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
            parent_revision_id=None,
            edit_type="director_override",
            payload=canonical_json(payload_a),
            affected_anchors=canonical_json(["seg_alpha"]),
            input_signature=compute_input_signature(
                edit_type="director_override", payload=payload_a, affected_anchors=["seg_alpha"]
            ),
            revision_hash=compute_revision_hash(
                audiobook_project_id=ctx["audiobook_project"].id,
                chapter_id=ctx["chapter"].id,
                edit_type="director_override",
                payload=payload_a,
                affected_anchors=["seg_alpha"],
                parent_revision_hash=None,
            ),
            operator_user_id=ctx["user"].id,
        )
        db.add(pre)
        db.flush()

        # 同事务 append 相同 payload 相同 base → candidate hash 与已存在行相同
        # → SAVEPOINT flush 撞 uq_scene_edit_revision_hash → 恢复 → 重读 head（无）→ 重抛
        with pytest.raises(IntegrityError):
            append_scene_edit_revision(
                db,
                **_base(ctx),
                edit_type="director_override",
                payload=payload_a,
                affected_anchors=["seg_alpha"],
                base_revision_hash=None,
            )
        # 外层事务仍可用（未 PendingRollbackError），可继续读与写
        assert db.query(SceneEditRevision).count() == 1
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
        )
        assert heads["director_override"] is None

    def test_savepoint_conflict_with_different_content(self, db, ctx, session_factory):
        """并发不同请求：loser 携带过期 base → 409 而非静默覆盖。"""
        base_kwargs = dict(
            **_base(ctx),
            edit_type="dialogue",
            payload={"script_segments": [], "semantic_fingerprint": "fp-base"},
            affected_anchors=[],
            base_revision_hash=None,
        )
        append_scene_edit_revision(db, **base_kwargs)
        db.commit()
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=ctx["audiobook_project"].id,
            chapter_id=ctx["chapter"].id,
        )
        current_hash = heads["dialogue"]["revision_hash"]

        other = session_factory()
        try:
            with pytest.raises(RevisionConflictError) as exc_info:
                append_scene_edit_revision(
                    other,
                    **_base(ctx),
                    edit_type="dialogue",
                    payload={"script_segments": [], "semantic_fingerprint": "fp-new"},
                    affected_anchors=[],
                    base_revision_hash="stale-base-hash",
                )
            assert exc_info.value.current_head_hash == current_hash
            other.rollback()
        finally:
            other.close()

    def test_unsupported_edit_type_rejected(self, db, ctx):
        with pytest.raises(ValueError):
            append_scene_edit_revision(
                db,
                **_base(ctx),
                edit_type="unknown",
                payload={},
                affected_anchors=[],
                base_revision_hash=None,
            )
