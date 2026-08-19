"""阶段 4 Prompt V2 修复测试（指导文档 §9.2/§9.3/§9.4/§9.5）。

覆盖：

- §9.2 表演模板：不再统一套用“用……的方式说道”，编译器根据显式动作
  选择说道/问道/回应道/低语道/喊道/一字一顿地说道；没有明确动作时
  使用中性模板；台词逐字不变。
- §9.3 非语言人声兼容词表：最长匹配（倒吸冷气不拆成吸气）；单字项
  只在引号、标点、空白或显式动作模板边界内命中，不从普通形容词句
  裸子串抽取。
- §9.4 until_text：中性措辞“持续至对应台词中的“{related_text}”说完”；
  编译前验证 related_text 是目标台词子串，失败降级“持续至该句说完”。
- §9.5 字符预算：估算复用实际事件渲染 helper，不使用 str(dataclass)。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.models import SceneAudioEvent  # noqa: E402
from app.services.audiobook.scene_engine.planner import ScenePlanner  # noqa: E402
from app.services.audiobook.scene_engine.prompt_compiler import (  # noqa: E402
    MICRO_VOCALIZATION_TERMS,
    ScenePromptCompiler,
)


def _speech(performance: str, *, speaker: str = "林川", text: str = "你是谁？") -> SceneAudioEvent:
    return SceneAudioEvent(
        kind="speech",
        anchor="during",
        speaker=speaker,
        exact_text=text,
        performance=performance,
    )


class TestSpeechVerbTemplates:
    @pytest.mark.parametrize(
        "performance,verb",
        [
            ("低声询问", "问道"),
            ("大声喊叫", "喊道"),
            ("低语", "低语道"),
            ("一字一顿", "一字一顿地说道"),
            ("平静回应", "回应道"),
        ],
    )
    def test_explicit_action_selects_verb(self, performance, verb):
        compiler = ScenePromptCompiler()
        result = compiler.compile_events([_speech(performance)])
        assert f"林川{verb}：“你是谁？”" in result.prompt
        assert "的方式说道" not in result.prompt

    def test_no_explicit_action_uses_neutral_template(self):
        compiler = ScenePromptCompiler()
        result = compiler.compile_events([_speech("语速缓慢，保持克制")])
        assert "林川说道：“你是谁？”" in result.prompt
        assert "的方式" not in result.prompt
        assert "语速缓慢，保持克制" in result.prompt

    def test_narrator_uses_narration_verb(self):
        compiler = ScenePromptCompiler()
        result = compiler.compile_events(
            [_speech("平稳铺陈", speaker="旁白", text="夜色渐深。")]
        )
        assert "旁白讲述：“夜色渐深。”" in result.prompt

    def test_dialogue_text_verbatim(self):
        compiler = ScenePromptCompiler()
        text = "我们先检查一下现场，别出声。"
        result = compiler.compile_events([_speech("压低声音问道", text=text)])
        assert result.expected_texts == (text,)
        assert f"“{text}”" in result.prompt


class TestVocalizationVocabulary:
    def test_full_vocabulary_covered(self):
        required = (
            "轻笑", "笑声", "冷笑", "苦笑", "哭泣", "抽泣", "哽咽", "呜咽",
            "吸气", "倒吸冷气", "喘息", "呼喝", "惊呼", "呼喊", "尖叫",
            "呻吟", "吞咽", "咳嗽", "叹气", "哼", "嗯", "啊", "诶", "哎",
        )
        for term in required:
            assert term in MICRO_VOCALIZATION_TERMS

    def test_longest_match_not_split(self):
        event = ScenePromptCompiler._build_vocalization_event("林川", "倒吸冷气")
        assert event is not None
        assert event.performance == "倒吸冷气"
        assert "吸气" not in event.performance.replace("倒吸冷气", "")

    def test_multiple_terms_ordered_by_position(self):
        event = ScenePromptCompiler._build_vocalization_event("林川", "呜咽并抽泣")
        assert event is not None
        assert event.performance == "呜咽、抽泣"

    @pytest.mark.parametrize(
        "performance",
        ["“嗯”", "嗯？", "先嗯了一声", "发出一声“啊”"],
    )
    def test_single_char_hits_at_boundaries(self, performance):
        event = ScenePromptCompiler._build_vocalization_event("林川", performance)
        assert event is not None

    @pytest.mark.parametrize(
        "performance",
        ["惊讶啊", "语气啊得不自然", "有些哼唧", "啊得不自然"],
    )
    def test_single_char_not_extracted_from_bare_substring(self, performance):
        event = ScenePromptCompiler._build_vocalization_event("林川", performance)
        assert event is None


class TestUntilTextNeutralWording:
    def _events(self, related_text: str):
        return [
            SceneAudioEvent(
                kind="speech",
                anchor="during",
                speaker="男主",
                exact_text="脑子进水啊？三八！",
            ),
            SceneAudioEvent(
                kind="sfx",
                anchor="until_text",
                acoustic="木地板上的快速脚步声",
                related_text=related_text,
            ),
        ]

    def test_valid_related_text_uses_neutral_wording(self):
        compiler = ScenePromptCompiler()
        result = compiler.compile_events(self._events("三八"))
        assert "持续至对应台词中的“三八”说完" in result.prompt
        assert "二字" not in result.prompt

    def test_invalid_related_text_degrades_to_sentence_end(self):
        compiler = ScenePromptCompiler()
        result = compiler.compile_events(self._events("不存在的词"))
        assert "持续至该句说完" in result.prompt
        assert "不存在的词" not in result.prompt


class TestCharEstimateUsesRenderHelper:
    class _LoudStr:
        """__str__ 返回超长内容，验证估算不走 str(dataclass)。"""

        def __init__(self, **fields) -> None:
            self.__dict__.update(fields)

        def __str__(self) -> str:
            return "X" * 10000

    def _segment(self, effect, music_cue):
        return SimpleNamespace(
            text="你好。",
            speaker="林川",
            performance_notes="",
            instruct_scene="",
            instruct_emotion="",
            emotion="",
            sound_effects=[effect],
            music_cue=music_cue,
        )

    def test_estimate_ignores_str_of_effect_and_music(self):
        loud_effect = self._LoudStr(name="木门吱呀声", timing="trigger", layer="action")
        quiet_effect = SimpleNamespace(name="木门吱呀声", timing="trigger", layer="action")
        loud_music = self._LoudStr(style="紧张弦乐", fade_in=0.0, fade_out=0.0, duration=None)
        quiet_music = SimpleNamespace(style="紧张弦乐", fade_in=0.0, fade_out=0.0, duration=None)
        loud = ScenePlanner._segment_prompt_char_estimate(
            self._segment(loud_effect, loud_music)
        )
        quiet = ScenePlanner._segment_prompt_char_estimate(
            self._segment(quiet_effect, quiet_music)
        )
        assert loud == quiet
        assert loud < 2000  # 远低于 __str__ 注入的 20000 字符
