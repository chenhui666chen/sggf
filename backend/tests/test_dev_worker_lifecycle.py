from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_dev_launcher_replaces_stale_workers_and_uses_unique_node_names():
    source = (ROOT_DIR / "dev.bat").read_text(encoding="utf-8")

    shutdown_index = source.index("control shutdown")
    audiobook_worker_index = source.index("-Q audiobook")
    dreamweaver_worker_index = source.index("-Q dreamweaver")

    assert shutdown_index < audiobook_worker_index
    assert shutdown_index < dreamweaver_worker_index
    assert "-Q audiobook -n audiobook@%%h" in source
    assert "-Q dreamweaver -n dreamweaver@%%h" in source
    assert "Celery workers do not auto-reload" in source
