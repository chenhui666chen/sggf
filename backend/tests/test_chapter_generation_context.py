import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
from app.services.character_runtime_context import (
    build_initial_character_contexts_from_text,
)
from app.services.workflow_context_builder import WorkflowContextBuilder


class DummyResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class DummySession:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        row = self.rows.pop(0) if self.rows else None
        return DummyResult(row)


def _build_test_characters() -> str:
    return (
        "### 【姓名】：顾长歌\n"
        "【角色定位】：主角\n"
        "【核心动机】：查明内鬼来源\n"
        "【关键关系】：苏晚晴：合作中试探\n"
        "【在情节中的作用】：推动主线调查\n"
        "【关联线索】：假印来源\n\n"
        "### 【姓名】：苏晚晴\n"
        "【角色定位】：危险盟友\n"
        "【核心动机】：借顾长歌之手钓出幕后黑手\n"
        "【关键关系】：顾长歌：合作中试探\n"
        "【在情节中的作用】：制造信息反差\n"
        "【关联线索】：偏殿暗门\n\n"
        "### 【姓名】：黑市使者\n"
        "【角色定位】：反派线联系人\n"
        "【核心动机】：掩盖假印交易链\n"
        "【关键关系】：顾长歌：潜在敌对\n"
        "【在情节中的作用】：制造追查阻力\n"
        "【关联线索】：黑市密账\n"
    )


