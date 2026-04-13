from pathlib import Path

from app.services.agents import config as agent_config


def test_resolve_backend_storage_path_uses_backend_root_for_relative_path():
    resolved = Path(agent_config._resolve_backend_storage_path("./chroma_db"))
    expected = Path(agent_config.__file__).resolve().parents[3] / "chroma_db"

    assert resolved == expected.resolve()


def test_resolve_backend_storage_path_keeps_absolute_path():
    absolute = Path("C:/tmp/chroma_db_absolute")
    resolved = Path(agent_config._resolve_backend_storage_path(str(absolute)))

    assert resolved == absolute
