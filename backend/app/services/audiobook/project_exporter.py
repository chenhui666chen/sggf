from __future__ import annotations

import json
import re
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.services.audiobook.project_audio_config import parse_project_audio_config
from app.services.audiobook.safe_filename import (
    build_safe_filename,
    ensure_unique_filename,
    sanitize_filename_component,
)
from app.services.audiobook.subtitle_generator import SubtitleGenerator


_CURRENT_FILE = Path(__file__).resolve()
_REPO_ROOT = _CURRENT_FILE.parents[4]
_DEFAULT_M4B_BITRATE = "128k"
_M4B_EXPORT_VERSION = 1
_AUDACITY_EXPORT_VERSION = 2


class AudiobookExportError(RuntimeError):
    """Raised when a project-level audiobook export cannot be produced."""

    def __init__(self, message: str, *, code: str = "audiobook_export_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProjectAudioChapter:
    chapter_id: int
    chapter_number: int
    title: str
    audio_path: str
    resolved_audio_path: str
    duration_seconds: float
    start_ms: int = 0
    end_ms: int = 0


@dataclass(frozen=True)
class AudacityTrackExport:
    path: str
    arcname: str
    kind: str
    name: str


def build_project_m4b_output_path(*, project_id: int, audiobook_project_id: int) -> str:
    return f"audiobooks/project_{int(project_id)}/exports/audiobook_project_{int(audiobook_project_id)}.m4b"


def build_project_audacity_output_path(*, project_id: int, audiobook_project_id: int) -> str:
    return f"audiobooks/project_{int(project_id)}/exports/audiobook_project_{int(audiobook_project_id)}_audacity.zip"


def resolve_project_m4b_output_file(*, project_id: int, audiobook_project_id: int) -> Path:
    return _resolve_output_path(
        build_project_m4b_output_path(
            project_id=project_id,
            audiobook_project_id=audiobook_project_id,
        )
    )


def resolve_project_audacity_output_file(*, project_id: int, audiobook_project_id: int) -> Path:
    return _resolve_output_path(
        build_project_audacity_output_path(
            project_id=project_id,
            audiobook_project_id=audiobook_project_id,
        )
    )


def collect_project_export_output_files(*, project_id: int, audiobook_project_id: int) -> List[Path]:
    output_files = [
        resolve_project_m4b_output_file(
            project_id=project_id,
            audiobook_project_id=audiobook_project_id,
        ),
        resolve_project_audacity_output_file(
            project_id=project_id,
            audiobook_project_id=audiobook_project_id,
        ),
    ]
    manifest_files = [_project_export_manifest_path(path) for path in output_files]
    return _unique_paths(output_files + manifest_files)


def build_project_m4b_export(
    db: Session,
    *,
    audiobook_project: AudiobookProject,
    project: Project,
    output_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    bitrate: str = _DEFAULT_M4B_BITRATE,
    timeout_seconds: int = 1800,
    force: bool = False,
) -> Dict[str, Any]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise AudiobookExportError("ffmpeg 不可用，无法生成 M4B", code="ffmpeg_unavailable")

    chapters = collect_project_audio_chapters(db, audiobook_project_id=audiobook_project.id)
    chapters = build_chapter_markers(chapters)
    if not chapters:
        raise AudiobookExportError("没有可导出的章节音频", code="no_completed_chapter_audio")

    resolved_output_path = output_path or build_project_m4b_output_path(
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
    )
    output_file = _resolve_output_path(resolved_output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    export_metadata = {
        "title": project.title or "Audiobook",
        "author": "",
        "narrator": "",
        "year": "",
        "description": project.description or "",
        **(metadata or {}),
    }
    if not str(export_metadata.get("cover_path") or "").strip():
        project_cover_path = _get_project_source_cover_path(project)
        if project_cover_path:
            export_metadata["cover_path"] = project_cover_path
    cover_path_raw = str(export_metadata.get("cover_path") or "").strip()
    cover_path = resolve_existing_audio_path(cover_path_raw) if cover_path_raw else None
    if cover_path_raw and cover_path is None:
        raise AudiobookExportError("M4B 封面图片不存在", code="cover_art_missing")

    source_signature = build_project_export_source_signature(
        chapters,
        export_kind="m4b",
        version=_M4B_EXPORT_VERSION,
        metadata=export_metadata,
        extra={"cover_art": _build_file_dependency_payload(cover_path)},
    )
    cached_result = _load_cached_project_export_result(
        output_file,
        export_kind="m4b",
        source_signature=source_signature,
    )
    if cached_result and not force:
        return cached_result

    with tempfile.TemporaryDirectory(prefix="audiobook_m4b_") as tmp_dir:
        temp_dir = Path(tmp_dir)
        concat_path = temp_dir / "concat.txt"
        metadata_path = temp_dir / "metadata.txt"
        concat_path.write_text(build_ffmpeg_concat_content(chapters), encoding="utf-8")
        metadata_path.write_text(
            build_ffmetadata_content(chapters, export_metadata),
            encoding="utf-8",
        )

        cmd = build_project_m4b_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            concat_path=concat_path,
            metadata_path=metadata_path,
            output_file=output_file,
            bitrate=bitrate,
            cover_path=cover_path,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-800:].strip()
            raise AudiobookExportError(
                f"ffmpeg 生成 M4B 失败: {stderr_tail or result.returncode}",
                code="ffmpeg_failed",
            )

    file_size = output_file.stat().st_size if output_file.exists() else 0
    if file_size <= 0:
        raise AudiobookExportError("M4B 输出文件为空", code="empty_m4b_output")

    expected_duration = sum(chapter.duration_seconds for chapter in chapters)
    output_validation = validate_project_m4b_output(
        output_file,
        expected_duration_seconds=expected_duration,
        expected_chapter_count=len(chapters),
    )
    result = {
        "success": True,
        "cached": False,
        "output_path": _to_repo_relative_path(output_file),
        "file_size": file_size,
        "duration": round(expected_duration, 6),
        "chapter_count": len(chapters),
        "chapters": [asdict(chapter) for chapter in chapters],
        "metadata": export_metadata,
        "cover_art": _to_repo_relative_path(cover_path) if cover_path else None,
        "output_validation": output_validation,
        "source_signature": source_signature,
    }
    _write_project_export_manifest(
        output_file,
        export_kind="m4b",
        source_signature=source_signature,
        result=result,
    )
    return result


def build_project_audacity_export(
    db: Session,
    *,
    audiobook_project: AudiobookProject,
    project: Project,
    output_path: Optional[str] = None,
    timeout_seconds: int = 1800,
    force: bool = False,
) -> Dict[str, Any]:
    chapters = build_chapter_markers(
        collect_project_audio_chapters(db, audiobook_project_id=audiobook_project.id)
    )
    if not chapters:
        raise AudiobookExportError("没有可导出的章节音频", code="no_completed_chapter_audio")

    resolved_output_path = output_path or build_project_audacity_output_path(
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
    )
    output_file = _resolve_output_path(resolved_output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    chapter_audio_by_id = _load_chapter_audio_map(
        db,
        audiobook_project_id=audiobook_project.id,
        chapters=chapters,
    )
    source_signature = build_project_export_source_signature(
        chapters,
        export_kind="audacity",
        version=_AUDACITY_EXPORT_VERSION,
        extra=_build_audacity_export_dependency_payload(
            db,
            audiobook_project_id=audiobook_project.id,
            chapters=chapters,
            chapter_audio_by_id=chapter_audio_by_id,
        ),
    )
    cached_result = _load_cached_project_export_result(
        output_file,
        export_kind="audacity",
        source_signature=source_signature,
    )
    if cached_result and not force:
        return cached_result

    with tempfile.TemporaryDirectory(prefix="audiobook_audacity_") as tmp_dir:
        temp_dir = Path(tmp_dir)
        tracks_dir = temp_dir / "tracks"
        tracks_dir.mkdir(parents=True, exist_ok=True)

        track_entries = _build_audacity_track_exports(
            db,
            audiobook_project_id=audiobook_project.id,
            chapters=chapters,
            chapter_audio_by_id=chapter_audio_by_id,
            tracks_dir=tracks_dir,
            timeout_seconds=timeout_seconds,
        )
        labels_content = build_project_audacity_labels_content(
            db,
            audiobook_project_id=audiobook_project.id,
            chapters=chapters,
        )
        lof_content = build_project_audacity_lof_content(
            entry.arcname for entry in track_entries
        )

        with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.lof", lof_content)
            archive.writestr("labels.txt", labels_content)
            for entry in track_entries:
                archive.write(entry.path, entry.arcname)

    file_size = output_file.stat().st_size if output_file.exists() else 0
    if file_size <= 0:
        raise AudiobookExportError("Audacity ZIP 输出文件为空", code="empty_audacity_output")

    label_count = len([line for line in labels_content.splitlines() if line.strip()])
    result = {
        "success": True,
        "cached": False,
        "output_path": _to_repo_relative_path(output_file),
        "file_size": file_size,
        "duration": round(sum(chapter.duration_seconds for chapter in chapters), 6),
        "chapter_count": len(chapters),
        "track_count": len(track_entries),
        "track_mode": _summarize_audacity_track_mode(track_entries),
        "label_count": label_count,
        "chapters": [asdict(chapter) for chapter in chapters],
        "files": ["project.lof", "labels.txt"] + [entry.arcname for entry in track_entries],
        "source_signature": source_signature,
    }
    _write_project_export_manifest(
        output_file,
        export_kind="audacity",
        source_signature=source_signature,
        result=result,
    )
    return result


def collect_project_audio_chapters(
    db: Session,
    *,
    audiobook_project_id: int,
) -> List[ProjectAudioChapter]:
    rows = (
        db.query(ChapterAudio, Chapter)
        .join(Chapter, Chapter.id == ChapterAudio.chapter_id)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.deleted_at.is_(None),
            Chapter.deleted_at.is_(None),
        )
        .order_by(Chapter.chapter_number.asc(), ChapterAudio.id.asc())
        .all()
    )

    chapters: List[ProjectAudioChapter] = []
    for chapter_audio, chapter in rows:
        audio_path = str(chapter_audio.audio_path or "").strip()
        if not audio_path:
            continue
        resolved_audio_path = resolve_existing_audio_path(audio_path)
        if resolved_audio_path is None:
            raise AudiobookExportError(
                f"章节音频文件不存在: chapter_id={chapter.id}, path={audio_path}",
                code="chapter_audio_missing",
            )

        duration_seconds = probe_audio_duration_seconds(resolved_audio_path)
        if duration_seconds <= 0:
            try:
                duration_seconds = float(chapter_audio.duration or 0.0)
            except Exception:
                duration_seconds = 0.0
        if duration_seconds <= 0:
            raise AudiobookExportError(
                f"无法获取章节音频时长: chapter_id={chapter.id}",
                code="chapter_duration_unavailable",
            )

        chapters.append(
            ProjectAudioChapter(
                chapter_id=int(chapter.id),
                chapter_number=int(chapter.chapter_number or 0),
                title=str(chapter.title or f"Chapter {chapter.chapter_number}"),
                audio_path=audio_path,
                resolved_audio_path=str(resolved_audio_path),
                duration_seconds=float(duration_seconds),
            )
        )

    return chapters


def build_chapter_markers(chapters: Iterable[ProjectAudioChapter]) -> List[ProjectAudioChapter]:
    marked: List[ProjectAudioChapter] = []
    cursor_ms = 0
    for chapter in chapters or []:
        duration_ms = max(1, int(round(float(chapter.duration_seconds) * 1000)))
        marked.append(
            ProjectAudioChapter(
                chapter_id=chapter.chapter_id,
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                audio_path=chapter.audio_path,
                resolved_audio_path=chapter.resolved_audio_path,
                duration_seconds=chapter.duration_seconds,
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
            )
        )
        cursor_ms += duration_ms
    return marked


def build_ffmpeg_concat_content(chapters: Iterable[ProjectAudioChapter]) -> str:
    lines = []
    for chapter in chapters or []:
        lines.append(f"file '{_escape_concat_path(chapter.resolved_audio_path)}'")
    return "\n".join(lines) + ("\n" if lines else "")


def build_project_m4b_ffmpeg_command(
    *,
    ffmpeg_path: str,
    concat_path: Path,
    metadata_path: Path,
    output_file: Path,
    bitrate: str = _DEFAULT_M4B_BITRATE,
    cover_path: Optional[Path] = None,
) -> List[str]:
    cmd = [
        ffmpeg_path,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-f",
        "ffmetadata",
        "-i",
        str(metadata_path),
    ]
    if cover_path:
        cmd.extend(["-i", str(cover_path)])

    cmd.extend(["-map", "0:a"])
    if cover_path:
        cmd.extend(["-map", "2:v"])

    cmd.extend(
        [
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
        ]
    )
    if cover_path:
        cmd.extend(["-c:v", "copy", "-disposition:v:0", "attached_pic"])

    cmd.extend(["-movflags", "+faststart", str(output_file)])
    return cmd


def build_project_audacity_lof_content(track_paths: Iterable[str]) -> str:
    lines = []
    for path_value in track_paths or []:
        path_text = str(path_value or "").replace("\\", "/").replace('"', '\\"').strip()
        if path_text:
            lines.append(f'file "{path_text}"')
    return "\n".join(lines) + ("\n" if lines else "")


def build_project_audacity_labels_content(
    db: Session,
    *,
    audiobook_project_id: int,
    chapters: Iterable[ProjectAudioChapter],
) -> str:
    chapter_list = list(chapters or [])
    if not chapter_list:
        return ""

    chapter_audio_by_id = {
        int(row.chapter_id): row
        for row in db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id.in_([chapter.chapter_id for chapter in chapter_list]),
            ChapterAudio.deleted_at.is_(None),
        )
        .all()
    }

    lines: List[str] = []
    for chapter in chapter_list:
        chapter_audio = chapter_audio_by_id.get(chapter.chapter_id)
        chapter_lines: List[str] = []
        if chapter_audio:
            chapter_lines = _build_segment_label_lines_for_chapter(
                db,
                audiobook_project_id=audiobook_project_id,
                chapter=chapter,
                chapter_audio=chapter_audio,
            )
        if not chapter_lines:
            chapter_lines = [
                _format_audacity_label_line(
                    chapter.start_ms / 1000.0,
                    chapter.end_ms / 1000.0,
                    f"{chapter.chapter_number}. {chapter.title}".strip(),
                )
            ]
        lines.extend(chapter_lines)

    return "\n".join(lines) + ("\n" if lines else "")


