"""Content analyzer package."""

from app.services.book_parser.content_analyzer_pkg._base import ContentAnalyzerBase
from app.services.book_parser.content_analyzer_pkg._text_utils_mixin import TextUtilsMixin
from app.services.book_parser.content_analyzer_pkg._char_infer_mixin import CharInferMixin
from app.services.book_parser.content_analyzer_pkg._char_norm_mixin import CharNormMixin
from app.services.book_parser.content_analyzer_pkg._setting_mixin import SettingMixin
from app.services.book_parser.content_analyzer_pkg._chapter_summary_mixin import ChapterSummaryMixin
from app.services.book_parser.content_analyzer_pkg._synthesis_mixin import SynthesisMixin
from app.services.book_parser.content_analyzer_pkg._type_analysis_mixin import TypeAnalysisMixin
from app.services.book_parser.content_analyzer_pkg._helpers_mixin import HelpersMixin
from app.services.book_parser.content_analyzer_pkg._quick_analyze_mixin import QuickAnalyzeMixin


class ContentAnalyzer(
    ContentAnalyzerBase,
    TextUtilsMixin,
    CharInferMixin,
    CharNormMixin,
    SettingMixin,
    ChapterSummaryMixin,
    SynthesisMixin,
    TypeAnalysisMixin,
    HelpersMixin,
    QuickAnalyzeMixin,
):
    pass


from app.services.book_parser.content_analyzer_pkg._base import AnalysisType, ChapterSummary, AnalysisResult

__all__ = ["ContentAnalyzer", "AnalysisType", "ChapterSummary", "AnalysisResult"]
