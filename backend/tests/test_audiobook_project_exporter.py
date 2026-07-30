from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.audio_mixer import FFMPEG_AVAILABLE
import app.services.audiobook.project_exporter as project_exporter_module
from app.services.audiobook.project_exporter import (
    ProjectAudioChapter,
    _build_audacity_track_filename,
    _get_project_source_cover_path,
    build_chapter_markers,
    build_ffmetadata_content,
    build_project_audacity_export,
    build_project_audacity_lof_content,
    build_project_m4b_ffmpeg_command,
    build_project_m4b_export,
    collect_project_export_output_files,
    validate_project_m4b_output,
)
from app.services.audiobook.project_export_jobs import (
    PROJECT_EXPORT_STAGE,
    build_project_export_download_url,
    build_project_export_task_detail,
)


try:
    from pydub import AudioSegment
except ImportError:  # pragma: no cover
    AudioSegment = None


def _build_session_factory():
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


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    buffer = io.BytesIO()
    AudioSegment.silent(duration=duration_ms).export(buffer, format="wav")
    path.write_bytes(buffer.getvalue())


def _write_tiny_jpeg(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "ffd8ffe000104a46494600010101006000600000"
            "ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514"
            "ffdb00430103040405040509050509140d0b0d141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414"
            "ffc00011080001000103012200021101031101"
            "ffc4001400010000000000000000000000000000000000000008"
            "ffc4001410010000000000000000000000000000000000000000"
            "ffc4001401010000000000000000000000000000000000000000"
            "ffc4001411010000000000000000000000000000000000000000"
            "ffda000c03010002110311003f00b2c001ffd9"
        )
    )


def test_ffmetadata_content_contains_chapter_markers_and_escaped_metadata():
    chapters = build_chapter_markers(
        [
            ProjectAudioChapter(
                chapter_id=1,
                chapter_number=1,
                title="Intro=A",
                audio_path="chapter_001.wav",
                resolved_audio_path="chapter_001.wav",
                duration_seconds=1.0,
            ),
            ProjectAudioChapter(
                chapter_id=2,
                chapter_number=2,
                title="Next;Part",
                audio_path="chapter_002.wav",
                resolved_audio_path="chapter_002.wav",
                duration_seconds=2.5,
            ),
        ]
    )

    content = build_ffmetadata_content(
        chapters,
        {
            "title": "Book #1",
            "author": "A=B",
            "narrator": "N;R",
            "description": "line1\nline2",
        },
    )

    assert "title=Book \\#1" in content
    assert "artist=A\\=B" in content
    assert "album_artist=N\\;R" in content
    assert "comment=line1 line2" in content
    assert "START=0" in content
    assert "END=1000" in content
    assert "START=1000" in content
    assert "END=3500" in content
    assert "title=1. Intro\\=A" in content
    assert "title=2. Next\\;Part" in content


def test_project_audacity_lof_escapes_track_paths():
    content = build_project_audacity_lof_content(
        [
            "tracks/chapter_001_intro.wav",
            'tracks/chapter_"quoted".wav',
        ]
    )

    assert 'file "tracks/chapter_001_intro.wav"' in content
    assert 'file "tracks/chapter_\\"quoted\\".wav"' in content


def test_project_export_script_segment_parser_ignores_invalid_json():
    assert project_exporter_module._parse_script_segments("{bad-json") == []


def test_project_export_script_segment_parser_does_not_swallow_unexpected_json_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("unexpected json parser failure")

    monkeypatch.setattr(project_exporter_module.json, "loads", boom)

    with pytest.raises(RuntimeError, match="unexpected json parser failure"):
        project_exporter_module._parse_script_segments('{"segments":[]}')


def test_project_audacity_track_filename_is_cross_platform_safe():
    filename = _build_audacity_track_filename(
        ProjectAudioChapter(
            chapter_id=1,
            chapter_number=2,
            title='CON<>:"/\\|?*' + "长标题" * 80,
            audio_path="chapter.wav",
            resolved_audio_path="chapter.wav",
            duration_seconds=1.0,
        ),
        position=2,
    )

    assert filename.startswith("chapter_002_")
    assert filename.endswith(".wav")
    assert len(filename.encode("utf-8")) <= 180
    assert not any(char in filename for char in '<>:"/\\|?*')