def build_project_export_source_signature(
    chapters: Iterable[ProjectAudioChapter],
    *,
    export_kind: str,
    version: int,
    metadata: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    payload = {
        "export_kind": str(export_kind or ""),
        "version": int(version),
        "chapters": [_build_chapter_source_payload(chapter) for chapter in chapters or []],
        "metadata": _normalize_jsonable(metadata or {}),
        "extra": _normalize_jsonable(extra or {}),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_chapter_audio_map(
    db: Session,
    *,
    audiobook_project_id: int,
    chapters: Iterable[ProjectAudioChapter],
) -> Dict[int, ChapterAudio]:
    chapter_ids = [chapter.chapter_id for chapter in chapters or []]
    if not chapter_ids:
        return {}
    return {
        int(row.chapter_id): row
        for row in db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id.in_(chapter_ids),
            ChapterAudio.deleted_at.is_(None),
        )
        .all()
    }


def _build_chapter_source_payload(chapter: ProjectAudioChapter) -> Dict[str, Any]:
    file_path = Path(chapter.resolved_audio_path)
    try:
        stat = file_path.stat()
        file_size = int(stat.st_size)
        mtime_ns = int(stat.st_mtime_ns)
    except Exception:
        file_size = None
        mtime_ns = None

    return {
        "chapter_id": int(chapter.chapter_id),
        "chapter_number": int(chapter.chapter_number),
        "title": chapter.title,
        "audio_path": chapter.audio_path,
        "resolved_audio_path": str(file_path.resolve(strict=False)),
        "duration_seconds": round(float(chapter.duration_seconds or 0.0), 6),
        "file_size": file_size,
        "mtime_ns": mtime_ns,
    }


def _build_audacity_export_dependency_payload(
    db: Session,
    *,
    audiobook_project_id: int,
    chapters: Iterable[ProjectAudioChapter],
    chapter_audio_by_id: Dict[int, ChapterAudio],
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for chapter in chapters or []:
        chapter_audio = chapter_audio_by_id.get(chapter.chapter_id)
        if not chapter_audio:
            items.append({"chapter_id": chapter.chapter_id, "chapter_audio_missing": True})
            continue

        subtitle_path = str(getattr(chapter_audio, "subtitle_path", "") or "").strip()
        label_path = _resolve_existing_label_path(subtitle_path) if subtitle_path else None
        checkpoint_json = _load_latest_checkpoint_json(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter.chapter_id,
        )

        items.append(
            {
                "chapter_id": int(chapter.chapter_id),
                "script_json": getattr(chapter_audio, "script_json", None),
                "subtitle_path": subtitle_path,
                "label_file": _build_file_dependency_payload(label_path),
                "segment_timings": checkpoint_json.get("segment_timings")
                if isinstance(checkpoint_json.get("segment_timings"), list)
                else [],
            }
        )

    return {"chapters": items}


def _build_audacity_track_exports(
    db: Session,
    *,
    audiobook_project_id: int,
    chapters: List[ProjectAudioChapter],
    chapter_audio_by_id: Dict[int, ChapterAudio],
    tracks_dir: Path,
    timeout_seconds: int,
) -> List[AudacityTrackExport]:
    speaker_tracks, covered_chapter_ids = _build_audacity_speaker_track_exports(
        db,
        audiobook_project_id=audiobook_project_id,
        chapters=chapters,
        chapter_audio_by_id=chapter_audio_by_id,
        tracks_dir=tracks_dir,
    )
    if speaker_tracks:
        fallback_chapters = [
            chapter
            for chapter in chapters
            if chapter.chapter_id not in covered_chapter_ids
        ]
        return speaker_tracks + _build_audacity_chapter_track_exports(
            fallback_chapters,
            tracks_dir=tracks_dir,
            timeout_seconds=timeout_seconds,
        )

    return _build_audacity_chapter_track_exports(
        chapters,
        tracks_dir=tracks_dir,
        timeout_seconds=timeout_seconds,
    )


def _build_audacity_speaker_track_exports(
    db: Session,
    *,
    audiobook_project_id: int,
    chapters: List[ProjectAudioChapter],
    chapter_audio_by_id: Dict[int, ChapterAudio],
    tracks_dir: Path,
) -> tuple[List[AudacityTrackExport], Set[int]]:
    try:
        from pydub import AudioSegment
    except Exception:
        return [], set()

    speaker_segments: Dict[str, List[tuple[int, Any]]] = {}
    speaker_order: List[str] = []
    used_filenames: Set[str] = set()
    covered_chapter_ids: Set[int] = set()
    total_duration_ms = max((chapter.end_ms for chapter in chapters), default=0)

    for chapter in chapters:
        chapter_audio = chapter_audio_by_id.get(chapter.chapter_id)
        if not chapter_audio:
            continue
        label_entries = _build_chapter_label_entries(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter=chapter,
            chapter_audio=chapter_audio,
        )
        if not label_entries:
            continue

        try:
            chapter_audio_segment = AudioSegment.from_file(chapter.resolved_audio_path)
        except Exception:
            continue

        chapter_had_audio = False
        for entry in label_entries:
            local_start_ms = max(0, int(round(float(entry.get("start_time") or 0.0) * 1000)))
            local_end_ms = max(local_start_ms + 1, int(round(float(entry.get("end_time") or 0.0) * 1000)))
            local_start_ms = min(local_start_ms, len(chapter_audio_segment))
            local_end_ms = min(local_end_ms, len(chapter_audio_segment))
            if local_end_ms <= local_start_ms:
                continue

            speaker = _normalize_audacity_speaker_name(entry.get("speaker"))
            if speaker not in speaker_segments:
                speaker_segments[speaker] = []
                speaker_order.append(speaker)

            clip = chapter_audio_segment[local_start_ms:local_end_ms]
            speaker_segments[speaker].append((chapter.start_ms + local_start_ms, clip))
            chapter_had_audio = True

        if chapter_had_audio:
            covered_chapter_ids.add(chapter.chapter_id)

    track_exports: List[AudacityTrackExport] = []
    for speaker in speaker_order:
        segments = sorted(speaker_segments.get(speaker) or [], key=lambda item: item[0])
        if not segments:
            continue

        track = AudioSegment.silent(duration=0)
        for start_ms, clip in segments:
            start_ms = max(0, int(start_ms))
            required_length = start_ms + len(clip)
            if len(track) < required_length:
                track += AudioSegment.silent(duration=required_length - len(track))
            track = track.overlay(clip, position=start_ms)

        if total_duration_ms > len(track):
            track += AudioSegment.silent(duration=total_duration_ms - len(track))

        filename = _ensure_unique_filename(
            f"speaker_{_sanitize_filename(speaker, fallback='speaker')}.wav",
            used_filenames,
        )
        track_path = tracks_dir / filename
        track.export(track_path, format="wav")
        if not track_path.exists() or track_path.stat().st_size <= 0:
            continue

        track_exports.append(
            AudacityTrackExport(
                path=str(track_path),
                arcname=f"tracks/{filename}",
                kind="speaker",
                name=speaker,
            )
        )

    if not track_exports:
        return [], set()
    return track_exports, covered_chapter_ids


def _build_audacity_chapter_track_exports(
    chapters: Iterable[ProjectAudioChapter],
    *,
    tracks_dir: Path,
    timeout_seconds: int,
) -> List[AudacityTrackExport]:
    track_entries: List[AudacityTrackExport] = []
    used_filenames: Set[str] = set()
    for position, chapter in enumerate(chapters or [], start=1):
        track_filename = _ensure_unique_filename(
            _build_audacity_track_filename(chapter, position),
            used_filenames,
        )
        track_file = tracks_dir / track_filename
        _write_audacity_wav_track(
            Path(chapter.resolved_audio_path),
            track_file,
            timeout_seconds=timeout_seconds,
        )
        track_entries.append(
            AudacityTrackExport(
                path=str(track_file),
                arcname=f"tracks/{track_filename}",
                kind="chapter",
                name=chapter.title,
            )
        )
    return track_entries


def _summarize_audacity_track_mode(track_entries: Iterable[AudacityTrackExport]) -> str:
    kinds = {entry.kind for entry in track_entries or []}
    if "speaker" in kinds and "chapter" in kinds:
        return "mixed"
    if "speaker" in kinds:
        return "speaker"
    return "chapter"


def build_ffmetadata_content(
    chapters: Iterable[ProjectAudioChapter],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    metadata = metadata or {}
    lines = [";FFMETADATA1"]
    lines.append(f"title={_escape_ffmetadata(metadata.get('title') or 'Audiobook')}")
    lines.append(f"artist={_escape_ffmetadata(metadata.get('author') or '')}")
    lines.append(f"album_artist={_escape_ffmetadata(metadata.get('narrator') or '')}")
    lines.append(f"date={_escape_ffmetadata(metadata.get('year') or '')}")
    lines.append(f"comment={_escape_ffmetadata(metadata.get('description') or '')}")
    lines.append("genre=Audiobook")
    lines.append("")

    for chapter in chapters or []:
        title = f"{chapter.chapter_number}. {chapter.title}".strip()
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={int(chapter.start_ms)}")
        lines.append(f"END={int(chapter.end_ms)}")
        lines.append(f"title={_escape_ffmetadata(title)}")
        lines.append("")

    return "\n".join(lines)


def probe_audio_duration_seconds(path: Path) -> float:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                return max(0.0, float(str(result.stdout or "").strip() or 0.0))
        except Exception:
            pass

    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(str(path))
        return max(0.0, len(audio) / 1000.0)
    except Exception:
        return 0.0


def probe_m4b_output(path: Path, *, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Probe a generated M4B with ffprobe and return normalized metadata."""
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return {
            "available": False,
            "skipped": True,
            "reason": "ffprobe_unavailable",
        }

    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_chapters",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudiobookExportError(
            "ffprobe 校验 M4B 超时",
            code="m4b_probe_timeout",
        ) from exc
    except Exception as exc:
        raise AudiobookExportError(
            f"ffprobe 校验 M4B 失败: {exc}",
            code="m4b_probe_failed",
        ) from exc

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:].strip()
        raise AudiobookExportError(
            f"ffprobe 无法读取 M4B 输出: {stderr_tail or result.returncode}",
            code="m4b_probe_failed",
        )

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AudiobookExportError(
            "ffprobe 返回的 M4B 元数据不是有效 JSON",
            code="m4b_probe_invalid_json",
        ) from exc

    format_payload = payload.get("format") if isinstance(payload, dict) else {}
    chapter_payloads = payload.get("chapters") if isinstance(payload, dict) else []
    if not isinstance(format_payload, dict):
        format_payload = {}
    if not isinstance(chapter_payloads, list):
        chapter_payloads = []

    duration = _coerce_float(format_payload.get("duration"))
    chapters = [_normalize_probe_chapter(chapter) for chapter in chapter_payloads if isinstance(chapter, dict)]
    return {
        "available": True,
        "skipped": False,
        "format_name": str(format_payload.get("format_name") or ""),
        "duration_seconds": round(duration, 6) if duration is not None else None,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }


def validate_project_m4b_output(
    output_file: Path,
    *,
    expected_duration_seconds: float,
    expected_chapter_count: int,
    duration_tolerance_seconds: float = 2.0,
    duration_tolerance_ratio: float = 0.02,
) -> Dict[str, Any]:
    """Validate that ffmpeg actually wrote readable audio and chapter metadata."""
    probe = probe_m4b_output(output_file)
    if probe.get("skipped"):
        return {
            "passed": True,
            "skipped": True,
            "reason": probe.get("reason") or "probe_skipped",
            "expected_duration_seconds": round(max(0.0, float(expected_duration_seconds or 0.0)), 6),
            "expected_chapter_count": int(expected_chapter_count or 0),
            "probe": probe,
        }

    expected_duration = max(0.0, float(expected_duration_seconds or 0.0))
    actual_duration = _coerce_float(probe.get("duration_seconds")) or 0.0
    expected_chapters = max(0, int(expected_chapter_count or 0))
    actual_chapters = max(0, int(probe.get("chapter_count") or 0))
    tolerance = max(
        float(duration_tolerance_seconds),
        expected_duration * float(duration_tolerance_ratio),
    )
    duration_delta = abs(actual_duration - expected_duration)

    issues: List[Dict[str, Any]] = []
    if actual_duration <= 0:
        issues.append(
            {
                "code": "invalid_duration",
                "message": "M4B 输出时长无效",
                "actual_duration_seconds": actual_duration,
            }
        )
    elif expected_duration > 0 and duration_delta > tolerance:
        issues.append(
            {
                "code": "duration_mismatch",
                "message": "M4B 输出时长与源章节总时长偏差过大",
                "expected_duration_seconds": round(expected_duration, 6),
                "actual_duration_seconds": round(actual_duration, 6),
                "delta_seconds": round(duration_delta, 6),
                "tolerance_seconds": round(tolerance, 6),
            }
        )

    if actual_chapters != expected_chapters:
        issues.append(
            {
                "code": "chapter_count_mismatch",
                "message": "M4B 输出章节标记数量不一致",
                "expected_chapter_count": expected_chapters,
                "actual_chapter_count": actual_chapters,
            }
        )

    if issues:
        raise AudiobookExportError(
            "; ".join(issue["message"] for issue in issues),
            code="m4b_output_validation_failed",
        )

    return {
        "passed": True,
        "skipped": False,
        "expected_duration_seconds": round(expected_duration, 6),
        "actual_duration_seconds": round(actual_duration, 6),
        "duration_delta_seconds": round(duration_delta, 6),
        "duration_tolerance_seconds": round(tolerance, 6),
        "expected_chapter_count": expected_chapters,
        "actual_chapter_count": actual_chapters,
        "probe": probe,
    }


def _normalize_probe_chapter(chapter: Dict[str, Any]) -> Dict[str, Any]:
    tags = chapter.get("tags") if isinstance(chapter.get("tags"), dict) else {}
    start_time = _coerce_float(chapter.get("start_time"))
    end_time = _coerce_float(chapter.get("end_time"))
    return {
        "id": int(chapter.get("id") or 0),
        "start_time": round(start_time, 6) if start_time is not None else None,
        "end_time": round(end_time, 6) if end_time is not None else None,
        "title": str(tags.get("title") or ""),
    }


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_existing_audio_path(path_value: str) -> Optional[Path]:
    raw = str(path_value or "").strip()
    if not raw:
        return None

    path = Path(raw)
    candidates = [path] if path.is_absolute() else [
        Path.cwd() / path,
        _REPO_ROOT / path,
        _REPO_ROOT / "backend" / path,
    ]

    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _get_project_source_cover_path(project: Project) -> Optional[str]:
    config = parse_project_audio_config(project.audio_config or "")
    for container_key in ("source_book", "audiobook_export"):
        container = config.get(container_key)
        if not isinstance(container, dict):
            continue
        cover_path = str(container.get("cover_path") or "").strip()
        if cover_path:
            return cover_path

    cover_path = str(config.get("cover_path") or "").strip()
    return cover_path or None


def _resolve_output_path(path_value: str) -> Path:
    path = Path(str(path_value or "").strip())
    if path.is_absolute():
        return path
    return (_REPO_ROOT / path).resolve(strict=False)


def _to_repo_relative_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(_REPO_ROOT.resolve(strict=False)).as_posix()
    except Exception:
        return path.as_posix()


def _unique_paths(paths: Iterable[Path]) -> List[Path]:
    unique: List[Path] = []
    seen: Set[str] = set()
    for path in paths or []:
        resolved = Path(path).resolve(strict=False)
        key = resolved.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _project_export_manifest_path(output_file: Path) -> Path:
    return output_file.with_name(f"{output_file.name}.json")


def _load_cached_project_export_result(
    output_file: Path,
    *,
    export_kind: str,
    source_signature: str,
) -> Optional[Dict[str, Any]]:
    if not output_file.exists() or output_file.stat().st_size <= 0:
        return None

    manifest_path = _project_export_manifest_path(output_file)
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if manifest.get("export_kind") != export_kind:
        return None
    if manifest.get("source_signature") != source_signature:
        return None

    result = manifest.get("result")
    if not isinstance(result, dict):
        return None

    cached_result = dict(result)
    cached_result["success"] = True
    cached_result["cached"] = True
    cached_result["file_size"] = output_file.stat().st_size
    cached_result["output_path"] = _to_repo_relative_path(output_file)
    cached_result["source_signature"] = source_signature
    return cached_result


def _write_project_export_manifest(
    output_file: Path,
    *,
    export_kind: str,
    source_signature: str,
    result: Dict[str, Any],
) -> None:
    manifest_path = _project_export_manifest_path(output_file)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "export_kind": export_kind,
        "source_signature": source_signature,
        "result": _normalize_jsonable(result),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _normalize_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _build_file_dependency_payload(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    try:
        stat = path.stat()
    except Exception:
        return {
            "path": path.as_posix(),
            "exists": False,
        }
    return {
        "path": path.as_posix(),
        "exists": True,
        "file_size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _escape_concat_path(path_value: str) -> str:
    return str(Path(path_value).resolve(strict=False)).replace("\\", "/").replace("'", "'\\''")


def _escape_ffmetadata(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace("=", "\\=")
    text = text.replace(";", "\\;")
    text = text.replace("#", "\\#")
    text = re.sub(r"[\r\n]+", " ", text)
    return text.strip()


def _build_audacity_track_filename(chapter: ProjectAudioChapter, position: int) -> str:
    chapter_number = chapter.chapter_number if chapter.chapter_number > 0 else position
    return build_safe_filename(
        chapter.title,
        ".wav",
        fallback=f"chapter_{chapter_number:03d}",
        prefix=f"chapter_{chapter_number:03d}",
    )


def _sanitize_filename(value: Any, *, fallback: str) -> str:
    return sanitize_filename_component(value, fallback=fallback, max_bytes=120)


def _ensure_unique_filename(filename: str, used_filenames: Set[str]) -> str:
    return ensure_unique_filename(filename, used_filenames)


def _normalize_audacity_speaker_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "Narrator"
    return text[:80]


def _extract_audacity_label_speaker(label: Any) -> tuple[Optional[str], str]:
    text = str(label or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    match = re.match(r"^\[([^\]]+)\]\s*(.*)$", text)
    if not match:
        return None, text
    speaker = match.group(1).strip() or None
    body = match.group(2).strip()
    return speaker, text if not body else text


def _write_audacity_wav_track(
    source_file: Path,
    output_file: Path,
    *,
    timeout_seconds: int,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if source_file.suffix.lower() == ".wav":
        shutil.copyfile(source_file, output_file)
    else:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise AudiobookExportError(
                "ffmpeg 不可用，无法将章节音频转换为 Audacity WAV",
                code="ffmpeg_unavailable",
            )

        result = subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(source_file),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-800:].strip()
            raise AudiobookExportError(
                f"ffmpeg 生成 Audacity WAV 失败: {stderr_tail or result.returncode}",
                code="ffmpeg_failed",
            )

    if not output_file.exists() or output_file.stat().st_size <= 0:
        raise AudiobookExportError("Audacity WAV 输出文件为空", code="empty_audacity_track")


def _build_segment_label_lines_for_chapter(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter: ProjectAudioChapter,
    chapter_audio: ChapterAudio,
) -> List[str]:
    offset_seconds = chapter.start_ms / 1000.0
    entries = _build_chapter_label_entries(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter=chapter,
        chapter_audio=chapter_audio,
    )
    return [
        _format_audacity_label_line(
            offset_seconds + max(0.0, float(entry.get("start_time") or 0.0)),
            offset_seconds + max(0.0, float(entry.get("end_time") or 0.0)),
            entry.get("label"),
        )
        for entry in entries
    ]

def _build_chapter_label_entries(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter: ProjectAudioChapter,
    chapter_audio: ChapterAudio,
) -> List[Dict[str, Any]]:
    label_entries = _load_existing_chapter_label_entries(chapter_audio)
    if label_entries:
        return label_entries

    script_segments = _parse_script_segments(getattr(chapter_audio, "script_json", None))
    checkpoint_json = _load_latest_checkpoint_json(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter.chapter_id,
    )
    segment_timings = checkpoint_json.get("segment_timings")
    if not script_segments or not isinstance(segment_timings, list) or not segment_timings:
        return []

    entries = SubtitleGenerator.from_segment_timings(script_segments, segment_timings)
    label_entries: List[Dict[str, Any]] = []
    for entry in entries:
        label = str(entry.text or "").strip()
        if entry.speaker:
            label = f"[{entry.speaker}] {label}"
        label_entries.append(
            {
                "start_time": max(0.0, float(entry.start_time or 0.0)),
                "end_time": max(0.0, float(entry.end_time or 0.0)),
                "speaker": entry.speaker,
                "label": label,
            }
        )
    return label_entries


def _load_existing_chapter_label_entries(chapter_audio: ChapterAudio) -> List[Dict[str, Any]]:
    subtitle_path = str(getattr(chapter_audio, "subtitle_path", "") or "").strip()
    if not subtitle_path:
        return []

    resolved_label_file = _resolve_existing_label_path(subtitle_path)
    if not resolved_label_file:
        return []

    entries: List[Dict[str, Any]] = []
    for raw_line in resolved_label_file.read_text(encoding="utf-8").splitlines():
        parts = raw_line.split("\t", 2)
        if len(parts) < 3:
            continue
        try:
            start = max(0.0, float(parts[0]))
            end = max(0.0, float(parts[1]))
        except Exception:
            continue
        if end <= start:
            continue
        speaker, label = _extract_audacity_label_speaker(parts[2])
        entries.append(
            {
                "start_time": start,
                "end_time": end,
                "speaker": speaker,
                "label": label,
            }
        )
    return entries


def _resolve_existing_label_path(subtitle_path: str) -> Optional[Path]:
    label_file = Path(str(subtitle_path or "").strip()).with_suffix(".labels.txt")
    candidates = [label_file] if label_file.is_absolute() else [
        Path.cwd() / label_file,
        _REPO_ROOT / label_file,
        _REPO_ROOT / "backend" / label_file,
    ]

    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _parse_script_segments(raw_value: Any) -> List[Dict[str, Any]]:
    if raw_value is None:
        return []
    payload = raw_value
    if isinstance(raw_value, str):
        try:
            payload = json.loads(raw_value)
        except Exception:
            return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("segments", "script_segments", "script"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = value.get("segments")
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def _load_latest_checkpoint_json(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> Dict[str, Any]:
    run = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
        )
        .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
        .first()
    )
    checkpoint_json = getattr(run, "checkpoint_json", None)
    return dict(checkpoint_json or {}) if isinstance(checkpoint_json, dict) else {}


def _format_audacity_label_line(start_seconds: float, end_seconds: float, label: Any) -> str:
    start = max(0.0, float(start_seconds or 0.0))
    end = max(start + 0.001, float(end_seconds or 0.0))
    text = str(label or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    return f"{start:.6f}\t{end:.6f}\t{text}"


__all__ = [
    "AudiobookExportError",
    "AudacityTrackExport",
    "ProjectAudioChapter",
    "build_chapter_markers",
    "collect_project_export_output_files",
    "build_ffmetadata_content",
    "build_ffmpeg_concat_content",
    "build_project_audacity_export",
    "build_project_audacity_labels_content",
    "build_project_audacity_lof_content",
    "build_project_audacity_output_path",
    "build_project_export_source_signature",
    "build_project_m4b_ffmpeg_command",
    "build_project_m4b_export",
    "build_project_m4b_output_path",
    "collect_project_audio_chapters",
    "probe_audio_duration_seconds",
    "probe_m4b_output",
    "resolve_project_audacity_output_file",
    "resolve_project_m4b_output_file",
    "resolve_existing_audio_path",
    "validate_project_m4b_output",
]
