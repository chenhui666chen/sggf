# -*- coding: utf-8 -*-
"""P36 真实行为验证：模拟 DeepSeek 欠费，验证 review 会自动切到备选。

不是静态断言 —— 实际跑一遍注册表的选择逻辑：
1. 正常态：review 选中 deepseek-pro（priority=1）
2. 模拟连续 5 次 insufficient_quota 后：review 选中 doubao-seed-evolving
3. 验证 provider 不同源
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import yaml  # noqa: E402

from core.unified_registry import UnifiedModelRegistry  # noqa: E402
from schemas.unified_model_spec import (  # noqa: E402
    DispatchStrategy, UnifiedModelSpec,
)

REVIEW = "review"
PRIMARY = "deepseek-pro"
BACKUP = "doubao-seed-evolving"

results = []


def check(label, cond, detail=""):
    results.append((label, cond, detail))
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def build_registry() -> UnifiedModelRegistry:
    data = yaml.safe_load(
        (REPO_ROOT / "config/llm_models.yaml").read_text(encoding="utf-8"))
    reg = UnifiedModelRegistry()
    for md in data["llm_models"]:
        reg.register(UnifiedModelSpec.from_dict(md))
    return reg


print("=== 1. review 候选池 ===")
reg = build_registry()
pool = [s.id for s in reg.get_models_for_task(REVIEW)]
check("review 池至少 2 个模型", len(pool) >= 2, f"实际: {pool}")
check("主模型在池内", PRIMARY in pool)
check("备选在池内", BACKUP in pool, f"备选={BACKUP}")

print("\n=== 2. 正常态选择 ===")
best = reg.select_best_model(REVIEW, DispatchStrategy.AUTO)
check("正常态选主模型", best is not None and best.id == PRIMARY,
      f"实际: {best.id if best else None}")

print("\n=== 3. 模拟 DeepSeek 欠费（连续 5 次 insufficient_quota）===")
threshold = None
for mid, brk in reg._circuit_breakers.items():
    if mid == PRIMARY:
        threshold = brk.FAILURE_THRESHOLD
check("熔断阈值可读", threshold is not None, f"FAILURE_THRESHOLD={threshold}")

for i in range(threshold):
    reg.record_failure(PRIMARY, "insufficient_quota")

breaker = reg._circuit_breakers.get(PRIMARY)
check("熔断已打开", breaker is not None and breaker.is_open,
      f"failure_count={breaker.failure_count if breaker else 'N/A'}")
check("主模型已不可用", not reg._is_available(PRIMARY))

print("\n=== 4. 欠费后 review 的选择（关键验证）===")
after = reg.select_best_model(REVIEW, DispatchStrategy.AUTO)
check("已切到备选模型", after is not None and after.id == BACKUP,
      f"实际: {after.id if after else None}")
check("不再选欠费的主模型", after is not None and after.id != PRIMARY)

print("\n=== 5. provider 不同源 ===")
raw = yaml.safe_load(
    (REPO_ROOT / "config/llm_models.yaml").read_text(encoding="utf-8"))
pm = {m["id"]: m for m in raw["llm_models"]}
check("provider 不同源", pm[PRIMARY]["provider"] != pm[BACKUP]["provider"],
      f"{PRIMARY}={pm[PRIMARY]['provider']} vs {BACKUP}={pm[BACKUP]['provider']}")

print("\n=== 6. 备选自身也有兜底 ===")
fb = (pm[BACKUP].get("routing") or {}).get("fallback_models") or []
check("备配有第三层兜底", bool(fb), f"fallback={fb}")

failed = [r for r in results if not r[1]]
print("\n" + "=" * 60)
print(f"总计{len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
if failed:
    for label, _, detail in failed:
        print(f"  FAIL: {label} {detail}")
    sys.exit(1)
print("全部通过 —— 余额耗尽时 review 会自动切到 doubao-seed-evolving")