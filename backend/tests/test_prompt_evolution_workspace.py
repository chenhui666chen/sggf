"""改写全文临时工作区测试：进化过程中持久化完整改写文本供取证分析，批次结束自动清理。

背景缺陷：失格 A/B 候选的评估结果只存在于内存且不落盘，历史文件中改写文本
统一截断100字，导致"事实一致性/过度改写"类硬失败无法取证对比原文与改写全文。

设计：评估器在 workspace_dir 启用时按评估批次 dump 完整记录（含提示词、原文、
改写全文、评审详情）；引擎在本批次启动时清理残留目录并创建本批次目录，
run_evolution 的 finally 阶段删除本批次目录，不积留垃圾文件。
"""
import json
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.models import EvolutionHistory
from app.services.prompt_evolution.storage import EvolutionStorage
from app.services.prompt_evolution.test_samples import TestSample


def _build_evaluator(workspace_dir):
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    # 改写返回超过100字的完整文本（历史存档截断阈值为100字）
    full_rewrite = "这是改写后的完整文本内容。" * 30
    evaluator.llm_client.chat = AsyncMock(return_value=full_rewrite)
    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 60, "ai_trace_details": {}}
    )
    evaluator.ai_detector.prepare_text = lambda t: t
    evaluator.semantic_judge = AsyncMock()
    evaluator.semantic_judge.evaluate = AsyncMock(return_value={
        "available": True, "hard_fail": False, "hard_fail_reasons": [],
        "semantic_fidelity": {"score": 95.0},
        "fact_consistency": {"score": 98.0},
        "information_completeness": {"score": 95.0},
        "readability": {"score": 90.0},
        "writing_naturalness": {"score": 90.0},
        "over_rewrite_risk": "low", "confidence": 0.9,
    })
    evaluator.workspace_dir = workspace_dir
    return evaluator, full_rewrite


@pytest.mark.asyncio
async def test_evaluator_dumps_full_rewrite_to_workspace(tmp_path):
    """启用工作区时，评估批次落盘完整改写全文与提示词（不截断）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    evaluator, full_rewrite = _build_evaluator(workspace)
    sample = TestSample(sample_id="s1", text="原文内容。" * 80, genre="科幻")

    await evaluator.evaluate_prompt("测试提示词", [sample], 0.7)

    dumps = list(workspace.glob("*.json"))
    assert len(dumps) == 1, "每次评估批次应落盘一个记录文件"
    data = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert data["prompt"] == "测试提示词"
    record = data["results"][0]
    # 改写经后处理管线可能与原始输出略有差异，核心断言：全文落盘不截断
    assert len(record["rewritten_text"]) > 100, "改写全文不得截断为100字"
    assert record["rewritten_text"] != full_rewrite[:100], "不得是100字截断存档"
    assert record["rewritten_text_length"] == len(record["rewritten_text"])
    assert record["original_text"] == sample.text, "原文应全文落盘"
    assert record["llm_review"]["fact_consistency"]["score"] == 98.0


@pytest.mark.asyncio
async def test_evaluator_without_workspace_writes_nothing(tmp_path):
    """未启用工作区时不落盘（保持既有行为）。"""
    evaluator, _ = _build_evaluator(None)
    sample = TestSample(sample_id="s1", text="原文内容。" * 80, genre="科幻")

    await evaluator.evaluate_prompt("测试提示词", [sample], 0.7)

    assert not list(tmp_path.glob("**/eval_*.json"))


def test_engine_workspace_lifecycle(tmp_path):
    """引擎：准备阶段清理残留目录并创建本批次目录；清理阶段删除本批次目录。"""
    storage = EvolutionStorage(storage_dir=str(tmp_path))
    engine = PromptEvolutionEngine(storage=storage)
    root = tmp_path / "rewrite_workspace"
    root.mkdir(exist_ok=True)
    # 模拟上一次进程被杀死遗留的残留目录
    stale = root / "stale-evolution-id"
    stale.mkdir()
    (stale / "eval_1.json").write_text("{}", encoding="utf-8")

    engine.history = EvolutionHistory()
    engine._prepare_rewrite_workspace()

    batch_dir = root / engine.history.evolution_id
    assert batch_dir.is_dir(), "应创建本批次工作区目录"
    assert engine.evaluator.workspace_dir == batch_dir
    assert not stale.exists(), "不属于本批次的残留目录应被清理"

    (batch_dir / "eval_1.json").write_text("{}", encoding="utf-8")
    engine._cleanup_rewrite_workspace()

    assert not batch_dir.exists(), "批次结束应删除本批次工作区"
    assert engine.evaluator.workspace_dir is None
