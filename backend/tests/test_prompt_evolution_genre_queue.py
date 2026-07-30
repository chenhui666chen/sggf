from types import SimpleNamespace

import pytest

from app.api.v1 import prompt_evolution
from app.services.prompt_evolution.models import EvolutionHistory
from app.services.prompt_evolution.storage import EvolutionStorage


def test_resolve_all_genres_uses_fixed_business_order():
    assert prompt_evolution.resolve_evolution_genres(True, "悬疑") == [
        "玄幻",
        "都市",
        "言情",
        "悬疑",
        "科幻",
        "历史",
        "武侠",
    ]


def test_resolve_single_genre_keeps_backward_compatibility():
    assert prompt_evolution.resolve_evolution_genres(False, "都市") == ["都市"]
    assert prompt_evolution.resolve_evolution_genres(False, None) == [None]


def test_evolution_history_persists_genre(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    history = EvolutionHistory(genre="玄幻")

    storage.save_evolution_history(history)

    assert storage.load_evolution_history(history.evolution_id).genre == "玄幻"
    assert storage.list_evolution_histories()[0]["genre"] == "玄幻"


@pytest.mark.asyncio
async def test_genre_queue_runs_independent_engines_and_continues_after_failure(monkeypatch):
    created_genres = []

    class FakeEngine:
        def __init__(self, config, genre=None):
            created_genres.append(genre)
            self.genre = genre
            self.history = SimpleNamespace(
                evolution_id=f"evolution-{genre}",
                status="running",
            )

        async def run_evolution(self):
            if self.genre == "都市":
                self.history.status = "failed"
                raise RuntimeError("provider unavailable")
            self.history.status = "completed"
            return self.history

    monkeypatch.setattr(prompt_evolution, "PromptEvolutionEngine", FakeEngine)
    prompt_evolution._reset_genre_queue_status(["玄幻", "都市", "言情"])

    result = await prompt_evolution._run_genre_evolution_queue(
        ["玄幻", "都市", "言情"],
        SimpleNamespace(),
    )

    assert created_genres == ["玄幻", "都市", "言情"]
    assert result == {
        "completed_genres": ["玄幻", "言情"],
        "failed_genres": ["都市"],
    }
    assert prompt_evolution._genre_queue_status["active"] is False
    assert prompt_evolution._genre_queue_status["current_genre"] is None
    assert prompt_evolution._genre_queue_status["current_index"] == 3
