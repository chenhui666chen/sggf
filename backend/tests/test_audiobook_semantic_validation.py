import logging
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment
from app.services.audiobook.script_adapter_pkg._merge import MergeMixin


@dataclass
class DummyStrategy:
    min_segment_length: int = 15


class DummyMergeAgent(MergeMixin):
    def __init__(self) -> None:
        self.strategy = DummyStrategy()


def _narration(text: str, emotion: str = "tense") -> ScriptSegment:
    return ScriptSegment(
        type="narration",
        text=text,
        speaker="旁白",
        emotion=emotion,
        performance_notes="短句停顿，制造悬念",
    )


def test_semantic_validation_excludes_natural_short_narration_beats(caplog):
    agent = DummyMergeAgent()
    segments = [
        _narration("第001章救他的命，要我的命"),
        _narration("是右手掌心那道黑色裂隙。"),
        _narration("它在呼吸。"),
        _narration("陆衍不信邪。"),
        _narration("现在，就是唯一的机会。"),
    ]

    with caplog.at_level(logging.INFO, logger="app.services.audiobook.script_adapter_pkg._merge"):
        result = agent._validate_semantic_integrity(segments)

    assert result == segments
    assert "自然短片段" in caplog.text
    assert "语义完整性验证失败" not in caplog.text


def test_semantic_validation_still_warns_for_fragmented_short_narration(caplog):
    agent = DummyMergeAgent()
    segments = [
        _narration("就一晚"),
    ]

    with caplog.at_level(logging.WARNING, logger="app.services.audiobook.script_adapter_pkg._merge"):
        result = agent._validate_semantic_integrity(segments)

    assert result == segments
    assert "语义完整性验证失败" in caplog.text
    assert "就一晚" in caplog.text
