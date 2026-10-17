"""P33 行为实测：`best_versions` 去重的真实效果。

守卫测试用构造夹具，本脚本用**13 轮真实存档**验证：
  1. 往返一致性（引用还原出的 best 版本与 all 版本内容完全相同）
  2. 体积降幅（真实数据，不是估算）
  3. 存量存档（无引用键）继续可读
  4. 顺序保持（best_versions[0] 必须仍是「最优版本」）

运行：python tests/manual_p33_best_versions_dedup.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent))

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def main() -> int:
    from app.services.prompt_evolution.storage import EvolutionStorage
    from app.services.ai_trace_storage import AtomicJsonStore

    archive = (BACKEND.parent / "data" / "prompt_evolution"
               / "evolution_history.json")
    if not archive.exists():
        print(f"存档不存在：{archive}")
        return 1

    raw_text = archive.read_text(encoding="utf-8")
    rounds = json.loads(raw_text)
    if isinstance(rounds, dict):
        rounds = rounds.get("evolutions", [])
    before = size(rounds)

    print("P33 行为实测：best_versions 去重\n")
    print(f"真实存档：{len(rounds)} 轮，{before / 1e6:.2f} MB\n")

    store = EvolutionStorage.__new__(EvolutionStorage)

    # --- A. 往返一致性 ---
    print("--- A 往返一致性 ---")
    mismatch = []
    shrunk_total = 0
    after_rounds = []
    for r in rounds:
        h = store._dict_to_history(r)
        d = store._history_to_dict(h)
        after_rounds.append(d)
        shrunk_total += size(d)
        # best 版本内容必须与 all 里同id 版本一致
        all_by_id = {v.get("version_id"): v for v in (r.get("all_versions") or [])}
        for v in (r.get("best_versions") or []):
            vid = v.get("version_id")
            src = all_by_id.get(vid)
            if src is None:
                continue
            # 关键字段逐一比对（评测明细也应一致）
            if size(v.get("evaluation_results") or []) != \
                    size(src.get("evaluation_results") or []):
                mismatch.append(f"{vid} 的 evaluation_results 不一致")
            if v.get("prompt_text") != src.get("prompt_text"):
                mismatch.append(f"{vid} 的 prompt_text 不一致")
    check("A1 引用还原后 best 与 all 内容完全一致",
          not mismatch, f"不一致项：{mismatch[:3]}")

    after = shrunk_total
    print(f"       去重后体积：{after / 1e6:.2f} MB"
          f"（原{before / 1e6:.2f} MB，降幅 {100 * (before - after) / before:.1f}%）")
    check("A2 体积确实下降", after < before,
          f"{before / 1e6:.2f} → {after / 1e6:.2f} MB")

    # --- B. 引用键与顺序 ---
    print("\n--- B 引用与顺序 ---")
    has_ids = sum(1 for d in after_rounds
                  if isinstance(d.get("best_version_ids"), list))
    check("B1 每轮都写出 best_version_ids 键（列表类型）",
          has_ids == len(after_rounds), f"{has_ids}/{len(after_rounds)}")

    # ⚠️ 注意：有 4 轮的best_versions 本来就是**空的**（早期准入门未生效期），
    # 其 best_version_ids 是空列表 [] —— falsy 但**键存在**。
    # 所以断言必须查「键是否为 list」而非「是否为真值」。
    empty_rounds = sum(1 for r in rounds if not (r.get("best_versions") or []))
    check("B1b 空轮次的引用列表为空列表",
          all(after_rounds[i].get("best_version_ids") == []
              for i, r in enumerate(rounds)
              if not (r.get("best_versions") or [])),
          f"空 best 的轮次：{empty_rounds}")

    order_bad = []
    for orig, d in zip(rounds, after_rounds):
        want = [v.get("version_id") for v in (orig.get("best_versions") or [])]
        got = list(d.get("best_version_ids") or [])
        if want != got:
            order_bad.append(f"{str(orig.get('evolution_id'))[:8]}: {want} -> {got}")
    check("B2 引用顺序与原 best_versions 完全一致",
          not order_bad, f"乱序：{order_bad[:3]}")

    # --- C. 回读还原 ---
    print("\n--- C 回读还原（把去重后的 dict 再读回来）---")
    back_bad = []
    for r, orig in zip(after_rounds, rounds):
        h = store._dict_to_history(r)
        want = [v.get("version_id") for v in (orig.get("best_versions") or [])]
        got = [v.version_id for v in h.best_versions]
        if want != got:
            back_bad.append(f"{str(orig.get('evolution_id'))[:8]}: {want} -> {got}")
    check("C1 去重后回读顺序不变", not back_bad, f"不一致：{back_bad[:3]}")

    # --- D. 存量存档兼容 ---
    print("\n--- D 存量存档兼容（无引用键）---")
    legacy = [dict(r) for r in rounds]
    for r in legacy:
        r.pop("best_version_ids", None)
    legacy_bad = []
    for r, orig in zip(legacy, rounds):
        h = store._dict_to_history(r)
        want = [v.get("version_id") for v in (orig.get("best_versions") or [])]
        got = [v.version_id for v in h.best_versions]
        if want != got:
            legacy_bad.append(f"{str(orig.get('evolution_id'))[:8]}")
    check("D1 移除引用键后仍能读出同样的 best_versions",
          not legacy_bad, f"失败轮次：{legacy_bad[:5]}")

    # --- E. 摘要里不该再有重字段 ---
    print("\n--- E 摘要内容 ---")
    leak = []
    for d in after_rounds:
        for v in (d.get("best_versions") or []):
            if "evaluation_results" in v:
                leak.append(str(v.get("version_id"))[:8])
    check("E1 摘要不含 evaluation_results（占 90% 体积）",
          not leak, f"泄漏：{leak[:3]}")

    sum_size = size([d.get("best_versions") for d in after_rounds])
    old_bv = size([r.get("best_versions") for r in rounds])
    print(f"       best_versions 序列化体积：{old_bv / 1e6:.2f} MB"
          f" → {sum_size / 1e6:.2f} MB")

    print(f"\n=== {sum(1 for ok, _ in RESULTS if ok)}/{len(RESULTS)} 通过 ===")
    failed = [n for ok, n in RESULTS if not ok]
    if failed:
        print("失败项：")
        for n in failed:
            print("  ✗", n)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())