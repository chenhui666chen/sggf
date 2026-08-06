from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin
from app.services.audiobook.narration_styles import apply_narration_style_to_tts_params
from app.services.audiobook.script_adapter_pkg._dataclasses import (
    ChapterClosing,
    ChapterOpening,
    ChapterStructure,
    MusicCue,
    ScriptSegment,
)
from app.services.audiobook.script_adapter_pkg._structure import StructureMixin


class DummyStructure(StructureMixin):
    pass


class DummyScriptUtils(ScriptUtilsMixin):
    _narration_style_id = ""
    _narration_style_prompt = None


def test_first_chapter_opening_uses_audiobook_template_and_short_music():
    opening = DummyStructure()._generate_chapter_opening(
        chapter_title="第一章 逃亡",
        chapter_number=1,
        genre="科幻",
        analysis={"theme": "药奴逃亡，觉醒致命力量，遭遇未知威胁"},
        character_list=["纪老药", "灰袍老者", "护卫队长"],
    )

    assert "继续展开" not in opening.intro_text
    assert "现在开播" not in opening.intro_text
    assert "," not in opening.intro_text
    assert "、" in opening.intro_text or "与" in opening.intro_text
    assert "第1集" in opening.intro_text
    assert opening.intro_music is not None
    assert opening.intro_music.duration <= 14
    assert opening.intro_music.fade_out >= 1.5
    assert opening.duration <= 16


def test_chapter_closing_uses_audiobook_wrap_up_without_social_cta():
    closing = DummyStructure()._generate_chapter_closing(
        chapter_title="第一章 逃亡",
        chapter_number=1,
        genre="科幻",
        body_segments=[],
        analysis={"theme": "药奴逃亡，觉醒致命力量，遭遇未知威胁"},
    )

    text = " ".join([closing.recap_text, closing.hook_text, closing.call_to_action])
    assert "点赞" not in text
    assert "订阅" not in text
    assert "评论区" not in text
    assert closing.call_to_action
    assert closing.outro_music is not None
    assert closing.outro_music.duration <= 20


def test_chapter_closing_hook_does_not_use_narrator_as_actor():
    closing = DummyStructure()._generate_chapter_closing(
        chapter_title="第001章 救他的命，要我的命",
        chapter_number=1,
        genre="科幻",
        body_segments=[
            ScriptSegment(
                type="narration",
                text="掌心裂隙剧烈震颤，危机逼近。",
                speaker="旁白",
                emotion="tense",
            )
        ],
        analysis={"theme": "药奴陆衍逃亡中觉醒致命能力，遭遇更强大威胁"},
    )

    assert "旁白" not in closing.hook_text
    assert "旁白将如何选择" not in closing.hook_text


def test_chapter_closing_hook_prefers_known_character_mentioned_in_narration():
    closing = DummyStructure()._generate_chapter_closing(
        chapter_title="第001章 救他的命，要我的命",
        chapter_number=1,
        genre="科幻",
        body_segments=[
            ScriptSegment(
                type="narration",
                text="陆衍掌心裂隙剧烈震颤，前所未有的恐惧压了上来。",
                speaker="旁白",
                emotion="tense",
            )
        ],
        analysis={"theme": "药奴陆衍逃亡中觉醒致命能力，遭遇更强大威胁"},
        character_list=["旁白", "陆衍"],
    )

    assert "陆衍" in closing.hook_text
    assert "旁白" not in closing.hook_text


def test_opening_segment_gets_performable_tense_delivery():
    structure = ChapterStructure(
        chapter_title="第一章 逃亡",
        chapter_number=1,
        genre="科幻",
        opening=ChapterOpening(
            intro_text="纪老药、灰袍老者与护卫队长卷入逃亡。第1集，危机开始。",
            intro_narrator="旁白",
            intro_music=MusicCue(style="科幻电子音乐", duration=12.0),
            duration=12.0,
        ),
        body_segments=[
            ScriptSegment(
                type="narration",
                text="药奴穿过雨夜。",
                speaker="旁白",
                emotion="tense",
            )
        ],
        closing=None,
    )

    segments = DummyScriptUtils()._flatten_chapter_structure(structure)
    opening_segment = segments[0]

    assert opening_segment.emotion in {"tense", "mysterious", "solemn"}
    assert opening_segment.instruct_emotion
    assert opening_segment.performance_notes != "章节片头"
    assert "悬念" in opening_segment.performance_notes
    assert "声线" not in opening_segment.performance_notes
    assert "低沉" not in opening_segment.performance_notes


def test_professional_narration_legacy_style_does_not_merge_runtime_instructions():
    params = apply_narration_style_to_tts_params(
        "professional",
        {
            "emotion": "tense",
            "performance_notes": "低沉克制，带悬念感，句尾短暂停顿。",
        },
    )

    assert params["emotion"] == "tense"
    assert "instructions" not in params
    assert params["narration_style_legacy"] == "professional"


def test_engine_style_application_merges_segment_performance_notes():
    engine = DummyScriptUtils()
    engine._narration_style_id = "professional"
    segment = ScriptSegment(
        type="narration",
        text="危机开始逼近。",
        speaker="旁白",
        emotion="tense",
        performance_notes="低沉克制，带悬念感。",
    )

    params = engine._apply_narration_style_to_voice_params(
        segment,
        {
            "emotion": "tense",
            "speaker": "Arthur",
        },
    )

    assert params["emotion"] == "tense"
    assert params["performance_notes"] == "低沉克制，带悬念感。"
    assert "instructions" not in params
