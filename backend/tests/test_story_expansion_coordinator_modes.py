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

from app.services.story_expansion_coordinator import StoryExpansionCoordinator


def test_total_mode_never_auto_upgrades_to_epic() -> None:
    coordinator = StoryExpansionCoordinator()

    result = coordinator.determine_execution_mode(
        current_outline="""
#### 第1章：《黑岩集》
- **场景目标**：觉醒古印

#### 第2章：《墨影叩门》
- **场景目标**：验证规则

#### 第3章：《巷战初鸣》
- **场景目标**：完成第一次反杀
""".strip(),
        characters="### 【姓名】：叶清尘\n### 【姓名】：墨丹心",
        target_total_chapters=360,
        target_total_characters=12,
        expansion_mode="total",
    )

    assert result["mode"] == "iterative"
    assert result["requested_expansion_mode"] == "total"


def test_total_mode_suitability_uses_new_recommended_and_framework_thresholds() -> None:
    suitability = StoryExpansionCoordinator._build_total_mode_suitability(
        current_chapter_count=48,
        target_chapter_count=320,
        chapters_needed=272,
        execution_mode="iterative",
    )

    assert suitability["recommended_total_chapters_max"] == 300
    assert suitability["framework_preferred_total_from"] == 301
    assert suitability["request_band"] == "forbidden"
    assert "禁止继续使用常规协同" in suitability["summary"]


def test_character_only_target_estimates_total_chapters_from_character_scale() -> None:
    coordinator = StoryExpansionCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="""
#### 第1章：初醒
#### 第2章：试探
#### 第3章：交锋
""".strip(),
        characters="""
### 【姓名】：林岩
### 【姓名】：回声
### 【姓名】：扳手
""".strip(),
        world_setting="星际废土",
        target_total_chapters=None,
        target_total_characters=38,
        enable_auto_supplement=True,
        expansion_mode="total",
    )

    assert analysis["effective_target_character_count"] == 38
    assert analysis["effective_target_chapter_count"] == 190
    assert analysis["auto_supplement"]["suggested_target_chapters"] == 190


def test_character_only_target_respects_total_mode_chapter_cap() -> None:
    coordinator = StoryExpansionCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="""
#### 第1章：初醒
#### 第2章：试探
#### 第3章：交锋
""".strip(),
        characters="""
### 【姓名】：林岩
### 【姓名】：回声
### 【姓名】：扳手
""".strip(),
        world_setting="星际废土",
        target_total_chapters=None,
        target_total_characters=190,
        enable_auto_supplement=True,
        expansion_mode="total",
    )

    assert analysis["effective_target_character_count"] == 190
    assert analysis["effective_target_chapter_count"] == 300
    assert analysis["auto_supplement"]["suggested_target_chapters"] == 300
