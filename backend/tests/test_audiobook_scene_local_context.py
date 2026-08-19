"""阶段 2 入口上下文修复：场景局部描述构造与贯通测试。

覆盖指导文档 §7.1/§7.2 与阶段 2 验收：

- 局部描述按优先级构造（director context > instruct_scene > 章节事实 >
  导演风格兜底 > 最终兜底文案）；
- 切分后的每个场景具有各自的局部上下文，Prompt 顶层不再使用泛化兜底；
- 场景描述进入计划、Prompt 与签名（prompt_hash 对描述变化敏感）；
- 角色 descriptions 与 default TTS model 从入口贯通到声音档案。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (ROOT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.planner import ScenePlanner  # noqa: E402
from app.services.audiobook.scene_engine.prompt_compiler import (  # noqa: E402
    GENERIC_SCENE_FALLBACK_DESCRIPTION,
    ScenePromptCompiler,
)
from app.services.audiobook.scene_engine.scene_local_context import (  # noqa: E402
    build_scene_local_description,
)
from app.services.audiobook.script_adapter_pkg._dataclasses import (  # noqa: E402
    ScriptSegment,
)

from test_audiobook_seed_chapter_scene_pipeline import (  # noqa: E402
    FakeMaterializer,
    FakeRenderer,
)
from app.services.audiobook.scene_engine.chapter_pipeline import (  # noqa: E402
    ChapterScenePipeline,
)


def _segment(
    text: str,
    *,
    speaker: str,
    scene: str = "",
    pause_after: float = 0.0,
) -> ScriptSegment:
    return ScriptSegment(
        type="dialogue",
        text=text,
        speaker=speaker,
        emotion="tense",
        instruct_scene=scene,
        pause_after=pause_after,
    )


def _splitting_planner() -> ScenePlanner:
    """强制每个片段独占一个场景，验证逐场景局部上下文。"""
    return ScenePlanner(
        target_min_duration_s=0.1,
        target_max_duration_s=0.2,
        soft_max_duration_s=0.3,
        hard_max_duration_s=0.4,
    )


class TestLocalDescriptionPriority:
    def test_direction_context_wins_over_all_sources(self) -> None:
        segments = [_segment("你好。", speaker="旁白", scene="雨夜室内")]
        description = build_scene_local_description(
            segments,
            direction_context="导演指定的场景上下文",
            chapter_facts={"time": "深夜", "location": "站台"},
            director_style="悬疑压抑",
        )
        assert description == "导演指定的场景上下文"

    def test_instruct_scene_is_used_when_no_direction_context(self) -> None:
        segments = [
            _segment("第一句。", speaker="旁白", scene="雨夜室内"),
            _segment("第二句。", speaker="旁白", scene="雨夜室内"),
        ]
        description = build_scene_local_description(
            segments,
            chapter_facts={"time": "深夜"},
            director_style="悬疑压抑",
        )
        assert description == "雨夜室内"

    def test_distinct_instruct_scenes_are_merged_in_order(self) -> None:
        segments = [
            _segment("第一句。", speaker="旁白", scene="雨夜室内"),
            _segment("第二句。", speaker="旁白", scene="清晨站台"),
        ]
        description = build_scene_local_description(segments)
        assert description == "雨夜室内；清晨站台"

    def test_chapter_facts_are_used_when_segments_lack_scene(self) -> None:
        segments = [_segment("你好。", speaker="旁白")]
        description = build_scene_local_description(
            segments,
            chapter_facts={"time": "深夜", "location": "废弃车站", "mood": "紧张"},
            director_style="悬疑压抑",
        )
        assert description == "本章发生在深夜，废弃车站。整体氛围是紧张。"

    def test_director_style_is_the_penultimate_fallback(self) -> None:
        segments = [_segment("你好。", speaker="旁白")]
        description = build_scene_local_description(
            segments, director_style="悬疑压抑"
        )
        assert description == "悬疑压抑"

    def test_final_fallback_matches_prompt_compiler_constant(self) -> None:
        description = build_scene_local_description(
            [_segment("你好。", speaker="旁白")]
        )
        assert description == GENERIC_SCENE_FALLBACK_DESCRIPTION
        assert description == "按剧情顺序生成自然、连贯的有声小说场景。"


class TestPerSceneLocalContextInPlans:
    def test_split_scenes_carry_their_own_local_context(self) -> None:
        planner = _splitting_planner()
        segments = [
            _segment("她听着雨声，迟迟没有开口。", speaker="女主", scene="雨夜室内"),
            _segment("列车进站后，她说出了真相。", speaker="女主", scene="清晨站台"),
        ]

        plans = planner.plan(segments)

        assert len(plans) == 2
        assert "场景：雨夜室内" in plans[0].prompt
        assert "场景：清晨站台" in plans[1].prompt
        # 验收：Prompt 顶层不再使用泛化兜底
        for plan in plans:
            assert GENERIC_SCENE_FALLBACK_DESCRIPTION not in plan.prompt

    def test_scene_description_changes_prompt_signature(self) -> None:
        planner = ScenePlanner()
        segments_a = [_segment("你好。", speaker="旁白", scene="雨夜室内")]
        segments_b = [_segment("你好。", speaker="旁白", scene="清晨站台")]

        plan_a = planner.plan(segments_a)[0]
        plan_b = planner.plan(segments_b)[0]

        assert plan_a.prompt_hash != plan_b.prompt_hash

    def test_chapter_facts_reach_prompt_when_no_instruct_scene(self) -> None:
        planner = ScenePlanner()
        segments = [_segment("你好。", speaker="旁白")]

        plans = planner.plan(
            segments,
            chapter_facts={"time": "深夜", "location": "废弃车站"},
        )

        # sanitize_fixed_voice_scene_text 会去掉句尾句号，故断言不含句号
        assert "场景：本章发生在深夜，废弃车站" in plans[0].prompt
        assert GENERIC_SCENE_FALLBACK_DESCRIPTION not in plans[0].prompt

    def test_split_plan_once_preserves_parent_local_context(self) -> None:
        planner = ScenePlanner()
        segments = [
            _segment("第一句。", speaker="女主", scene="雨夜室内", pause_after=60),
            _segment("第二句。", speaker="女主", scene="雨夜室内"),
        ]
        parent = planner.plan(segments)[0]

        parts = planner.split_plan_once(parent, segments)

        assert parts
        for part in parts:
            assert "场景：雨夜室内" in part.prompt


class TestEntryContextWiringThroughPipeline:
    def test_pipeline_passes_descriptions_and_default_tts_model(self) -> None:
        from app.services.audiobook.tts_model_ids import SEED_TTS_20_EXPRESSIVE_MODEL

        materializer = FakeMaterializer()
        renderer = FakeRenderer()
        pipeline = ChapterScenePipeline(
            planner=ScenePlanner(),
            reference_materializer=materializer,
            renderer=renderer,
        )
        segments = [
            _segment("她听着雨声，迟迟没有开口。", speaker="女主", scene="雨夜室内"),
            _segment("旁白低声道破了真相。", speaker="旁白", scene="雨夜室内"),
        ]

        result = pipeline.render(
            segments,
            voice_mapping={"女主": {"tts_model": "", "voice_id": "voice-001"}},
            descriptions={
                "女主": "低沉稳重的女刑警",
                "旁白": "冷静克制的讲述者",
            },
            default_tts_model=SEED_TTS_20_EXPRESSIVE_MODEL,
            chapter_facts={"time": "深夜"},
            director_style="悬疑压抑",
        )

        assert result.scenes
        plan = result.plans[0]
        # default_tts_model 贯通：原生 Seed-TTS speaker 直传
        assert plan.references[0] == {"speaker": "voice-001"}
        # §7.2：有 reference 的角色不重复注入静态声音身份
        assert "低沉稳重的女刑警" not in plan.prompt
        # 无 reference 的临时角色使用可听辨的文字声音描述
        assert "冷静克制的讲述者" in plan.prompt
        # 章节事实贯通进入 Prompt 顶层
        assert "场景：雨夜室内" in plan.prompt


class TestPromptCompilerFallbackConstant:
    def test_compiler_top_level_uses_provided_description(self) -> None:
        compiler = ScenePromptCompiler()
        compiled = compiler.compile_segments(
            [_segment("你好。", speaker="旁白")],
            scene_description="雨夜室内",
        )
        assert compiled.prompt.startswith("场景：雨夜室内")

    def test_compiler_keeps_named_final_fallback_only_when_empty(self) -> None:
        compiler = ScenePromptCompiler()
        compiled = compiler.compile_segments(
            [_segment("你好。", speaker="旁白")],
            scene_description="",
        )
        assert f"场景：{GENERIC_SCENE_FALLBACK_DESCRIPTION}" in compiled.prompt
