# -*- coding: utf-8 -*-
"""review 任务备选模型守卫（P36）。

## 问题（真实故障，非假设）

P30 三题材批次实测：`review` 任务 **86 次调用全部押注 DeepSeek V4 Pro**，
零备选。同期 DeepSeek 账户余额不足，产生 **123 次 `insufficient_quota`
（HTTP 402）**、100 次调用失败。

危险的不是这次失败（适配器重试消化了，存档未被污染），
而是**余额耗尽且重试全败时**：语义评审大面积失效
⇒ `MIN_SEMANTIC_FIDELITY` 等门槛拿不到输入
⇒ **质量门失准 ⇒ 好版本被误拒**。

## 根因（三层，前两层与最初判断不同，是取证推翻的）

`config/llm_models.yaml` 里 `deepseek-pro` **早已配了**
`fallback_models: ['qwen-plus']`，但它不生效。三层原因：

1. **review 候选池只有 1 个模型**（已修）
   13 个模型里只有 `deepseek-pro` 声明 `task_types` 含 `review`，
   池子里没有第二个，兜底无处可去。
   → P36 把 `doubao-seed-evolving` 加入该池（priority=2，低于主模型的 1）。

2. **熔断记账排在 `break` 之后**（已修，这是最隐蔽的一层）
   `core/model_hub.py` 的重试循环原本先`if error_code in _PERMANENT_ERROR_CODES: break`，
   再 `record_failure`。⇒ 走 break 的永久错误**永远不计入熔断**
   ⇒ `_is_available()` 恒为 true ⇒ `_select_best` 的 fallback 分支永远进不去。
   注意 `auth_error` / `invalid_request` 同样受此影响，不止余额错误。

3. **`insufficient_quota` 不在 `_PERMANENT_ERROR_CODES`**（已修）
   余额耗尽时同一 prompt 被重试满 `max_retries` 次（实测浪费 123 次）。
   它与 `record_failure` 是**并存的因果**：
   正是「不 break ⇒ 会计账」才让熔断有机会积累到阈值 5；
   若把它也改成 break 而不修第 2 点，熔断反而永远打不开。
   ⚠️ 这两处**必须同改**，单独改任何一处都无效。

## 为什么选 doubao-seed-evolving（而非配置能力分更高的 mimo-pro）

`capabilities.score` 是**配置声明值，不是实测值**。真实评测数据
（`data/prompt_evolution/model_evaluation_details.json`，115 条）推翻了它：

| 模型 | 能力分声明 | 真实调用 | 真实成功率 | 语义评审覆盖 | 准入通过 |
|---|---|---|---|---|---|
| deepseek-pro | 0.95 | 0 | — | — | — |
| **mimo-pro** | **0.94** | **0** | **从未验证** | — | — |
| **glm** | **0.93** | 8 | **0%** | **0/8** | 0 |
| step-preview | 0.88 | 8 | **0%** | 0/8 | 0 |
| **doubao-seed-evolving** | 0.93 | 14 | **100%** | **14/14** | **7（最高）** |
| qwen-plus | 0.92 | 15 | 100% | 15/15 | 2 |

`mimo-pro` 能力分 0.94 高于备选，但**从未被调用过一次**，
拿零样本的能力声明当备选依据 = 重蹈「构造理想化输入」的覆辙。
`glm` 能力分 0.93 却在真实评测中 **0% 成功**（与 `model_config.json`
的 `availability_failures` 里 glm 3~4 次失败吻合）—— 直接证伪「能力分可信」。

选 `doubao-seed-evolving` 的三条理由：
1. 真实成功率 100%（15 条中 14 条成功，0 次 error）
2. 准入通过数 7 为全场最高、平均确定AI占比 0.5877 为全场最低
3. `model_config.json` 的 `auto_best_by_genre.玄幻` **已把它评为该题材最优**
   —— 系统自身已在用真实数据做同样的判断

附加优势：provider=volcengine，与 deepseek **不同源**，
余额/限流问题天然隔离，不会一起挂。

## 守卫口径

1. `review` 候选池至少 2 个模型（消除单点）
2. 备选必须是**真实评测成功率 100%** 的模型（不接受未验证的 mimo-pro）
3. 备选 provider 必须与主模型不同源（否则同生共死）
4. `insufficient_quota` 必须触发**快速失败**而非消耗上百次无效重试
5. 余额类错误应能驱动熔断器打开，让 `_is_available` 变 false
   —— 否则第 1 条配了也不生效（这正是当前 fallback 失效的原因）
"""
from __future__ import annotations

import ast
import io
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

