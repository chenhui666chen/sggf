"""说话风格与生成后行为一致性校验（P3）单元测试。

背景：人物防扁平化改造第三阶段——
- ParsedCharacter 新增可选 speech_style（说话风格短摘要），进入运行态摘要；
- 章节生成后增加可解释的行为一致性检查：
  * 禁用/回避表达出现在该角色对白 → high 违规（附证据片段）；
  * 同章多角色对白语气特征高度同质 → medium 提示；
  * 检查只产出报告（角色/章节/证据/严重等级），不阻断生成，缺字段历史项目返回空报告。

纯文本规则，离线确定性，不依赖 LLM。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.services.character_parser import CharacterTextParser
from app.services.character_runtime_context import build_character_runtime_brief
from app.services.character_behavior_consistency import (
    BehaviorConsistencyIssue,
    check_character_behavior_consistency,
    extract_character_dialogues,
)


CHAR_CARD_WITH_SPEECH_STYLE = """### 【姓名】：林昭
【故事立场】：主角方
【角色定位】：主角
【性格特点】：冷静缜密，谋定后动
【说话风格】：语气克制，短句为主；自称"在下"；称对方"阁下"；回避：感叹号、口头禅"其实"

### 【姓名】：苏晚晴
【故事立场】：亦正亦邪
【角色定位】：危险盟友
【说话风格】：语速快，反问多；自称"我"；口头禅"有意思"
"""


def test_parser_extracts_speech_style_field() -> None:
    parsed = CharacterTextParser().parse_all_characters(CHAR_CARD_WITH_SPEECH_STYLE)

    assert len(parsed) == 2
    assert parsed[0].speech_style is not None
    assert "在下" in parsed[0].speech_style
    assert "回避" in parsed[0].speech_style
    assert parsed[1].speech_style is not None
    assert "反问" in parsed[1].speech_style


def test_build_profile_includes_speech_style_section() -> None:
    parsed = CharacterTextParser().parse_all_characters(CHAR_CARD_WITH_SPEECH_STYLE)

    profile = parsed[0].build_profile()
    assert "【说话风格】" in profile
    assert "在下" in profile


def test_runtime_brief_includes_speech_style() -> None:
    brief = build_character_runtime_brief(
        name="林昭",
        role="主角方",
        role_position="主角",
        speech_style='语气克制，短句为主；自称"在下"；回避：感叹号、口头禅"其实"',
    )

    assert "说话风格：" in brief
    assert "在下" in brief


def test_runtime_brief_without_speech_style_keeps_legacy_output() -> None:
    brief = build_character_runtime_brief(name="林昭", role="主角方", motivation="查明真相")

    assert "说话风格" not in brief
    assert "动机：查明真相" in brief


def test_check_flags_forbidden_expression_in_character_dialogue() -> None:
    chapter_text = (
        "林昭道：“在下以为，此印有诈。”\n"
        "苏晚晴笑道：“其实吧，我也觉得有问题！”\n"
        "林昭沉声道：“其实，你说得对。”\n"
    )

    issues = check_character_behavior_consistency(
        chapter_text,
        CHAR_CARD_WITH_SPEECH_STYLE,
        chapter_number=17,
    )

    forbidden = [
        issue for issue in issues if issue.check_type == "forbidden_expression"
    ]
    # 林昭对白出现其回避的口头禅"其实"（第三句）；苏晚晴的"其实"不是她的回避项
    assert any(issue.character_name == "林昭" for issue in forbidden)
    lin_issue = next(issue for issue in forbidden if issue.character_name == "林昭")
    assert lin_issue.severity == "high"
    assert "其实" in lin_issue.reason
    assert "其实" in lin_issue.evidence_text  # 证据片段可定位
    assert lin_issue.chapter_number == 17
    assert not any(issue.character_name == "苏晚晴" for issue in forbidden)


def test_check_clean_chapter_returns_no_issues() -> None:
    chapter_text = (
        "林昭道：“在下以为，此印有诈。”\n"
        "苏晚晴笑道：“有意思，说说你的看法？”\n"
    )

    issues = check_character_behavior_consistency(
        chapter_text,
        CHAR_CARD_WITH_SPEECH_STYLE,
        chapter_number=17,
    )

    assert issues == []


def test_check_missing_speech_style_returns_empty_report() -> None:
    """历史项目角色卡无说话风格字段：返回空报告，不阻断。"""
    legacy_characters = (
        "### 【姓名】：顾长歌\n"
        "【故事立场】：主角方\n"
        "【角色定位】：主角\n"
        "【核心动机】：查明内鬼来源\n"
    )
    chapter_text = "顾长歌道：“其实也没什么。”\n"

    issues = check_character_behavior_consistency(
        chapter_text,
        legacy_characters,
        chapter_number=1,
    )

    assert issues == []


def test_check_detects_dialogue_homogenization() -> None:
    """同场两个角色对白语气特征几乎一致（同句长、同标点习惯）→ 同质化提示。"""
    characters = (
        "### 【姓名】：甲\n"
        "【角色定位】：主角\n"
        "【说话风格】：短句，克制；回避：感叹号\n\n"
        "### 【姓名】：乙\n"
        "【角色定位】：对手\n"
        "【说话风格】：短句，克制；回避：感叹号\n"
    )
    chapter_text = (
        "甲道：“今天风很大。”\n"
        "乙道：“今天雨很小。”\n"
        "甲说：“我们去东边。”\n"
        "乙说：“我们去西边。”\n"
    )

    issues = check_character_behavior_consistency(
        chapter_text,
        characters,
        chapter_number=3,
    )

    homogenized = [
        issue for issue in issues if issue.check_type == "dialogue_homogenization"
    ]
    assert len(homogenized) == 1
    assert homogenized[0].severity == "medium"
    assert homogenized[0].evidence_text  # 附证据（对白样本）


def test_extract_character_dialogues_supports_stable_feature_detection() -> None:
    """P3 验收1：同一角色在不同章节的对白可提取并检测稳定语言特征（自称）。"""
    chapter_one = '林昭道：“在下以为，此印有诈。”\n苏晚晴说：“有意思。”\n'
    chapter_two = '林昭答道：“在下明白了。”\n苏晚晴问：“是吗？”\n'

    one = extract_character_dialogues(chapter_one, "林昭")
    two = extract_character_dialogues(chapter_two, "林昭")

    assert one == ["在下以为，此印有诈。"]
    assert two == ["在下明白了。"]
    # 稳定特征：两章对白均保持自称"在下"
    assert all("在下" in line for line in one + two)


# ==================== 后处理链路集成（章节保存后检查） ====================

def _build_post_save_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.character import Character
    from app.models.project import Project
    from app.models.user import User

    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            Character.__table__,
        ],
    )
    return session_factory()


def _seed_post_save_project(db):
    from app.models.project import Project
    from app.models.user import User

    user = User(username="post_save_user", email="post_save@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(title="后处理检查项目", description="", user_id=user.id, display_no=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.id


def test_run_character_behavior_consistency_check_reports_from_db():
    from app.models.character import Character
    from app.services.chapter_post_save import (
        run_character_behavior_consistency_check,
    )

    db = _build_post_save_session()
    project_id = _seed_post_save_project(db)
    try:
        db.add(
            Character(
                project_id=project_id,
                name="林昭",
                speech_style='语气克制；回避：口头禅"其实"',
            )
        )
        db.commit()

        result = run_character_behavior_consistency_check(
            db,
            project_id=project_id,
            chapter_number=17,
            chapter_content="林昭道：“其实，此印有诈。”\n",
            notify=False,
        )

        assert result["checked"] is True
        assert len(result["issues"]) == 1
        issue = result["issues"][0]
        assert issue["character_name"] == "林昭"
        assert issue["severity"] == "high"
        assert issue["check_type"] == "forbidden_expression"
        assert "其实" in issue["evidence_text"]
    finally:
        db.close()


def test_run_character_behavior_consistency_check_skips_without_speech_style():
    from app.models.character import Character
    from app.services.chapter_post_save import (
        run_character_behavior_consistency_check,
    )

    db = _build_post_save_session()
    project_id = _seed_post_save_project(db)
    try:
        # 历史项目角色：无说话风格字段
        db.add(Character(project_id=project_id, name="顾长歌", motivation="查明真相"))
        db.commit()

        result = run_character_behavior_consistency_check(
            db,
            project_id=project_id,
            chapter_number=1,
            chapter_content="顾长歌道：“其实也没什么。”\n",
            notify=False,
        )

        assert result["checked"] is False
        assert result["issues"] == []
    finally:
        db.close()


def test_run_character_behavior_consistency_check_never_raises():
    """检查失败（如无角色数据）只记录日志，不阻断章节后处理。"""
    from app.services.chapter_post_save import (
        run_character_behavior_consistency_check,
    )

    db = _build_post_save_session()
    project_id = _seed_post_save_project(db)
    try:
        result = run_character_behavior_consistency_check(
            db,
            project_id=project_id,
            chapter_number=1,
            chapter_content="",
            notify=False,
        )
        assert result["issues"] == []
    finally:
        db.close()
