# -*- coding: utf-8 -*-
"""去AI味 Skill 基准实验：用项目降AI引擎口径评测网络流传 skill 提示词。

评分口径完全对齐 backend/app/services/prompt_evolution：
  - 朱雀检测 ai_score（越低越好），降分幅度 = 基线分 - 改写分
  - 篇幅守门：改写长度 >= 原文 50%（拦截删文落入检测盲区的虚假降分）
  - SemanticJudge：语义保真>=80 / 事实一致>=90 / 信息完整>=75 / 过度改写风险 low

用法：
  python scripts/skill_benchmark_experiment.py             # dry-run：打印计划与预计调用
  python scripts/skill_benchmark_experiment.py --apply     # 实际执行
  附加参数：--skills=humanizer,qu_ai_wei（限定条目）--no-review（跳过语义评审省调用）
  独立运行（脚本自带 sys.path 注入，无需 PYTHONPATH=backend）
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

SAMPLES_PATH = ROOT / "backend" / "app" / "services" / "prompt_evolution" / "default_samples_3000.json"
PROMPTS_DIR = ROOT / ".tmp" / "skill_bench" / "prompts"
BASELINE_CACHE = ROOT / "tmp" / "skill_bench_baselines.json"
OUT_JSON = ROOT / "tmp" / "skill_bench_report.json"
OUT_TXT = ROOT / "tmp" / "skill_bench_report.txt"

# 与 evaluator.PromptEvaluator 一致的守门参数
MIN_REWRITE_RATIO = 0.5
SAMPLE_COUNT = 3
MIN_BASELINE_SCORE = 60
CONCURRENCY = 2
REWRITE_MAX_TOKENS = 12000

# 与 evaluator._rewrite_text 一致的信封；末尾输出约束对所有条目（含对照）统一附加
USER_TEMPLATE = (
    "请改写以下文本，降低其AI痕迹：\n\n{text}\n\n"
    "只输出改写后的完整正文，不要输出分析过程、改动说明或清单。"
)


def load_samples() -> list:
    return json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))


def load_prompts() -> dict:
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in sorted(PROMPTS_DIR.glob("*.txt"))
    }


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def ensure_baselines(service, samples: list) -> dict:
    """检测全部样本基线（带文件缓存），返回 sample_id -> 检测结果。"""
    cache = load_json(BASELINE_CACHE, {})
    for s in samples:
        sid = s["sample_id"]
        if sid in cache and cache[sid].get("success"):
            continue
        result = await service.detect_ai_content(s["text"])
        cache[sid] = result
        save_json(BASELINE_CACHE, cache)
        print(f"[基线] {sid} score={result.get('ai_score')} success={result.get('success')}", flush=True)
        await asyncio.sleep(1)
    return cache


def select_samples(samples: list, baselines: dict) -> list:
    """选 3 条基线高分且题材互异的样本。"""
    scored = [
        (baselines[s["sample_id"]].get("ai_score") or 0, s)
        for s in samples
        if baselines.get(s["sample_id"], {}).get("success")
    ]
    scored.sort(key=lambda x: -x[0])
    picked, used_genres = [], set()
    for score, s in scored:
        if score < MIN_BASELINE_SCORE:
            continue
        if s.get("genre") in used_genres:
            continue
        picked.append(s)
        used_genres.add(s.get("genre"))
        if len(picked) == SAMPLE_COUNT:
            break
    if len(picked) < SAMPLE_COUNT:  # 题材不足时按分数补齐
        for score, s in scored:
            if len(picked) >= SAMPLE_COUNT:
                break
            if s["sample_id"] not in {p["sample_id"] for p in picked}:
                picked.append(s)
    return picked


async def rewrite_once(client, prompt: str, text: str) -> str:
    from core.model_resolution import TaskType

    for _ in range(2):
        result = await client.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": USER_TEMPLATE.format(text=text)},
            ],
            temperature=0.8,
            use_cache=False,
            task_type=TaskType.REWRITE,
            max_tokens=REWRITE_MAX_TOKENS,
        )
        if result and result.strip():
            return result.strip()
    return ""


async def run_case(service, client, judge, arm: str, prompt: str, sample: dict, base_score: int, with_review: bool) -> dict:
    text = sample["text"]
    record = {
        "arm": arm,
        "sample_id": sample["sample_id"],
        "genre": sample.get("genre"),
        "baseline_score": base_score,
        "original_len": len(text),
    }
    try:
        rewritten = await rewrite_once(client, prompt, text)
    except Exception as exc:
        record.update(success=False, error=f"改写异常: {type(exc).__name__}: {exc}")
        return record
    if not rewritten:
        record.update(success=False, error="改写返回空")
        return record

    ratio = len(rewritten) / len(text)
    record.update(rewritten_len=len(rewritten), length_ratio=round(ratio, 3))
    if ratio < MIN_REWRITE_RATIO:
        record.update(success=False, error=f"篇幅守门拦截: {len(rewritten)}/{len(text)}")
        return record

    det = await service.detect_ai_content(rewritten)
    await asyncio.sleep(0.5)
    if not det.get("success"):
        record.update(success=False, error=f"检测失败: {det.get('error')}")
        return record

    new_score = det.get("ai_score")
    record.update(rewritten_score=new_score, score_reduction=base_score - new_score, success=True)

    if with_review and judge is not None:
        review = await judge.evaluate(text, rewritten, sample.get("genre", "通用"))
        record["review"] = review
        if review.get("available") and not review.get("hard_fail"):
            fid = review.get("semantic_fidelity", {}).get("score", 0)
            fact = review.get("fact_consistency", {}).get("score", 0)
            comp = review.get("information_completeness", {}).get("score", 0)
            record["quality_pass"] = (
                fid >= 80 and fact >= 90 and comp >= 75
                and review.get("over_rewrite_risk") == "low"
                and (base_score - new_score) > 10
            )
    return record


async def run(skills_filter, with_review: bool):
    from app.services.zhuque_ai_detect import ZhuqueAIDetectService
    from core.unified_llm_client import get_llm_client

    service = ZhuqueAIDetectService()
    if not service.gateway_url or not service.api_key:
        raise SystemExit("错误：朱雀网关未配置")
    client = get_llm_client()

    samples = load_samples()
    baselines = await ensure_baselines(service, samples)
    picked = select_samples(samples, baselines)
    print(f"[样本] 选用: {[(s['sample_id'], s.get('genre'), baselines[s['sample_id']]['ai_score']) for s in picked]}", flush=True)

    prompts = load_prompts()
    if skills_filter:
        prompts = {k: v for k, v in prompts.items() if k in skills_filter}

    # 项目现行提示词对照：按题材取初始提示词（含经验注入）
    from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
    optimizer = MetaOptimizer()
    for s in picked:
        prompts.setdefault(f"project_baseline[{s.get('genre')}]", optimizer.get_initial_prompt(genre=s.get("genre")))

    judge = None
    if with_review:
        from app.services.prompt_evolution.semantic_judge import SemanticJudge
        judge = SemanticJudge(client)

    report = load_json(OUT_JSON, {"cases": []})
    done_keys = {(c["arm"], c["sample_id"]) for c in report["cases"]}
    sem = asyncio.Semaphore(CONCURRENCY)
    total = len(prompts) * len(picked)
    finished = 0

    async def limited(arm, prompt, s):
        nonlocal finished
        if (arm, s["sample_id"]) in done_keys:
            return
        async with sem:
            base_score = baselines[s["sample_id"]]["ai_score"]
            rec = await run_case(service, client, judge, arm, prompt, s, base_score, with_review)
            report["cases"].append(rec)
            save_json(OUT_JSON, report)
            finished += 1
            print(
                f"[{finished}/{total}] {arm} x {s['sample_id']}: "
                f"{rec.get('baseline_score')} -> {rec.get('rewritten_score')} "
                f"({'通过' if rec.get('quality_pass') else '未过/无评审'}) "
                f"{rec.get('error', '')}",
                flush=True,
            )

    await asyncio.gather(
        *[limited(arm, prompt, s) for arm, prompt in prompts.items() for s in picked]
    )
    summarize(report, baselines)


def summarize(report: dict, baselines: dict) -> None:
    lines = ["=== 去AI味 Skill 基准测试汇总 ===",
             f"{'条目':26s} {'样本':14s} {'基线':4s} {'改后':4s} {'降幅':5s} {'长度比':6s} {'质量':4s}",
             "-" * 80]
    for c in report["cases"]:
        score = c.get("rewritten_score")
        red = c.get("score_reduction")
        q = "通过" if c.get("quality_pass") else ("未过" if "review" in c else "-")
        lines.append(
            f"{c['arm'][:26]:26s} {c['sample_id'][:14]:14s} "
            f"{str(c.get('baseline_score')):4s} {str(score):4s} "
            f"{str(red):5s} {str(c.get('length_ratio', '-')):6s} {q:4s} "
            f"{c.get('error', '')}"
        )
    # 按条目聚合
    agg = {}
    for c in report["cases"]:
        agg.setdefault(c["arm"], []).append(c)
    lines += ["", "=== 按条目聚合（仅计成功案例） ===",
              f"{'条目':26s} {'成功率':6s} {'平均降幅':8s} {'平均改后':8s} {'质量通过率':10s}"]
    for arm, cases in sorted(agg.items(), key=lambda kv: -sum(
            (c.get("score_reduction") or 0) for c in kv[1] if c.get("success")) / max(1, len(kv[1]))):
        ok = [c for c in cases if c.get("success")]
        reviewed = [c for c in cases if "review" in c]
        q_pass = [c for c in reviewed if c.get("quality_pass")]
        lines.append(
            f"{arm[:26]:26s} {len(ok)}/{len(cases)}    "
            f"{(sum(c['score_reduction'] for c in ok) / len(ok)) if ok else 0:8.1f}"
            f"{(sum(c['rewritten_score'] for c in ok) / len(ok)) if ok else 0:9.1f}"
            f"  {len(q_pass)}/{len(reviewed)}"
        )
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"报告: {OUT_TXT} / {OUT_JSON}", flush=True)


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    with_review = "--no-review" not in args
    skills_filter = next(
        (a.split("=", 1)[1].split(",") for a in args if a.startswith("--skills=")), None
    )
    prompts = load_prompts()
    if skills_filter:
        prompts = {k: v for k, v in prompts.items() if k in skills_filter}
    n_cases = len(prompts) * SAMPLE_COUNT
    lines = [
        "=== 去AI味 Skill 基准实验 ===",
        f"条目: {len(prompts)} 个 skill 提示词 + 项目对照（按题材）",
        f"样本: 从 {SAMPLES_PATH.name} 选 {SAMPLE_COUNT} 条（基线>={MIN_BASELINE_SCORE}分、题材互异）",
        f"预计调用: 基线检测<=10 + 改写{n_cases} + 朱雀检测{n_cases} + 语义评审{n_cases if with_review else 0}",
        f"条目清单: {', '.join(sorted(prompts))}",
    ]
    if not apply:
        lines.append("（dry-run：加 --apply 实际执行）")
    print("\n".join(lines), flush=True)
    if not apply:
        return
    asyncio.run(run(skills_filter, with_review))


if __name__ == "__main__":
    main()