def test_collect_project_export_output_files_includes_manifests():
    files = collect_project_export_output_files(project_id=12, audiobook_project_id=34)
    relative_files = {
        path.relative_to(ROOT_DIR.parent).as_posix()
        for path in files
    }

    assert relative_files == {
        "audiobooks/project_12/exports/audiobook_project_34.m4b",
        "audiobooks/project_12/exports/audiobook_project_34.m4b.json",
        "audiobooks/project_12/exports/audiobook_project_34.m4b.CREDITS.md",
        "audiobooks/project_12/exports/audiobook_project_34.m4b.license_manifest.jsonl",
        "audiobooks/project_12/exports/audiobook_project_34_audacity.zip",
        "audiobooks/project_12/exports/audiobook_project_34_audacity.zip.json",
        "audiobooks/project_12/exports/audiobook_project_34_audacity.zip.CREDITS.md",
        "audiobooks/project_12/exports/audiobook_project_34_audacity.zip.license_manifest.jsonl",
    }


def test_project_export_credits_sidecars_delegate_to_sfx_downloader(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeSfxLibraryDownloader:
        def export_attribution_credits(self, *, jsonl_path, markdown_path, used_effect_ids=None):
            calls["jsonl_path"] = Path(jsonl_path)
            calls["markdown_path"] = Path(markdown_path)
            calls["used_effect_ids"] = used_effect_ids
            Path(jsonl_path).parent.mkdir(parents=True, exist_ok=True)
            Path(jsonl_path).write_text('{"effect_id":"rain"}\n', encoding="utf-8")
            Path(markdown_path).write_text("# Audio Credits\n\n- Rain\n", encoding="utf-8")
            return {
                "stats": {"credits": 1},
                "jsonl_path": str(jsonl_path),
                "markdown_path": str(markdown_path),
            }

    monkeypatch.setattr(project_exporter_module, "SfxLibraryDownloader", FakeSfxLibraryDownloader, raising=False)

    result = project_exporter_module._write_project_export_credits(
        tmp_path / "book.m4b",
        used_effect_ids={"rain_1"},
    )

    assert calls["jsonl_path"].name == "book.m4b.license_manifest.jsonl"
    assert calls["markdown_path"].name == "book.m4b.CREDITS.md"
    assert calls["used_effect_ids"] == {"rain_1"}
    assert result["stats"]["credits"] == 1
    assert Path(result["jsonl_path"]).exists()
    assert Path(result["markdown_path"]).exists()


def test_project_export_collects_used_effect_ids_from_checkpoints():
    session_factory = _build_session_factory()

    with session_factory() as db:
        user = User(
            username="effects_user",
            email="effects@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            display_no=1,
            title="Effects Book",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()

        chapter = Chapter(project_id=project.id, chapter_number=1, title="Opening", content="")
        db.add(chapter)
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
        )
        other_audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
        )
        db.add_all([audiobook_project, other_audiobook_project])
        db.flush()

        db.add_all(
            [
                ChapterAudioRun(
                    audiobook_project_id=audiobook_project.id,
                    chapter_id=chapter.id,
                    run_type="full",
                    status="completed",
                    checkpoint_json={
                        "effect_timeline": {
                            "timeline": [
                                {"effect_id": "rain_light"},
                                {"effect_id": "door_open"},
                                {"effect_id": "rain_light"},
                                {"effect_id": ""},
                            ],
                        },
                    },
                ),
                ChapterAudioRun(
                    audiobook_project_id=other_audiobook_project.id,
                    chapter_id=chapter.id,
                    run_type="full",
                    status="completed",
                    checkpoint_json={
                        "effect_timeline": {"timeline": [{"effect_id": "other_project"}]},
                    },
                ),
            ]
        )
        db.commit()

        used_effect_ids = project_exporter_module._collect_project_used_effect_ids(
            db,
            audiobook_project_id=audiobook_project.id,
        )

    assert used_effect_ids == {"rain_light", "door_open"}


