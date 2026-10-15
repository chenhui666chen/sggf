import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_video_release_migrations_preserve_existing_chapters_and_apply_finite_quota(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'release-migrations.db'}")
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE chapters (id INTEGER PRIMARY KEY, project_id INTEGER, "
            "chapter_number INTEGER, deleted_at TIMESTAMP)"))
        connection.execute(text("INSERT INTO chapters VALUES (1, 1, 1, NULL)"))
        context = MigrationContext.configure(connection)
        for name in ("add_chapter_project_number_unique_index", "add_video_api_applications", "add_video_api_trial_quota"):
            spec = importlib.util.spec_from_file_location(name, versions / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with Operations.context(context):
                module.upgrade()
        columns = {item["name"]: item for item in inspect(connection).get_columns("video_api_applications")}
        assert str(columns["lifetime_task_limit"]["default"]).strip("'") == "100"
        assert connection.execute(text("SELECT count(*) FROM chapters")).scalar() == 1
    engine.dispose()
