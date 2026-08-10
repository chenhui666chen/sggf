"""守卫测试：删除进化历史不得连带删除经验报告 + 优化器响应解析的截断取证与预算。

背景缺陷：
1. storage.delete_evolution_history 曾尝试删除 `{evolution_id}.json` 经验文件，
   但经验报告实际以 `{evolution_id}_experience.json` 命名——文件名不匹配导致
   该代码从未生效。经验报告是跨批次传承资产，应固化"删历史不动经验"的行为。
2. meta_optimizer.optimize_prompt 调用 LLM 时未显式指定 max_tokens，改进提示词
   位于响应模板末尾，输出被默认上限截断时 ===IMPROVED_PROMPT=== 段整体缺失，
   表现为"⚠️ 无法解析改进后的提示词"且无任何响应取证信息。
"""
import inspect

import pytest

from app.services.prompt_evolution import storage as storage_module
from app.services.prompt_evolution import meta_optimizer


def test_delete_history_keeps_experience_report(tmp_path):
    """删除进化历史后，对应的经验报告文件必须仍然存在。"""
    store = storage_module.EvolutionStorage(storage_dir=str(tmp_path))
    evolution_id = "evo-test-001"

    # 写入一条历史（直接操作底层 store，避免构造完整 EvolutionHistory）
    store._history_store.write([{"evolution_id": evolution_id, "status": "completed"}])
    # 按真实保存逻辑的命名写入经验报告
    report_file = store.experience_dir / f"{evolution_id}_experience.json"
    report_file.write_text('{"effective_strategies": []}', encoding="utf-8")

    assert store.delete_evolution_history(evolution_id) is True
    assert report_file.exists(), "删除历史不得连带删除经验报告（跨批次传承资产）"


def test_optimizer_chat_call_sets_explicit_max_tokens():
    """优化器 LLM 调用必须显式设置足够的 max_tokens，防止改进提示词段被截断。"""
    source = inspect.getsource(meta_optimizer.MetaOptimizer.optimize_prompt)
    assert "OPTIMIZER_RESPONSE_MAX_TOKENS" in source, (
        "optimize_prompt 应显式传入 OPTIMIZER_RESPONSE_MAX_TOKENS，避免依赖模型默认上限"
    )
    assert meta_optimizer.MetaOptimizer.OPTIMIZER_RESPONSE_MAX_TOKENS >= 8000


@pytest.mark.asyncio
async def test_unparseable_response_is_logged_with_forensics(caplog):
    """改进提示词段缺失时，日志必须包含响应长度与结尾取证，便于区分截断/格式变体。"""
    optimizer = meta_optimizer.MetaOptimizer.__new__(meta_optimizer.MetaOptimizer)
    optimizer.experience = meta_optimizer.ExperienceRecord()
    optimizer.previous_analyses = []

    # 经验段全部正常、仅 IMPROVED_PROMPT 缺失——模拟输出被截断的典型形态
    truncated_response = (
        "===EFFECTIVE_STRATEGIES===\n策略A\n===EFFECTIVE_STRATEGIES_END===\n"
        "===ANALYSIS===\n这是一段足够长的分析内容用于触发记录，超过二十个字符。\n===ANALYSIS_END===\n"
        "===IMPROVED_PROMPT===\n改进后的提示词开头，但在这里被截断"
    )

    import logging
    from app.services.prompt_evolution.meta_optimizer import logger as mo_logger

    with caplog.at_level(logging.WARNING, logger=mo_logger.name):
        improved, _ = optimizer._parse_response(truncated_response)

    assert improved == ""
    forensics = [r for r in caplog.records if "IMPROVED_PROMPT" in r.getMessage() or "响应" in r.getMessage()]
    assert forensics, "解析失败时必须输出带响应长度/结尾的取证日志"
    message = " ".join(r.getMessage() for r in forensics)
    assert "响应长度" in message or "len=" in message