def test_cached_m4b_export_uses_checkpoint_effect_ids_for_credits(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory()
    calls = {}

    class FakeSfxLibraryDownloader:
        def export_attribution_credits(self, *, jsonl_path, markdown_path, used_effect_ids=None):
            calls["used_effect_ids"] = used_effect_ids
            Path(jsonl_path).write_text("", encoding="utf-8")
            Path(markdown_path).write_text("# Audio Credits\n", encoding="utf-8")
            return {
                "stats": {"credits": 0},
                "jsonl_path": str(jsonl_path),
                "markdown_path": str(markdown_path),
            }

    monkeypatch.setattr(project_exporter_module, "SfxLibraryDownloader", FakeSfxLibraryDownloader, raising=False)
    audio_file = tmp_path / "chapter_001.mp3"
    audio_file.write_bytes(b"audio")
    output_file = tmp_path / "book.m4b"
    output_file.write_bytes(b"m4b")

    with session_factory() as db:
        user = User(
            username="cached_effects_user",
            email="cached-effects@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            display_no=1,
            title="Cached Effects Book",
            description="",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()

        chapter = Chapter(project_id=project.id, chapter_number=1, title="Opening", content="")
        db.add(chapter)
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
        )
        db.add(audiobook_project)
        db.flush()

        db.add(
            ChapterAudio(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter.id,
                audio_path=str(audio_file),
                duration=1.0,
                file_size=audio_file.stat().st_size,
            )
        )
        db.add(
            ChapterAudioRun(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter.id,
                run_type="full",
                status="completed",
                checkpoint_json={
                    "effect_timeline": {"timeline": [{"effect_id": "rain_light"}]},
                },
            )
        )
        db.commit()

        chapters = project_exporter_module.build_chapter_markers(
            project_exporter_module.collect_project_audio_chapters(
                db,
                audiobook_project_id=audiobook_project.id,
            )
        )
        export_metadata = {
            "title": project.title or "Audiobook",
            "author": "",
            "narrator": "",
            "year": "",
            "description": project.description or "",
        }
        source_signature = project_exporter_module.build_project_export_source_signature(
            chapters,
            export_kind="m4b",
            version=project_exporter_module._M4B_EXPORT_VERSION,
            metadata=export_metadata,
            extra={"cover_art": project_exporter_module._build_file_dependency_payload(None)},
        )
        project_exporter_module._write_project_export_manifest(
            output_file,
            export_kind="m4b",
            source_signature=source_signature,
            result={
                "success": True,
                "cached": False,
                "output_path": str(output_file),
                "source_signature": source_signature,
            },
        )

        result = build_project_m4b_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(output_file),
        )

    assert result["cached"] is True
    assert calls["used_effect_ids"] == {"rain_light"}


def test_m4b_ffmpeg_command_maps_cover_as_attached_picture():
    cmd = build_project_m4b_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        concat_path=Path("concat.txt"),
        metadata_path=Path("metadata.txt"),
        cover_path=Path("cover.jpg"),
        output_file=Path("book.m4b"),
        bitrate="96k",
    )

    assert cmd.count("-i") == 3
    assert cmd[cmd.index("cover.jpg") - 1] == "-i"
    assert cmd[cmd.index("-map_metadata") + 1] == "1"
    assert cmd[cmd.index("-map_chapters") + 1] == "1"
    assert ["-map", "2:v"] == cmd[cmd.index("2:v") - 1:cmd.index("2:v") + 1]
    assert cmd[cmd.index("-disposition:v:0") + 1] == "attached_pic"
    assert cmd[cmd.index("-b:a") + 1] == "96k"
    assert cmd[-1] == "book.m4b"


def test_m4b_output_validation_passes_when_probe_matches(monkeypatch, tmp_path: Path):
    output_file = tmp_path / "book.m4b"
    output_file.write_bytes(b"m4b")

    monkeypatch.setattr(
        project_exporter_module,
        "probe_m4b_output",
        lambda path: {
            "available": True,
            "skipped": False,
            "duration_seconds": 10.1,
            "chapter_count": 2,
            "chapters": [],
        },
    )

    result = validate_project_m4b_output(
        output_file,
        expected_duration_seconds=10.0,
        expected_chapter_count=2,
    )

    assert result["passed"] is True
    assert result["actual_chapter_count"] == 2
    assert result["duration_delta_seconds"] == 0.1


