from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def test_load_project_env_fills_empty_process_value_from_backend_env(tmp_path, monkeypatch):
    from app.core import env_loader

    backend_env = tmp_path / "backend.env"
    root_env = tmp_path / "root.env"
    backend_env.write_text("OSS_BUCKET=backend-bucket\n", encoding="utf-8")
    root_env.write_text("OSS_BUCKET=root-bucket\n", encoding="utf-8")
    monkeypatch.setattr(
        env_loader,
        "get_env_file_candidates",
        lambda: (backend_env, root_env),
    )
    monkeypatch.setenv("OSS_BUCKET", "")

    loaded_files = env_loader.load_project_env(override=False)

    assert loaded_files == (backend_env, root_env)
    assert os.environ["OSS_BUCKET"] == "backend-bucket"


def test_load_project_env_preserves_non_empty_process_value(tmp_path, monkeypatch):
    from app.core import env_loader

    backend_env = tmp_path / "backend.env"
    backend_env.write_text("OSS_ENDPOINT=backend-endpoint\n", encoding="utf-8")
    monkeypatch.setattr(
        env_loader,
        "get_env_file_candidates",
        lambda: (backend_env,),
    )
    monkeypatch.setenv("OSS_ENDPOINT", "process-endpoint")

    env_loader.load_project_env(override=False)

    assert os.environ["OSS_ENDPOINT"] == "process-endpoint"
