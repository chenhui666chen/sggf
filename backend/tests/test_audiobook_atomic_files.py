from pathlib import Path
import sys


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