REGISTRY_YAML = REPO_ROOT / "config" / "llm_models.yaml"
EVAL_DETAILS = (REPO_ROOT / "data" / "prompt_evolution"
                / "model_evaluation_details.json")

REVIEW_TASK = "review"
PRIMARY = "deepseek-pro"
EXPECTED_BACKUP = "doubao-seed-evolving"

# 已知真实成功率 0% 的模型 —— 绝不能被选为任何任务的备选
KNOWN_BROKEN = {"glm", "step-preview"}
# 从未在真实评测中出现过的模型 —— 能力分不可信，不得作为备选依据
UNVERIFIED = {"mimo-pro"}


def _load_models() -> list[dict]:
    data = yaml.safe_load(io.open(REGISTRY_YAML, encoding="utf-8"))
    return data["llm_models"]


def _by_id(models: list[dict]) -> dict[str, dict]:
    return {m["id"]: m for m in models}


def _review_pool(models: list[dict]) -> list[dict]:
    out = []
    for m in models:
        tt = (m.get("routing") or {}).get("task_types") or []
        if REVIEW_TASK in tt:
            out.append(m)
    return out


def _real_success_rate() -> dict[str, tuple[int, int]]:
    """从真实评测存档统计 (成功数, 总调用数)。"""
    data = json.load(io.open(EVAL_DETAILS, encoding="utf-8"))
    rows: list[dict] = []
    if isinstance(data, dict):
        for items in data.values():
            if isinstance(items, list):
                rows.extend(x for x in items if isinstance(x, dict))
    elif isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]

    stat: dict[str, list[int]] = {}
    for r in rows:
        mid = r.get("model_id")
        if not mid:
            continue
        slot = stat.setdefault(mid, [0, 0])
        slot[1] += 1
        if r.get("success"):
            slot[0] += 1
    return {k: (v[0], v[1]) for k, v in stat.items()}


class TestReviewPoolHasNoSinglePoint:
    """核心守卫：review 不能再是单模型。"""

    def test_pool_has_at_least_two_models(self):
        pool = _review_pool(_load_models())
        ids = [m["id"] for m in pool]
        assert len(ids) >= 2, (
            f"review 候选池只有 {len(ids)} 个模型（{ids}）—— "
            f"主模型余额耗尽时无备可选，语义评审会整体失效"
        )

    def test_primary_model_is_in_pool(self):
        ids = [m["id"] for m in _review_pool(_load_models())]
        assert PRIMARY in ids, (
            f"deepseek-pro 不在 review 候选池里了：{ids} —— "
            f"它一直是 review 的实际执行者，消失说明路由被改坏"
        )

    def test_expected_backup_is_in_pool(self):
        ids = [m["id"] for m in _review_pool(_load_models())]
        assert EXPECTED_BACKUP in ids, (
            f"{EXPECTED_BACKUP} 应作为 {PRIMARY} 的备选加入 review 池，实际池：{ids}"
        )


class TestBackupMustBeRealVerified:
    """备选必须经真实评测验证 —— 配置能力分不算数。"""

    def test_backup_has_real_success_rate(self):
        rate = _real_success_rate()
        assert EXPECTED_BACKUP in rate, (
            f"{EXPECTED_BACKUP} 在真实评测存档里没有任何记录，"
            f"不能凭配置能力分当备选"
        )
        ok, total = rate[EXPECTED_BACKUP]
        assert total >= 10, (
            f"{EXPECTED_BACKUP} 真实样本仅 {total} 条，不足以证明稳定性"
        )
        assert ok == total, (
            f"{EXPECTED_BACKUP} 真实成功率 {ok}/{total}，"
            f"有失败记录，不适合当唯一备选"
        )

    def test_known_broken_models_stay_excluded(self):
        """记录已证伪模型的真实成功率，作为「能力分不可信」的活证据。

        glm / step-preview 的 capabilities.score 分别是 0.93 / 0.88，
        但真实评测成功率都是 0% —— 这条测试一旦失败，说明它们恢复了，
        届时应重新评估能否用作备选。
        """
        rate = _real_success_rate()
        for broken in KNOWN_BROKEN:
            ok, total = rate.get(broken, (0, 0))
            assert total > 0, (
                f"{broken} 在真实评测存档里没有记录了 —— "
                f"评测数据被清理，请重新核实其可用性"
            )
            assert ok == 0, (
                f"{broken} 真实成功率已变成 {ok}/{total}，"
                f"它恢复了可用性，应重新纳入备选候选并更新本守卫"
            )

    def test_capability_score_is_not_taken_as_evidence(self):
        """锁住核心教训：能力分声明 ≠ 可用性。

        mimo-pro 声明 0.94（高于备选 0.93）却零样本；
        glm 声明 0.93 却 0% 成功率。任何用 capabilities.score
        论证「某模型适合当备选」的做法都会踩这两个坑。
        """
        models = _by_id(_load_models())
        rate = _real_success_rate()

        mimo = models["mimo-pro"]
        caps = {c["name"]: c.get("score", 0) for c in (mimo.get("capabilities") or [])}
        assert caps.get("reasoning", 0) >= 0.94, (
            "mimo-pro 能力分变了 —— 若已补真实样本，应重新评估备选人选"
        )
        assert "mimo-pro" not in rate, (
            "mimo-pro 已有真实评测数据，"
            "请基于实测而非配置能力分重新确定备选"
        )

        glm_caps = {c["name"]: c.get("score", 0)
                    for c in (models["glm"].get("capabilities") or [])}
        assert glm_caps.get("reasoning", 0) >= 0.93
        ok, total = rate.get("glm", (0, 0))
        assert total > 0 and ok == 0, (
            f"glm 实测 {ok}/{total}，与它 0.93 的能力分声明严重不符 —— "
            f"这正是「不可用能力分选备选」的证据"
        )

    def test_unverified_models_are_not_used_as_backup(self):
        """mimo-pro 能力分 0.94 但零样本 —— 必须明确记录这个陷阱。"""
        rate = _real_success_rate()
        for m in UNVERIFIED:
            assert m not in rate or rate[m][1] == 0, (
                f"{m} 现已有真实样本，请重新评估它是否适合当备选"
            )
        pool = {m["id"] for m in _review_pool(_load_models())}
        assert not (pool & UNVERIFIED), (
            f"未验证模型 {pool & UNVERIFIED} 被加入了 review 池 —— "
            f"能力分是配置声明值，零样本不能作为依据"
        )


