from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment
from app.services.audiobook.script_adapter_pkg._transform import TransformMixin


def make_segment(text: str, **overrides) -> ScriptSegment:
    data = {
        "type": "narration",
        "text": text,
        "speaker": "旁白",
        "emotion": "tense",
    }
    data.update(overrides)
    return ScriptSegment(**data)


def test_fidelity_audit_reports_missing_source_quotes_and_unsupported_weapon():
    from app.services.audiobook.script_adapter_pkg._fidelity import audit_script_fidelity

    source_text = "守卫狞笑着一掌拍向后心。灰袍老者低声道：“小道友……可否借一步说话？”"
    segments = [
        make_segment("守卫甩出长鞭，抽向陆衍面门。"),
        make_segment("一个药奴，也敢逃？", type="dialogue", speaker="守卫"),
    ]

    report = audit_script_fidelity(source_text, segments)

    assert report["has_issues"] is True
    assert "小道友可否借一步说话" in report["missing_source_quotes"]
    assert report["unsupported_terms"] == [{"term": "鞭", "generated_variants": ["长鞭"]}]
    assert report["unsupported_dialogue"] == ["一个药奴，也敢逃？"]


def test_fidelity_audit_accepts_dialogue_and_terms_present_in_source():
    from app.services.audiobook.script_adapter_pkg._fidelity import audit_script_fidelity

    source_text = "护卫队长刀抵他咽喉：“治不好，按私藏异化者论处——斩立决。”"
    segments = [
        make_segment("护卫队长刀抵住陆衍咽喉。"),
        make_segment("治不好，按私藏异化者论处——斩立决。", type="dialogue", speaker="护卫队长"),
    ]

    report = audit_script_fidelity(source_text, segments)

    assert report["has_issues"] is False
    assert report["missing_source_quotes"] == []
    assert report["unsupported_terms"] == []
    assert report["unsupported_dialogue"] == []


class DummyTransformForFidelity(TransformMixin):
    def __init__(self, segments):
        self._segments = segments
        self.strategy = None
        self.last_script_fidelity_report = None

    async def _transform_paragraph(self, *args, **kwargs):
        return self._segments


@pytest.mark.asyncio
async def test_transform_to_script_records_fidelity_report_after_generation():
    agent = DummyTransformForFidelity(
        [
            make_segment("守卫甩出长鞭，抽向陆衍面门。"),
            make_segment("一个药奴，也敢逃？", type="dialogue", speaker="守卫"),
        ]
    )

    await agent._transform_to_script(
        content="守卫狞笑着一掌拍向他后心。",
        character_list=["陆衍", "守卫"],
        analysis={},
    )

    assert agent.last_script_fidelity_report["has_issues"] is True
    assert agent.last_script_fidelity_report["unsupported_dialogue"] == ["一个药奴，也敢逃？"]
