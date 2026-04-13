import os
import sys

import pytest


ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

for path in (ROOT_DIR, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


from app.services.book_parser.content_analyzer import AnalysisResult, AnalysisType, ContentAnalyzer
from app.services.book_parser.chapter_splitter import ChapterInfo, ChapterType


def _make_chapters(count: int) -> list[ChapterInfo]:
    return [
        ChapterInfo(
            number=index,
            title=f"第{index}章",
            content=f"章节{index}内容",
            word_count=1000,
            chapter_type=ChapterType.NORMAL,
        )
        for index in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_analyze_all_defaults_include_concepts_and_short_books_get_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = object.__new__(ContentAnalyzer)
    captured: dict[str, object] = {}

    async def fake_extract_all_chapter_summaries(chapters, on_progress=None):
        captured["extract_count"] = len(chapters)
        return [
            {
                "chapter_number": chapter.number,
                "title": chapter.title,
                "summary": f"{chapter.title}摘要",
                "key_events": [],
            }
            for chapter in chapters
        ]

    async def fake_sampling_analysis(
        chapters,
        analysis_types,
        on_progress=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ):
        captured["analysis_types"] = list(analysis_types)
        captured["progress_range"] = (progress_start, progress_end)
        return []

    async def fail_two_stage(*args, **kwargs):
        raise AssertionError("短篇分析不应进入两阶段分支")

    monkeypatch.setattr(analyzer, "_extract_all_chapter_summaries", fake_extract_all_chapter_summaries)
    monkeypatch.setattr(analyzer, "_sampling_analysis", fake_sampling_analysis)
    monkeypatch.setattr(analyzer, "_two_stage_analysis", fail_two_stage)

    results, chapter_summaries = await ContentAnalyzer.analyze_all(
        analyzer,
        chapters=_make_chapters(3),
        analysis_types=None,
        use_two_stage=True,
    )

    assert results == []
    assert len(chapter_summaries) == 3
    assert captured["extract_count"] == 3
    assert AnalysisType.CONCEPTS in captured["analysis_types"]
    assert captured["progress_range"] == (50, 100)


@pytest.mark.asyncio
async def test_analyze_by_type_supports_concepts(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = object.__new__(ContentAnalyzer)
    expected = AnalysisResult(
        analysis_type=AnalysisType.CONCEPTS,
        content={"terms": [{"term": "灵纹", "definition": "用于标记线索的特殊纹路"}]},
        confidence=0.8,
        chapter_range=(1, 2),
        model_used="test-model",
    )

    async def fake_analyze_concepts(chapters):
        return expected

    monkeypatch.setattr(analyzer, "analyze_concepts", fake_analyze_concepts)

    result = await ContentAnalyzer._analyze_by_type(
        analyzer,
        chapters=_make_chapters(2),
        analysis_type=AnalysisType.CONCEPTS,
    )

    assert result is expected


def test_build_analysis_result_marks_parse_error_as_low_confidence() -> None:
    analyzer = object.__new__(ContentAnalyzer)

    result = ContentAnalyzer._build_analysis_result(
        analyzer,
        analysis_type=AnalysisType.PLOT,
        content={
            "parse_error": True,
            "raw_response": "not-json-response",
        },
        confidence=0.88,
        chapter_range=(1, 3),
        model_used="test-model",
    )

    assert result.confidence == 0.15
    assert result.content["parse_error"] is True
    assert "raw_response" not in result.content
    assert result.extra_data is not None
    assert result.extra_data["parse_error"] is True
    assert "quality_warning" in result.extra_data
    assert result.extra_data["raw_response_preview"] == "not-json-response"


def test_normalize_character_entries_maps_new_semantic_aliases() -> None:
    parsed = {
        "characters": [
            {
                "name": "林澈",
                "appearance_anchor": "眉眼冷厉",
                "personality_anchor": ["冷静", "执拗"],
                "background_status": "停职调查员，仍暗中追查旧案",
                "ability_outline": "痕迹推演与现场复盘",
                "limitation": "过度冒险，难以及时止损",
                "growth_direction": "从独胆追查转向主动协作",
                "mainline_role": "负责追查旧案并撬开主线缺口",
                "mainline_clues": "掌握黑匣子与旧档案两条关键线索",
            }
        ]
    }

    characters = ContentAnalyzer._normalize_character_entries(parsed)

    assert len(characters) == 1
    assert characters[0]["appearance_anchor"] == "眉眼冷厉"
    assert characters[0]["personality_anchor"] == ["冷静", "执拗"]
    assert characters[0]["background_status"] == "停职调查员，仍暗中追查旧案"
    assert characters[0]["ability_outline"] == "痕迹推演与现场复盘"
    assert characters[0]["limitation"] == "过度冒险，难以及时止损"
    assert characters[0]["growth_direction"] == "从独胆追查转向主动协作"
    assert characters[0]["mainline_role"] == "负责追查旧案并撬开主线缺口"
    assert characters[0]["mainline_clues"] == "掌握黑匣子与旧档案两条关键线索"
