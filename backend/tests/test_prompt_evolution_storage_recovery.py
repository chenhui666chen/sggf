import json

import pytest

from app.services.prompt_evolution.models import EvolutionHistory
from app.services.prompt_evolution.storage import EvolutionStorage


def _history(evolution_id: str) -> EvolutionHistory:
    return EvolutionHistory(
        evolution_id=evolution_id,
        target_score=25,
        max_iterations=6,
        genre="玄幻",
    )


def test_history_recovers_from_last_valid_backup(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    storage.save_evolution_history(_history("first"))
    storage.save_evolution_history(_history("second"))

    storage.history_file.write_text("{broken", encoding="utf-8")

    assert storage.load_evolution_history("first") is not None
    assert storage.load_evolution_history("second") is None


def test_corrupt_history_without_backup_raises_instead_of_becoming_empty(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    storage.history_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        storage.list_evolution_histories()


def test_core_prompt_files_create_last_valid_backups(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    storage.best_prompts_file.write_text("[]", encoding="utf-8")
    storage.approved_prompts_file.write_text(
        '[{"version_id": "existing"}]', encoding="utf-8"
    )

    storage.save_best_prompts([])
    assert storage.remove_approved_prompt("existing") is True

    assert storage.best_prompts_file.with_suffix(".json.bak").exists()
    assert storage.approved_prompts_file.with_suffix(".json.bak").exists()
