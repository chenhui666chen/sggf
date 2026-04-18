"""提示词 JSON 化管理集成测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def test_prompt_manager_load():
    print("\n=== Test 1: PromptManager 加载 ===")
    from app.services.prompts.manager import prompt_manager

    assert prompt_manager.is_loaded, "PromptManager 未加载成功"
    print(f"  [OK] 加载成功, version={prompt_manager.version}")

    agents = prompt_manager.list_agents()
    print(f"  [OK] 已注册 Agent 数: {len(agents)}")
    for key, name in agents.items():
        print(f"    - {key}: {name}")


def test_agent_prompts():
    print("\n=== Test 2: Agent System Prompt 获取 ===")
    from app.services.prompts.manager import prompt_manager

    expected_keys = [
        "world_architect",
        "character_designer",
        "outline_plan_parser",
        "creative_director",
        "plot_architect",
        "content_creator",
        "quality_reviewer",
        "event_validator",
        "style_optimizer",
        "iteration_coordinator",
        "chapter_logic_checker",
    ]

    for key in expected_keys:
        prompt = prompt_manager.get_agent_prompt(key)
        assert prompt, f"Agent prompt 为空: {key}"
        print(f"  [OK] {key}: {len(prompt)} 字符")


def test_user_prompts():
    print("\n=== Test 3: User Prompt 模板获取 ===")
    from app.services.prompts.manager import prompt_manager

    expected_keys = [
        "quality_reviewer_assessment",
        "content_creator_scene",
        "event_validator_validate",
        "style_optimizer_optimize",
        "iteration_coordinator_coordinate",
        "chapter_logic_checker_check",
    ]

    for key in expected_keys:
        prompt = prompt_manager.get_user_prompt(key)
        assert prompt, f"User prompt 为空: {key}"
        print(f"  [OK] {key}: {len(prompt)} 字符")


def test_variable_substitution():
    print("\n=== Test 4: 变量替换测试 ===")
    from app.services.prompts.manager import prompt_manager

    prompt = prompt_manager.get_user_prompt("content_creator_scene", variables={
        "scene_name": "测试场景",
        "scene_description": "这是一个测试描述",
        "characters": "张三, 李四",
        "scene_type": "对话",
        "tone": "轻松",
        "word_count": "800",
    })
    assert "测试场景" in prompt, "变量替换失败"
    print(f"  [OK] 变量替换成功, 结果长度: {len(prompt)} 字符")


def test_agent_integration():
    print("\n=== Test 5: Agent 集成测试 ===")
    from app.services.agents.agents import (
        WorldArchitectAgent,
        CharacterDesignerAgent,
        OutlinePlanParserAgent,
        CreativeDirectorAgent,
        PlotArchitectAgent,
        ContentCreatorAgent,
        QualityReviewerAgent,
        EventValidatorAgent,
        StyleOptimizerAgent,
        IterationCoordinatorAgent,
        ChapterLogicChecker,
    )

    agents = [
        ("WorldArchitectAgent", WorldArchitectAgent),
        ("CharacterDesignerAgent", CharacterDesignerAgent),
        ("OutlinePlanParserAgent", OutlinePlanParserAgent),
        ("CreativeDirectorAgent", CreativeDirectorAgent),
        ("PlotArchitectAgent", PlotArchitectAgent),
        ("ContentCreatorAgent", ContentCreatorAgent),
        ("QualityReviewerAgent", QualityReviewerAgent),
        ("EventValidatorAgent", EventValidatorAgent),
        ("StyleOptimizerAgent", StyleOptimizerAgent),
        ("IterationCoordinatorAgent", IterationCoordinatorAgent),
        ("ChapterLogicChecker", ChapterLogicChecker),
    ]

    for name, cls in agents:
        agent = cls()
        prompt = agent.get_system_prompt()
        assert prompt, f"{name} system prompt 为空"
        print(f"  [OK] {name}: {len(prompt)} 字符")


def test_hot_reload():
    print("\n=== Test 6: 热更新测试 ===")
    from app.services.prompts.manager import prompt_manager

    old_time = prompt_manager._last_load_time
    success = prompt_manager.reload()
    assert success, "热更新失败"
    assert prompt_manager._last_load_time > old_time, "热更新未刷新"
    print(f"  [OK] 热更新成功, 加载时间: {prompt_manager._last_load_time}")


def test_default_values():
    print("\n=== Test 7: 默认值变量替换 ===")
    from app.services.prompts.manager import PromptManager

    text = "Hello {name:world}! Count is {count:0}."
    result = PromptManager._replace_variables(text, {"name": "test"})
    assert result == "Hello test! Count is 0.", f"默认值替换失败: {result}"
    print(f"  [OK] 默认值替换: {result}")

    result2 = PromptManager._replace_variables(text, {})
    assert result2 == "Hello world! Count is 0.", f"无变量时应使用默认值: {result2}"
    print(f"  [OK] 无变量时使用默认值: {result2}")

    text3 = "Hello {name}!"
    result3 = PromptManager._replace_variables(text3, {})
    assert result3 == "Hello {name}!", f"无默认值且无变量时应保留原样: {result3}"
    print(f"  [OK] 无默认值且无变量保留原样: {result3}")


if __name__ == "__main__":
    print("Prompt JSON Management Integration Test")
    print("=" * 60)

    test_prompt_manager_load()
    test_agent_prompts()
    test_user_prompts()
    test_variable_substitution()
    test_agent_integration()
    test_hot_reload()
    test_default_values()

    print("\n" + "=" * 60)
    print("All tests passed!")
