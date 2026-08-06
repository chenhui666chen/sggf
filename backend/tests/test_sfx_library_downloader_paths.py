"""Regression tests for shared audio-library paths."""
import importlib
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def test_sfx_downloader_uses_backend_audio_library_dir_by_default(monkeypatch):
    """The importer must write to the same library root used by browser routes."""
    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_DIR", raising=False)

    paths_module = importlib.import_module("app.services.audiobook.audio_library_paths")
    downloader_module = importlib.import_module("app.services.audiobook.sfx_library_downloader")
    downloader_module = importlib.reload(downloader_module)

    expected_dir = paths_module.get_audio_library_dir()
    assert downloader_module.AUDIO_LIBRARY_DIR == expected_dir
    assert downloader_module.SOUND_EFFECTS_DIR == expected_dir / "sound_effects"

    downloader = downloader_module.SfxLibraryDownloader()
    assert downloader.index_path == expected_dir / "sound_effects_index.json"
    assert downloader.output_dir == expected_dir / "sound_effects"


def test_audio_library_path_resolver_rejects_paths_outside_library(tmp_path):
    paths_module = importlib.import_module("app.services.audiobook.audio_library_paths")
    library_root = tmp_path / "audio_library"
    inside = library_root / "music" / "inside.mp3"
    outside = tmp_path / "outside.mp3"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"inside")
    outside.write_bytes(b"outside")

    assert (
        paths_module.resolve_audio_library_file_path("music/inside.mp3", library_root)
        == inside.resolve()
    )
    assert paths_module.resolve_audio_library_file_path(inside, library_root) == inside.resolve()
    assert paths_module.resolve_audio_library_file_path(outside, library_root) is None
    assert (
        paths_module.resolve_audio_library_file_path("../outside.mp3", library_root)
        is None
    )