class TestBackupIsDifferentProvider:
    """备选与主模型必须不同源，否则同生共死。"""

    def test_providers_differ(self):
        models = _by_id(_load_models())
        p_main = (models[PRIMARY].get("routing") or {}), models[PRIMARY].get("provider")
        p_back = (models[EXPECTED_BACKUP].get("routing") or {}), models[EXPECTED_BACKUP].get("provider")
        assert p_main[1] != p_back[1], (
            f"主模型与备选同为 {p_main[1]} 供应商 —— "
            f"一个账户欠费会同时打掉两个，备选无意义"
        )

    def test_backup_itself_has_fallback(self):
        """备选也不能是死胡同。"""
        models = _by_id(_load_models())
        fb = (models[EXPECTED_BACKUP].get("routing") or {}).get("fallback_models")
        assert fb, (
            f"{EXPECTED_BACKUP} 作为备选却没有第三层兜底，"
            f"它挂掉后仍会回到单点"
        )


class TestQuotaErrorMustFailFast:
    """余额错误必须被识别为永久错误，而不是当瞬时故障重试。

    取证（P36，修正了此前「全库零识别」的误判）：
    - `core/llm_adapters.py:659` **确实**映射出 `insufficient_quota`
    - `core/model_hub.py` **确实**调用 `registry.record_failure`
    真正的两处缺陷是：
    1. `insufficient_quota` 不在 `_PERMANENT_ERROR_CODES` 里
       ⇒ 余额耗尽时同一 prompt 被重试满max_retries 次（实测浪费 123 次）
    2. `record_failure` 原先排在 `break` **之后**
       ⇒ 走 break 的永久错误永不计入熔断 ⇒ `_is_available` 恒 true
       ⇒ 配了 fallback_models 也永远切不到备选
    """

    def test_quota_error_is_mapped_by_adapters(self):
        from core.llm_adapters import BaseLLMAdapter  # noqa: F401
        src = io.open(REPO_ROOT / "core/llm_adapters.py", encoding="utf-8").read()
        assert 'return "insufficient_quota"' in src, (
            "适配器不再把余额错误映射成insufficient_quota —— "
            "欠费时会落unknown_error 并被当瞬时故障重试"
        )

    def test_quota_is_treated_as_permanent_error(self):
        from core.model_hub import _PERMANENT_ERROR_CODES
        assert "insufficient_quota" in _PERMANENT_ERROR_CODES, (
            "余额不足又被当瞬时故障重试了 —— 同prompt 重试不会成功，"
            "只会烧掉 max_retries 轮（实测浪费 123 次）"
        )
        assert "unknown_error" not in _PERMANENT_ERROR_CODES, (
            "unknown_error 是_ map_error_code 的兜底，"
            "真瞬时故障也会落这里，必须保留韧性"
        )

    @staticmethod
    def _retry_try_block(tree: ast.Module) -> ast.Try | None:
        """定位重试循环里那个含熔断记账的 try 块。

        注意：不能用 ast.walk 全树扫 —— 它会连`except` 子句里的
        record_failure 一起收进来（异常路径的记账是独立且必要的）。
        """
        for n in ast.walk(tree):
            if not isinstance(n, ast.For):
                continue
            for stmt in n.body:
                if isinstance(stmt, ast.Try):
                    dump = ast.dump(stmt)
                    if "record_failure" in dump and "_PERMANENT_ERROR_CODES" in dump:
                        return stmt
        return None

    def test_breaker_accounting_precedes_break(self):
        """熔断记账必须早于 break —— 否则永久错误永远打不开熔断。"""
        src = io.open(REPO_ROOT / "core/model_hub.py", encoding="utf-8").read()
        try_block = self._retry_try_block(ast.parse(src))
        assert try_block is not None, "未找到含熔断记账的重试 try 块"

        # 只看 try 主体（不含 handler），与 338 行 except 里的记账无关
        rec_line = min(
            n.lineno for stmt in try_block.body
            for n in ast.walk(stmt)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "record_failure"
        )
        break_line = min(
            n.lineno for stmt in try_block.body
            for n in ast.walk(stmt)
            if isinstance(n, ast.Break)
        )
        assert rec_line < break_line, (
            f"record_failure 在第 {rec_line} 行、break 在第 {break_line} 行 —— "
            f"永久错误 break 之后不再记账，熔断永远打不开、fallback 永远不触发"
        )

    def test_breaker_accounting_is_not_duplicated(self):
        """记账提到前面后，try 主体末尾不能留重复调用（否则熔断被加速误触）。"""
        src = io.open(REPO_ROOT / "core/model_hub.py", encoding="utf-8").read()
        try_block = self._retry_try_block(ast.parse(src))
        assert try_block is not None
        calls = [n.lineno for stmt in try_block.body
                 for n in ast.walk(stmt)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "record_failure"]
        assert len(calls) == 1, (
            f"try 主体内有 {len(calls)} 处 record_failure：{calls} —— "
            f"重复记账会让熔断阈值（5）以2 倍速度误触"
        )
        # except 分支的记账必须仍然存在（异常路径也要计入熔断）
        handler_calls = [n.lineno for h in try_block.handlers
                         for n in ast.walk(h)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "record_failure"]
        assert handler_calls, (
            "except 分支的 record_failure 被误删 —— "
            "异常路径不再计入熔断"
        )

    def test_registry_fallback_triggers_on_breaker_open(self):
        from core.unified_registry import UnifiedModelRegistry  # noqa: F401
        src = io.open(REPO_ROOT / "core/unified_registry.py", encoding="utf-8").read()
        assert "_circuit_breakers" in src, (
            "注册表失去熔断器查询能力，fallback 触发条件已失效"
        )
        assert "can_attempt" in src, (
            "熔断器判定方法缺失 —— 余额错误无法让模型变为不可用"
        )

    def test_registry_fallback_triggers_on_breaker_open(self):
        from core.unified_registry import UnifiedModelRegistry  # noqa: F401
        src = io.open(
            REPO_ROOT / "core/unified_registry.py", encoding="utf-8").read()
        assert "_circuit_breakers" in src, (
            "注册表失去熔断器查询能力，fallback 触发条件已失效"
        )
        assert "can_attempt" in src, (
            "熔断器判定方法缺失 —— 余额错误无法让模型变为不可用"
        )


class TestRegistryFallbackChainDepth:
    """兜底链必须真的能走通，而不只是配置里写着。"""

    def test_fallback_is_not_only_used_when_everything_unavailable(self):
        """记录当前 fallback 的触发条件（本守卫锁住现状，变更需复核）。"""
        src = io.open(
            REPO_ROOT / "core/unified_registry.py", encoding="utf-8").read()
        assert "所有模型都不可用" in src, (
            "fallback 触发条件已变更 —— "
            "若改为单模型不可用即兜底，需同步复核候选池与优先级排序"
        )

    def test_no_model_is_excluded_from_review_by_elimination(self):
        """确认消除名单里没有 review 池成员（被淘汰的模型不能再当备选）。"""
        cfg = REPO_ROOT / "data/prompt_evolution/model_config.json"
        if not cfg.exists():
            return
        data = json.load(io.open(cfg, encoding="utf-8"))
        eliminated = data.get("eliminated_models") or {}
        pool = {m["id"] for m in _review_pool(_load_models())}
        for genre, models in eliminated.items():
            clash = set(models or []) & pool
            assert not clash, (
                f"{genre} 题材的消除名单 {clash} 与 review 池重叠 —— "
                f"已被判定不可用的模型不能当备选"
            )