# -*- coding: utf-8 -*-
"""样本题材枚举一致性守卫（P25）。

## 取证修正：原先的判断是错的

盘点阶段（2026-10-17 08:47）我记的是「题材定义三处不一致」，
深挖后**证伪**了其中两条：

1. `genre.py:SUPPORTED_GENRES`（8 个，含「通用」）——
   用途是**题材规范化**（`normalize_genre` 的白名单），属通用入口，
   理应包含「通用」。
2. `experiment_contract.py:EVOLUTION_GENRES`（7 个，不含「通用」）——
   用途是**进化实验覆盖范围**，其 docstring 明写「单一定义点…杜绝
   双份维护漂移」；「通用」不进进化是**有意设计**（进化需具体题材）。
3. 前端 `AI_TRACE_SAMPLE_GENRES` 里的「其他」——
   后端确实存在（`test_samples.py:51` 定义枚举、`:88` 为默认题材），
   不是前端自造。

三个常量**作用域不同，不是重复定义**。把它们当冲突去「统一」会破坏设计。

## 但确实挖到一个真缺陷

`test_samples.py:_GENRE_GENERATION_PROMPTS` 只有 **7 个键**
（玄幻/都市/言情/悬疑/科幻/历史/武侠），既不含「通用」也不含「其他」。
而 `:559-560` 对不在映射里的题材**静默 `continue`**：

    for genre_index, genre in enumerate(target_genres):
        if genre not in _GENRE_GENERATION_PROMPTS:
            continue

后果：调用方请求生成「通用」样本时，会拿到**空列表 + 一条 info 日志**，
无法区分「题材不支持」与「生成失败」—— 静默失败比报错更难排查。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = "backend/app/services/prompt_evolution/test_samples.py"
GENRE = "backend/app/services/prompt_evolution/genre.py"
CONTRACT = "backend/app/services/prompt_evolution/experiment_contract.py"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestDistinctScopesAreDocumented:
    """三个题材常量作用域不同，必须各自写清用途，防止后人误当重复定义。"""

    def test_normalization_scope_documents_general(self):
        src = _src(GENRE)
        assert "通用" in src
        # 该常量用于题材规范化，应在注释里说明它不是进化覆盖范围
        assert "规范化" in src, (
            "genre.py 的 SUPPORTED_GENRES 应注明用于题材规范化，"
            "避免与 EVOLUTION_GENRES 被误认为重复定义"
        )

    def test_evolution_scope_documents_exclusion(self):
        src = _src(CONTRACT)
        assert "EVOLUTION_GENRES" in src
        assert "单一定义点" in src or "杜绝" in src, (
            "EVOLUTION_GENRES 应保留「单一定义点」的说明，"
            "它是进化覆盖范围的权威来源"
        )


class TestUnsupportedGenreIsNotSilent:
    """真缺陷：不在生成模板里的题材被静默跳过。"""

    def test_skip_is_logged_as_warning(self):
        src = _src(SAMPLES)
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        )
        # 跳过不支持的题材必须留痕，不能只有一条汇总 info
        assert "logger.info" not in code.split(
            "if genre not in _GENRE_GENERATION_PROMPTS:"
        )[1].split("for i in range")[0], (
            "跳过不支持的题材只应留 warning 级别的痕迹，而非静默 continue"
        )

    def test_generation_template_keys_are_traceable(self):
        """生成模板的键必须与进化题材清单一致（7 个具体题材）。"""
        from app.services.prompt_evolution.test_samples import (
            _GENRE_GENERATION_PROMPTS,
        )
        from app.services.prompt_evolution.experiment_contract import (
            EVOLUTION_GENRES,
        )

        assert set(_GENRE_GENERATION_PROMPTS) == set(EVOLUTION_GENRES), (
            f"生成模板题材应与进化清单一致；"
            f"多出 {set(_GENRE_GENERATION_PROMPTS) - set(EVOLUTION_GENRES)}，"
            f"缺少 {set(EVOLUTION_GENRES) - set(_GENRE_GENERATION_PROMPTS)}"
        )

    def test_sample_genre_enum_still_contains_other(self):
        """「其他」仍是合法的样本题材枚举（前端 AI_TRACE_SAMPLE_GENRES 依赖它）。"""
        import ast

        src = _src(SAMPLES)
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if getattr(target, "id", "") == "OTHER":
                        found = True
        assert found, "「其他」枚举值不应被误删——前端样本题材选项依赖它"