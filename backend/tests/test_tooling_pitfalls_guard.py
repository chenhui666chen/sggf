# -*- coding: utf-8 -*-
"""P35：取证/驱动脚本的踩坑防线。

## 背景

P30~P34 的取证过程中，同一类错误反复出现且**每次都浪费整轮实测时间**：
把「失联」当成「失败」、把「状态完成」当成「任务结束」、
把凭据过期当成后端故障。这些都不是业务代码的问题，而是**驱动层判据错误**。

本守卫把这些判据固化成可执行的测试，
因为它们描述的是**易复发且代价高（一次 30~50 分钟实测）**的经验。

## 清理说明（2026-10-17）

原 `scripts/p30_batch_driver.py` / `p30_issue_watch.py` / `p30_summarize.py`
已在任务收尾时删除（一次性工具，结论已固化到记忆与本测试）。
本测试引用它们时会跳过而非失败 ——
工具已移除，但**判据知识必须留档**。
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
SCRIPTS = BACKEND / "scripts"


def _read(name: str) -> str | None:
    p = SCRIPTS / name
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


class TestDriverScriptsRemovedAfterUse:
    """一次性取证脚本在任务收尾后应已删除（保持工作目录干净）。"""

    def test_p30_scripts_are_gone(self):
        for name in ("p30_batch_driver.py", "p30_followup_runner.py",
                     "p30_issue_watch.py", "p30_summarize.py"):
            assert not (SCRIPTS / name).exists(), (
                f"{name} 是一次性取证工具，收尾时应删除"
            )

    def test_no_token_files_left(self):
        """临时凭据绝不能留在工作目录里。"""
        for pat in (".p30_token", ".p29_token", ".p20_token"):
            assert not (SCRIPTS / pat).exists(), f"临时凭据 {pat} 未清理"


class TestTokenExpiryLessons:
    """token 有效期 30 分钟，单轮进化必然过期 —— 记为可执行断言。"""

    def test_ttl_matches_measured_behaviour(self):
        """实测：首跑恰在 30 分钟后开始 401。

        取证来自登录响应的 `Set-Cookie: __Host-access_token=...; Max-Age=1800`。
        这个数字必须与「单轮进化耗时 20~30 分钟」对照——
        意味着**任何长轮次驱动都必须能自动重登**。
        """
        from app.core.config import settings
        assert settings.JWT_ACCESS_EXPIRATION_MINUTES == 30, (
            "access token 有效期变了 —— 长轮次驱动的重登时机需同步调整"
        )
        assert settings.JWT_ACCESS_EXPIRATION_MINUTES * 60 == 1800, (
            "Max-Age 应为 1800 秒；与实测首跑 401 时刻不符"
        )

    def test_login_response_puts_token_in_cookie_with_prefix(self):
        """登录 token 在 Set-Cookie 里，且生产环境 cookie 名带 `__Host-` 前缀。

        第一版重登实现按 `access_token` 找 cookie，取不到 token ——
        因为实测跑批环境返回的名字是 `__Host-access_token`。
        注意：COOKIE_PREFIX 是**环境相关**的（development 为空串，
        production/staging 才带前缀），所以断言的是「前缀拼接机制」，
        不能把前缀值硬断言成恒定。
        """
        from app.core.config import settings
        from app.core.security import access_cookie_name, refresh_cookie_name

        # 机制：cookie 名 = COOKIE_PREFIX + 固定后缀
        assert access_cookie_name() == f"{settings.COOKIE_PREFIX}access_token"
        assert refresh_cookie_name() == f"{settings.COOKIE_PREFIX}refresh_token"
        # 前缀只允许两种取值（config.py:144 的注释明确了这个分支）
        assert settings.COOKIE_PREFIX in ("", "__Host-"), (
            f"cookie 前缀出现第三种取值：{settings.COOKIE_PREFIX!r}"
        )
        # 非空时必须就是 __Host-（浏览器安全前缀，写死了别改）
        if settings.COOKIE_PREFIX:
            assert access_cookie_name() == "__Host-access_token", (
                "生产环境 cookie 名变了 —— 驱动脚本按硬编码名取 token 会静默取空"
            )

        # 真正可断言的是：项目里不应有把 token 硬编码的脚本
        leftover = [
            f for f in SCRIPTS.glob("*.py")
            if re.search(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", f.read_text(
                encoding="utf-8", errors="ignore"))
        ]
        assert not leftover, f"疑似硬编码 JWT：{[f.name for f in leftover]}"


class TestCompletionCriteriaLessons:
    """结束判据必须同时看 status 与 is_running。"""

    # `status=completed` 时后台 asyncio task 仍在跑多模型终评。
    # 后果：只看 status 就启动下一轮 ⇒ 撞 400 或 409。
    # 两者**含义不同**：400 要等任务结束，409 只需等冷却过。
    DONE_STATUSES = ("completed", "failed", "error", "stopped")

    def test_completed_status_appears_in_payload_but_is_not_end_signal(self):
        """`completed` 与「任务结束」是两件事，必须同时看 is_running。"""
        from app.api.v1 import prompt_evolution as api_mod
        src = inspect.getsource(api_mod)
        assert "已有进化任务正在运行" in src, "400 分支的文案变了，需复核"
        assert "冷却期" in src, "409 分支的文案变了，需复核"
        # 两个错误码语义不同，绝不能合并成一个判断
        assert "status_code=400" in src.replace(" ", ""), "400 分支消失了"
        assert src.count("status_code=409") >= 2, (
            "409 分支应至少两处（启动 + 终评），少了说明被改坏"
        )

    def test_driver_must_check_is_running_flag(self):
        """删掉的驱动脚本曾只用 status 判结束 ⇒ 漏等终评。

        留档方式：直接锁定 `is_running` 的判定表达式。
        `status=completed` 时后台 asyncio task 仍在跑终评，
        只有 `_running_task.done()` 为真才是真正的结束信号。
        """
        from app.api.v1 import prompt_evolution as api_mod
        src = inspect.getsource(api_mod)
        assert "is_running = _running_task is not None and not _running_task.done()" in src, (
            "is_running 的判定口径变了 —— 依赖它的驱动脚本需重新评估"
        )
        # 状态字段与运行标志必须**同时**出现在状态响应里
        assert re.search(r"class EvolutionStatusResponse[\s\S]{0,600}is_running: bool", src), (
            "EvolutionStatusResponse 缺 is_running 字段"
        )
        # 终态回查分支：history 跑满但 task 未 done 时不得标记为失败
        assert '_running_task.done()' in src

    def test_cooldown_is_sixty_seconds(self):
        """冷却期 60 秒 —— 决定驱动脚本要不要自动重试。"""
        import app.services.ai_trace_storage as m
        from app.services.ai_trace_storage import BackgroundOptimizationCoordinator
        # 默认值 60.0：小于它就重试等待，大于它就白等
        assert m.BackgroundOptimizationCoordinator.__init__.__defaults__ is not None
        # 更可靠的来源：构造签名里的默认参数
        import inspect as _inspect
        sig = _inspect.signature(BackgroundOptimizationCoordinator.__init__)
        assert sig.parameters["cooldown_seconds"].default == 60.0, (
            "冷却期默认值变了 —— 驱动脚本的重试间隔需同步调整"
        )
        # 全局单例也用同一口径（coordinator.try_start 走的就是这个）
        src = inspect.getsource(m)
        assert "cooldown_seconds: float = 60.0" in src


class TestIssueWatcherPatternsNotOverBroad:
    """日志监控器的模式不得过宽（曾 100% 误报）。"""

    def test_bare_number_patterns_are_absent(self):
        """429 必须是 HTTP 状态码，不能是裸子串。

        实测：`r"429|rate_limited"` 在 1387 行日志里报 6 次，
        全部是噪音 —— 4 处是**日志时间戳毫秒**（10:27:30,429），
        2 处是检测数值（'0': 0.429）。
        """
        # 断言项目内不存在裸 429 模式（防止有人再写一个）
        offenders = []
        for f in SCRIPTS.glob("*.py"):
            body = f.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"re\.compile\([^)]*429", body):
                seg = m.group(0)
                if not re.search(r"HTTP|status|限流|Too Many|rate_limit", seg):
                    offenders.append(f"{f.name}: {seg}")
        assert not offenders, f"存在裸 429 模式：{offenders}"

    def test_bare_429_demonstrably_matches_noise_in_real_log(self):
        """用真实日志证明裸 429 会误命中（留档判据的可复现依据）。

        构造夹具而非依赖现读日志：生产日志会轮转/删除，
        但这两行噪音形态是稳定的（Python logging 的毫秒时间戳格式固定）。
        """
        noise = [
            "2026-10-17 10:27:30,429 [info] 批次推进",
            "{'detections': {'0': 0.429, '1': 0.571}}",
        ]
        bare = re.compile(r"429|rate_limited")
        for line in noise:
            assert bare.search(line), (
                f"该行本应被裸模式误命中，若不再命中说明日志格式变了：{line}"
            )
        # 合格的状态码模式必须要求上下文
        strict = re.compile(r'HTTP[/ ]?\S*\s*429|"status(?:_code)?":\s*429')
        for line in noise:
            assert not strict.search(line), f"严格模式仍误命中：{line}"
        assert strict.search('HTTP/1.1 429 Too Many Requests')

    def test_quality_threshold_diagnostics_are_expected_not_violations(self):
        """「事实一致=85.0低于90」是 P23 收敛后的**正确诊断输出**，不是漂移。

        阈值来自 SemanticJudge 常量，核对：
        MIN_SEMANTIC_FIDELITY=80 / MIN_FACT_CONSISTENCY=90
        / MIN_INFORMATION_COMPLETENESS=75
        """
        from app.services.prompt_evolution.semantic_judge import SemanticJudge
        assert SemanticJudge.MIN_SEMANTIC_FIDELITY == 80
        assert SemanticJudge.MIN_FACT_CONSISTENCY == 90
        assert SemanticJudge.MIN_INFORMATION_COMPLETENESS == 75


class TestArchiveAnalysisToolingGone:
    """取证脚本已删，但存档字段结构的知识必须留档（否则重写会再踩）。"""

    def test_archive_field_structure_documented(self):
        """朱雀三分类是**扁平字段**，不是嵌套 labels_ratio。

        第一版取证脚本按 `rec.zhuque_result.labels_ratio` 读取，
        结果全量取空却**不报错** —— 最隐蔽的一类失败。
        """
        from app.services.prompt_evolution.models import EvaluationResult
        import dataclasses
        names = {f.name for f in dataclasses.fields(EvaluationResult)}
        for key in ("rewritten_ai_ratio", "rewritten_human_ratio",
                    "rewritten_suspect_ratio"):
            assert key in names, (
                f"EvaluationResult 缺 {key} —— 取证脚本按扁平字段读取"
            )
        # 关键：不存在嵌套容器字段（若有，取证脚本会误走嵌套分支取空）
        assert "labels_ratio" not in names, (
            "若新增 labels_ratio 嵌套字段，需同步改取证脚本的读取路径"
        )
        # 扁平三字段必须能在存档 JSON 里直接命中
        archive = REPO_ROOT / "data" / "prompt_evolution" / "evolution_history.json"
        if archive.exists():
            raw = archive.read_text(encoding="utf-8")
            assert "rewritten_ai_ratio" in raw, (
                "存档里找不到扁平字段 —— 说明序列化口径变了"
            )

    def test_archive_lives_in_project_root(self):
        """存档在项目根 data/prompt_evolution/，不在 backend/data/。"""
        assert (REPO_ROOT / "data" / "prompt_evolution"
                / "evolution_history.json").exists(), "存档路径变了"
        assert not (BACKEND / "data" / "prompt_evolution").exists(), (
            "backend/data 不该存在 —— 那是错误路径遗留"
        )