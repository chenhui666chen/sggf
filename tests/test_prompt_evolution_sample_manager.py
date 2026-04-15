from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"

for candidate in (str(ROOT_DIR), str(BACKEND_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from backend.app.services.prompt_evolution.test_samples import TestSampleManager as SampleManager


def test_get_samples_returns_requested_amount_when_available() -> None:
    manager = SampleManager()

    samples = manager.get_samples(3)

    assert len(samples) == 3
    assert all(sample.sample_id for sample in samples)


def test_get_samples_caps_result_to_available_sample_count() -> None:
    manager = SampleManager()

    samples = manager.get_samples(manager.get_sample_count() + 10)

    assert len(samples) == manager.get_sample_count()