def test_build_chapter_generation_context_prefers_exact_outline_from_epic_volumes_detail() -> None:
    db = DummySession(
        rows=[
            (
                "",
                "2026-04-26T00:00:00",
                "",
                json.dumps(
                    {
                        "total_volumes": 2,
                        "framework_header": "主线约束：第17章必须确认假印来源。",
                        "framework_footer": "长线伏笔：黑市印谱暂时不要回收。",
                        "volumes": {
                            "1": {
                                "type": "detail",
                                "title": "灯影入局",
                                "summary": "- 卷目标：潜入偏殿，确认内鬼身份。",
                                "detail": "\n\n".join(
                                    [
                                        "### 第16章：夜探外城\n- 场景目标：摸清外城哨点。",
                                        "### 第17章：灯下问局\n- 场景目标：顾长歌潜入偏殿确认假印来源。\n- 关键事件：试探苏晚晴；发现第二枚假印。\n- 结尾钩子：偏殿深处有人提前叫出了顾长歌的名字。",
                                        "### 第18章：密档失踪\n- 场景目标：追查失踪卷宗。",
                                    ]
                                ),
                                "chapters_range": [1, 40],
                                "chapter_count": 40,
                                "expanded_at": None,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    )

    builder = WorkflowContextBuilder(db)
    context = builder.build_chapter_generation_context(
        9,
        17,
        plot_outline="### 第17章：旧版细纲\n- 场景目标：这里不该优先。",
        characters=_build_test_characters(),
    )

    assert context.outline_source == "epic_volumes_detail.volume_1"
    assert "第17章：灯下问局" in context.current_chapter_outline
    assert "灯影入局" in context.current_volume_context
    assert "第17章必须确认假印来源" in context.epic_framework_context
    assert context.focus_character_names[:2] == ["顾长歌", "苏晚晴"]
    assert "1. 顾长歌" in context.character_prompt_context
    assert "顾长歌" in context.core_character_anchor_context
    assert "苏晚晴" in context.focus_character_relationship_context
    assert "顾长歌" in context.planning_character_prompt_context
    assert "苏晚晴" in context.planning_character_prompt_context
    assert "【核心角色锚点】" in context.content_character_context
    assert "【焦点人物关系】" in context.content_character_context
    assert "相关人物：顾长歌、苏晚晴" in context.rag_query_text


def test_build_chapter_generation_context_preserves_core_anchor_when_focus_is_side_character() -> None:
    db = DummySession(rows=[None])
    builder = WorkflowContextBuilder(db)

    context = builder.build_chapter_generation_context(
        12,
        17,
        plot_outline=(
            "### 第17章：苏晚晴先行试探\n"
            "- 场景目标：苏晚晴单独进入偏殿，试探黑市使者反应。\n"
            "- 关键事件：苏晚晴故意放出错误线索。\n"
        ),
        characters=_build_test_characters(),
    )

    assert context.outline_source == "plot_outline"
    assert context.focus_character_names[0] == "苏晚晴"
    assert "黑市使者" in context.focus_character_names
    assert "顾长歌" in context.core_character_anchor_context
    assert "苏晚晴" in context.focus_character_relationship_context
    assert "【核心角色锚点】" in context.content_character_context
    assert "【焦点人物关系】" in context.content_character_context


def test_build_chapter_generation_context_falls_back_to_plot_outline() -> None:
    db = DummySession(rows=[None])
    builder = WorkflowContextBuilder(db)

    context = builder.build_chapter_generation_context(
        12,
        17,
        plot_outline=(
            "### 第16章：夜探外城\n- 场景目标：摸清外城哨点。\n\n"
            "### 第17章：灯下问局\n- 场景目标：顾长歌潜入偏殿确认假印来源。\n"
        ),
        characters="### 【姓名】：顾长歌\n【角色定位】：主角",
    )

    assert context.outline_source == "plot_outline"
    assert "第17章：灯下问局" in context.current_chapter_outline


def test_build_chapter_generation_context_injects_latest_state_snapshots() -> None:
    """闭环读取端：生成第 N 章时注入第 N-1 章的最新人物状态快照。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.character import Character, CharacterStateSnapshot
    from app.models.project import Project
    from app.models.user import User
    from app.services.character_state_snapshot import save_character_state_snapshot

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE project_settings ("
            "project_id INTEGER, epic_framework TEXT, "
            "epic_framework_generated_at TEXT, plot_outline TEXT, "
            "epic_volumes_detail TEXT)"
        ))
        conn.commit()
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            Character.__table__,
            CharacterStateSnapshot.__table__,
        ],
    )
    db = session_factory()
    try:
        user = User(username="ctx_user", email="ctx@example.com", password_hash="hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        project = Project(title="快照注入项目", description="", user_id=user.id, display_no=1)
        db.add(project)
        db.commit()
        db.refresh(project)
        char = Character(project_id=project.id, name="顾长歌", motivation="查明内鬼来源")
        db.add(char)
        db.commit()
        db.refresh(char)

        save_character_state_snapshot(
            db,
            project_id=project.id,
            character_id=char.id,
            chapter_id=16,
            chapter_number=16,
            current_motivation="确认假印来源",
            current_belief="苏晚晴有所隐瞒",
            emotional_state="克制中的紧绷",
        )

        builder = WorkflowContextBuilder(db)
        context = builder.build_chapter_generation_context(
            project.id,
            17,
            plot_outline="### 第17章：灯下问局\n- 场景目标：顾长歌潜入偏殿确认假印来源。",
            characters=_build_test_characters(),
        )

        assert "【人物当前状态】" in context.character_state_context
        assert "顾长歌" in context.character_state_context
        assert "确认假印来源" in context.character_state_context
    finally:
        db.close()


def test_build_chapter_generation_context_without_snapshots_keeps_empty_state() -> None:
    db = DummySession(rows=[None])
    builder = WorkflowContextBuilder(db)

    context = builder.build_chapter_generation_context(
        12,
        17,
        plot_outline="### 第17章：灯下问局\n- 场景目标：顾长歌潜入偏殿。",
        characters=_build_test_characters(),
    )

    assert context.character_state_context == ""


def test_chapter_prompt_builder_includes_precise_chapter_context_sections() -> None:
    builder = ChapterPromptBuilder(genre="悬疑")

    prompt = builder.build_user_prompt(
        next_chapter_number=17,
        chapter_plan="本章潜入偏殿，确认假印来源，并在结尾放出新的身份疑点。",
        previous_ending="偏殿门缝后传来轻微的金属摩擦声。",
        recent_chapter_assets_summary="第16章《夜探外城》\n- 场景目标：摸清哨点\n- 结尾钩子：有人提前撤走了账册",
        rag_character_context="- 顾长歌：合作中试探苏晚晴",
        rag_world_context="- 偏殿夜巡每半个时辰轮换一次",
        selected_opening=("悬念开头", "从异常动静切入", ""),
        selected_ending=("信息炸弹式", "在真相揭开前停住", ""),
        current_chapter_outline="### 第17章：灯下问局\n- 场景目标：顾长歌潜入偏殿确认假印来源。",
        current_volume_context="第1卷《灯影入局》\n- 覆盖章节：第1-40章（当前生成第17章）\n- 卷目标：潜入偏殿，确认内鬼身份。",
        core_character_anchor_context="【核心角色锚点】\n- 顾长歌（主角） | 动机：查明内鬼来源",
        focus_character_relationship_context="【焦点人物关系】\n- 顾长歌：苏晚晴：合作中试探",
        character_runtime_context="【角色名单摘要】\n1. 顾长歌（主角）\n2. 苏晚晴（危险盟友）",
        epic_framework_context="【长篇框架约束】\n主线约束：第17章必须确认假印来源。",
    )

    assert "【当前章节精确细纲】" in prompt
    assert "### 第17章：灯下问局" in prompt
    assert "【当前卷上下文】" in prompt
    assert "【核心角色锚点】" in prompt
    assert "【焦点人物关系】" in prompt
    assert "【人物运行态摘要】" in prompt
    assert "【长篇框架约束】" in prompt


def _build_first_chapter_characters() -> str:
    return (
        "### 【姓名】：顾长歌\n"
        "【故事立场】：主角方\n"
        "【角色定位】：主角\n"
        "【性格特点】：谨慎多疑，先验证后行动\n"
        "【世界观/价值观立场】：重承诺胜过个人利益\n"
        "【核心动机】：查明内鬼来源\n"
        "【关键关系】：苏晚晴：合作中试探\n\n"
        "### 【姓名】：苏晚晴\n"
        "【故事立场】：亦正亦邪\n"
        "【角色定位】：危险盟友\n"
        "【性格特点】：外冷内热，习惯用交易掩饰善意\n"
        "【世界观/价值观立场】：只有活下来的人才配谈原则\n"
        "【核心动机】：借顾长歌之手钓出幕后黑手\n"
        "【关键关系】：顾长歌：依赖与试探并存\n"
    )


def test_build_initial_character_contexts_from_text_returns_baseline_contexts() -> None:
    contexts = build_initial_character_contexts_from_text(
        _build_first_chapter_characters()
    )

    assert "顾长歌" in contexts.core_character_anchor_context
    assert "性格：谨慎多疑，先验证后行动" in contexts.core_character_anchor_context
    assert "价值倾向：重承诺胜过个人利益" in contexts.core_character_anchor_context

    assert "苏晚晴" in contexts.focus_character_relationship_context

    assert "顾长歌" in contexts.character_runtime_context
    assert "性格：谨慎多疑，先验证后行动" in contexts.character_runtime_context


def test_build_initial_character_contexts_from_text_empty_input_returns_empty_strings() -> None:
    contexts = build_initial_character_contexts_from_text("")

    assert contexts.core_character_anchor_context == ""
    assert contexts.focus_character_relationship_context == ""
    assert contexts.character_runtime_context == ""


def test_first_chapter_user_prompt_contains_character_baseline_context() -> None:
    """P1 验收：首章 user_prompt 必须包含身份、动机、性格锚点和价值倾向。"""
    characters = _build_first_chapter_characters()
    contexts = build_initial_character_contexts_from_text(characters)

    prompt_builder = ChapterPromptBuilder(genre="悬疑")
    user_prompt = prompt_builder.build_user_prompt(
        next_chapter_number=1,
        chapter_plan="第1章：顾长歌初入偏殿，与苏晚晴首次交锋。",
        previous_ending="",
        recent_chapter_assets_summary="",
        rag_character_context="",
        rag_world_context="",
        selected_opening=("悬念开头", "从异常动静切入", ""),
        selected_ending=("信息炸弹式", "在真相揭开前停住", ""),
        core_character_anchor_context=contexts.core_character_anchor_context,
        focus_character_relationship_context=contexts.focus_character_relationship_context,
        character_runtime_context=contexts.character_runtime_context,
    )

    # 身份 + 动机 + 性格锚点 + 价值倾向均进入最终 prompt
    assert "顾长歌" in user_prompt
    assert "动机：查明内鬼来源" in user_prompt
    assert "性格：谨慎多疑，先验证后行动" in user_prompt
    assert "价值倾向：重承诺胜过个人利益" in user_prompt
    # RAG 为空时不阻断，prompt 仍包含人物上下文
    assert "【核心角色锚点】" in user_prompt
    assert "【人物运行态摘要】" in user_prompt