def test_m4b_output_validation_fails_on_missing_chapters(monkeypatch, tmp_path: Path):
    output_file = tmp_path / "book.m4b"
    output_file.write_bytes(b"m4b")

    monkeypatch.setattr(
        project_exporter_module,
        "probe_m4b_output",
        lambda path: {
            "available": True,
            "skipped": False,
            "duration_seconds": 10.0,
            "chapter_count": 0,
            "chapters": [],
        },
    )

    with pytest.raises(project_exporter_module.AudiobookExportError) as exc_info:
        validate_project_m4b_output(
            output_file,
            expected_duration_seconds=10.0,
            expected_chapter_count=2,
        )

    assert exc_info.value.code == "m4b_output_validation_failed"


def test_project_m4b_export_reads_source_book_cover_from_audio_config():
    project = Project(
        user_id=1,
        display_no=1,
        title="Cover Source",
        audio_config=json.dumps(
            {
                "source_book": {
                    "book_id": 9,
                    "cover_path": "backend/data/book_covers/book_9.jpg",
                }
            },
            ensure_ascii=False,
        ),
        status="draft",
    )

    assert _get_project_source_cover_path(project) == "backend/data/book_covers/book_9.jpg"


@pytest.mark.skipif(AudioSegment is None, reason="pydub unavailable")
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg unavailable")
def test_project_m4b_export_merges_completed_chapters_with_markers(tmp_path: Path):
    session_factory = _build_session_factory()
    audio_1 = tmp_path / "chapter_001.wav"
    audio_2 = tmp_path / "chapter_002.wav"
    _write_silent_wav(audio_1, 500)
    _write_silent_wav(audio_2, 700)

    with session_factory() as db:
        user = User(
            username="export_user",
            email="export@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            display_no=1,
            title="Export Book",
            description="Export description",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()

        chapter_1 = Chapter(project_id=project.id, chapter_number=1, title="Opening", content="")
        chapter_2 = Chapter(project_id=project.id, chapter_number=2, title="Turn", content="")
        db.add_all([chapter_1, chapter_2])
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=2,
            completed_chapters=2,
        )
        db.add(audiobook_project)
        db.flush()

        db.add_all(
            [
                ChapterAudio(
                    audiobook_project_id=audiobook_project.id,
                    chapter_id=chapter_2.id,
                    audio_path=str(audio_2),
                    duration=0.7,
                    file_size=audio_2.stat().st_size,
                ),
                ChapterAudio(
                    audiobook_project_id=audiobook_project.id,
                    chapter_id=chapter_1.id,
                    audio_path=str(audio_1),
                    duration=0.5,
                    file_size=audio_1.stat().st_size,
                ),
            ]
        )
        db.commit()

        result = build_project_m4b_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(tmp_path / "book.m4b"),
            metadata={"author": "Author", "narrator": "Narrator"},
        )

    output_file = Path(result["output_path"])
    if not output_file.is_absolute():
        output_file = ROOT_DIR.parent / output_file

    assert result["success"] is True
    assert result["chapter_count"] == 2
    assert result["chapters"][0]["chapter_number"] == 1
    assert result["chapters"][1]["chapter_number"] == 2
    assert result["chapters"][0]["start_ms"] == 0
    assert result["chapters"][1]["start_ms"] >= result["chapters"][0]["end_ms"]
    assert result["output_validation"]["passed"] is True
    assert result["output_validation"]["expected_chapter_count"] == 2
    assert Path(result["credits"]["markdown_path"]).exists()
    assert Path(result["credits"]["jsonl_path"]).exists()
    assert output_file.exists()
    assert b"ftyp" in output_file.read_bytes()[:32]


