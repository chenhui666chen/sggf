from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_write_bytes_atomic_writes_and_replaces_existing_file(tmp_path: Path):
    from app.services.audiobook.atomic_files import write_bytes_atomic

    output_path = tmp_path / "chapter.mp3"
    output_path.write_bytes(b"old")

    result = write_bytes_atomic(output_path, b"new-audio")

    assert result == output_path
    assert output_path.read_bytes() == b"new-audio"
    assert not list(tmp_path.glob("*.part"))


def test_write_bytes_atomic_creates_parent_directory(tmp_path: Path):
    from app.services.audiobook.atomic_files import write_bytes_atomic

    output_path = tmp_path / "nested" / "chapter.wav"

    write_bytes_atomic(output_path, b"wav")

    assert output_path.read_bytes() == b"wav"


def test_write_bytes_atomic_logs_temp_cleanup_failure(monkeypatch, tmp_path: Path, caplog):
    from app.services.audiobook import atomic_files

    output_path = tmp_path / "chapter.mp3"
    output_path.write_bytes(b"old")
    original_unlink = atomic_files.Path.unlink

    def fail_replace(_src, _dst):
        raise OSError("replace failed")

    def fail_part_unlink(self, *args, **kwargs):
        if str(self).endswith(".part"):
            raise RuntimeError("cleanup failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)
    monkeypatch.setattr(atomic_files.Path, "unlink", fail_part_unlink)

    with caplog.at_level("DEBUG", logger="app.services.audiobook.atomic_files"):
        with pytest.raises(OSError, match="replace failed"):
            atomic_files.write_bytes_atomic(output_path, b"new-audio")

    assert output_path.read_bytes() == b"old"
    assert "清理原子写入临时文件失败，已忽略" in caplog.text
    assert "cleanup failed" in caplog.text
