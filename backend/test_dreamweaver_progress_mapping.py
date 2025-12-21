from __future__ import annotations

from pipeline.state_machine import State, progress_percent, stage_label


def test_progress_percent_mapping_is_stable():
    assert progress_percent(State.INIT) == 0
    assert progress_percent(State.SCRIPT) == 10
    assert progress_percent(State.VIDEO) == 75
    assert progress_percent(State.DONE) == 100


def test_stage_label_mapping_is_stable():
    assert stage_label(State.INIT) == "init"
    assert stage_label(State.KEYFRAMES) == "keyframes"
    assert stage_label(State.REWORK) == "rework"