@pytest.mark.skipif(AudioSegment is None, reason="pydub unavailable")
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg unavailable")
def test_project_m4b_export_embeds_cover_metadata_and_cache_signature(tmp_path: Path):
    session_factory = _build_session_factory()
    audio_1 = tmp_path / "chapter_001.wav"
    cover = tmp_path / "cover.jpg"
    _write_silent_wav(audio_1, 500)
    _write_tiny_jpeg(cover)

    with session_factory() as db:
        user = User(
            username="cover_user",
            email="cover@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            display_no=1,
            title="Cover Book",
            description="Cover description",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()

        chapter = Chapter(project_id=project.id, chapter_number=1, title="Opening", content="")
        db.add(chapter)
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
        )
        db.add(audiobook_project)
        db.flush()

        db.add(
            ChapterAudio(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter.id,
                audio_path=str(audio_1),
                duration=0.5,
                file_size=audio_1.stat().st_size,
            )
        )
        db.commit()

        output_path = tmp_path / "book_with_cover.m4b"
        result = build_project_m4b_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(output_path),
            metadata={"cover_path": str(cover), "author": "Author"},
        )
        cached_result = build_project_m4b_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(output_path),
            metadata={"cover_path": str(cover), "author": "Author"},
        )

    assert output_path.exists()
    assert result["cached"] is False
    assert result["cover_art"] == project_exporter_module._to_repo_relative_path(cover)
    assert cached_result["cached"] is True
    assert cached_result["source_signature"] == result["source_signature"]


@pytest.mark.skipif(AudioSegment is None, reason="pydub unavailable")
def test_project_audacity_export_packages_tracks_lof_and_labels(tmp_path: Path):
    session_factory = _build_session_factory()
    audio_1 = tmp_path / "chapter_001.wav"
    audio_2 = tmp_path / "chapter_002.wav"
    _write_silent_wav(audio_1, 500)
    _write_silent_wav(audio_2, 700)

    with session_factory() as db:
        user = User(
            username="audacity_user",
            email="audacity@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            display_no=1,
            title="Audacity Book",
            description="Audacity description",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()

        chapter_1 = Chapter(project_id=project.id, chapter_number=1, title="Opening", content="")
        chapter_2 = Chapter(project_id=project.id, chapter_number=2, title="Turn", content="")
        db.add_all([chapter_1, chapter_2])
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=2,
            completed_chapters=2,
        )
        db.add(audiobook_project)
        db.flush()

        db.add_all(
            [
                ChapterAudio(
                    audiobook_project_id=audiobook_project.id,
                    chapter_id=chapter_1.id,
                    audio_path=str(audio_1),
                    duration=0.5,
                    file_size=audio_1.stat().st_size,
                    script_json=json.dumps(
                        [{"text": "Opening line", "speaker": "Narrator"}],
                        ensure_ascii=False,
                    ),
                ),
                ChapterAudio(
                    audiobook_project_id=audiobook_project.id,
                    chapter_id=chapter_2.id,
                    audio_path=str(audio_2),
                    duration=0.7,
                    file_size=audio_2.stat().st_size,
                ),
            ]
        )
        db.add(
            ChapterAudioRun(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter_1.id,
                run_type="full",
                status="completed",
                checkpoint_json={
                    "segment_timings": [
                        {"index": 0, "start": 0.0, "end": 0.3, "duration": 0.3},
                    ],
                },
            )
        )
        db.commit()

        result = build_project_audacity_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(tmp_path / "audacity.zip"),
        )
        cached_result = build_project_audacity_export(
            db,
            audiobook_project=audiobook_project,
            project=project,
            output_path=str(tmp_path / "audacity.zip"),
        )

    output_file = Path(result["output_path"])
    assert output_file.exists()
    assert result["success"] is True
    assert result["cached"] is False
    assert result["chapter_count"] == 2
    assert result["track_count"] == 2
    assert result["track_mode"] == "mixed"
    assert result["label_count"] == 2
    assert cached_result["success"] is True
    assert cached_result["cached"] is True
    assert cached_result["source_signature"] == result["source_signature"]
    assert cached_result["track_mode"] == result["track_mode"]
    assert Path(f"{output_file}.json").exists()

    with zipfile.ZipFile(output_file) as archive:
        names = set(archive.namelist())
        assert "project.lof" in names
        assert "labels.txt" in names
        assert "CREDITS.md" in names
        assert "license_manifest.jsonl" in names
        assert "tracks/speaker_Narrator.wav" in names
        assert "tracks/chapter_002_Turn.wav" in names

        lof_content = archive.read("project.lof").decode("utf-8")
        labels_content = archive.read("labels.txt").decode("utf-8")
        credits_content = archive.read("CREDITS.md").decode("utf-8")

    assert 'file "tracks/speaker_Narrator.wav"' in lof_content
    assert 'file "tracks/chapter_002_Turn.wav"' in lof_content
    assert "0.000000\t0.300000\t[Narrator] Opening line" in labels_content
    assert "\t2. Turn" in labels_content
    assert "# Audio Credits" in credits_content


def test_project_m4b_export_routes_are_registered():
    route_file = ROOT_DIR / "app/api/v1/audiobook_api/routes_projects.py"
    content = route_file.read_text(encoding="utf-8")

    assert "/projects/{audiobook_project_id:int}/exports/m4b" in content
    assert "/projects/{audiobook_project_id:int}/exports/m4b/queue" in content
    assert "/projects/{audiobook_project_id:int}/exports/m4b/download" in content
    assert "build_project_m4b_export" in content
    assert "audiobook.export_m4b" in content
    assert "/projects/{audiobook_project_id:int}/exports/audacity" in content
    assert "/projects/{audiobook_project_id:int}/exports/audacity/queue" in content
    assert "/projects/{audiobook_project_id:int}/exports/audacity/download" in content
    assert "build_project_audacity_export" in content
    assert "audiobook.export_audacity" in content


def test_project_export_celery_tasks_are_registered():
    task_file = ROOT_DIR / "app/tasks/audiobook_tasks.py"
    content = task_file.read_text(encoding="utf-8")

    assert '@celery_app.task(name="audiobook.export_m4b", bind=True)' in content
    assert '@celery_app.task(name="audiobook.export_audacity", bind=True)' in content
    assert "build_project_m4b_export" in content
    assert "build_project_audacity_export" in content
    assert "build_audiobook_trace_context" in content
    assert "trace_context=_build_project_export_trace_context" in content


def test_project_export_task_detail_contains_stage_and_download_url():
    detail = build_project_export_task_detail(
        audiobook_project_id=34,
        export_type="audacity",
        status="completed",
        progress=1.0,
        message="Audacity ZIP 导出完成",
        result={
            "cached": True,
            "chapter_count": 2,
            "duration": 3.5,
            "file_size": 1024,
            "track_count": 4,
            "label_count": 8,
            "track_mode": "speaker",
        },
    )

    assert detail["download_url"] == build_project_export_download_url(34, "audacity")
    assert detail["current_stage"] == PROJECT_EXPORT_STAGE
    assert detail["export_result"]["cached"] is True
    stage = detail["stages"][PROJECT_EXPORT_STAGE]
    assert stage["status"] == "completed"
    assert stage["progress"] == 1.0
    assert stage["metrics"]["track_count"] == 4


def test_project_export_task_detail_adds_trace_context_without_overwriting_detail_fields():
    detail = build_project_export_task_detail(
        audiobook_project_id=34,
        export_type="m4b",
        status="running",
        progress=0.05,
        message="正在导出整本 M4B",
        trace_context={
            "trace_id": "celery-123",
            "celery_task_id": "celery-123",
            "task_db_id": 56,
            "task_type": "export_m4b",
            "audiobook_project_id": 999,
            "stage": PROJECT_EXPORT_STAGE,
            "status": "running",
            "progress": 0.05,
        },
    )

    assert detail["audiobook_project_id"] == 34
    assert detail["trace_id"] == "celery-123"
    assert detail["celery_task_id"] == "celery-123"
    assert detail["task_db_id"] == 56
    assert detail["task_type"] == "export_m4b"
    assert detail["stage"] == PROJECT_EXPORT_STAGE
    assert detail["status"] == "running"
    assert detail["progress"] == 0.05


def test_audiobook_delete_routes_clean_project_export_artifacts():
    route_file = ROOT_DIR / "app/api/v1/audiobook_api/routes_delete.py"
    content = route_file.read_text(encoding="utf-8")

    assert "collect_project_export_output_files" in content
    assert "_collect_chapter_audio_artifact_files" in content
    assert ".labels.txt" in content
