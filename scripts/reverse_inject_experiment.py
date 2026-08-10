# -*- coding: utf-8 -*-
"""朱雀反向隔离实验：99分 AI 基线 + 单维度人味化，测各降分杠杆真实权重。

与 human_detect_experiment.py（0分真人底本+AI特征注入）互为镜像：
本实验回答"人味特征注入到高分 AI 文本上各自能降多少分"，
直接指导元优化器的策略方向（全文质地转换 vs 局部技巧）。

维度：
  H1 句式口语化     —— 近边界基线的主杠杆；实测 99 分深区单做无效（99→99）
  H2 不完美感注入   —— 冗余/自我修正；实测 99 分深区单做无效（99→99）
  H3 语域混搭       —— 实测 99 分深区单做无效（99→98）
  H4 名词近义替换   —— 对照组，实测分数不变（99→99）

用法：
  python scripts/reverse_inject_experiment.py             # dry-run：打印计划与预计调用
  python scripts/reverse_inject_experiment.py --apply     # 实际执行（4次改写+5次检测）
  附加参数：--sample=0（样本序号0-9）--dims=H1,H2
  需要 PYTHONPATH=backend（独立脚本调用 app.services）
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SAMPLES_PATH = ROOT / "backend" / "app" / "services" / "prompt_evolution" / "default_samples_3000.json"
OUT_TXT = ROOT / "tmp" / "reverse_inject_report.txt"
OUT_JSON = ROOT / "tmp" / "reverse_inject_report.json"

REWRITE_PREFIX = (
    "你是中文小说改写器。对给定原文只执行下面这一条指定操作，"
    "其余一切（事实、情节、专名、其余措辞）保持不变。"
    "改写后篇幅与原文一致（偏差不超过20%），不得删句删段。只输出改写后的正文。\n\n"
)

DIM_INSTRUCTIONS = {
    "H1": "【唯一操作：句式口语化】在题材语域内把书面化长句改为短句节奏，优先常见动词，少用成语四字格；不加方言和网络用语。",
    "H2": "【唯一操作：注入表达不完美】在不改变事实的前提下，加入少量自然冗余与自我修正语气（先给出一个说法再轻补充或修正），避免过度流畅；不新增情节。",
    "H3": "【唯一操作：语域混搭】在同一段落内交替使用文学化表达与平实口语表达，雅俗穿插；不改变事实与情绪方向。",
    "H4": "【唯一操作：名词近义替换】只把部分普通名词替换为近义名词（人物专名、功法、地名保持不变），句式与其余措辞尽量不动。",
}

DIM_DESC = {
    "H1": "句式口语化（已知主杠杆）",
    "H2": "不完美感注入（待验证）",
    "H3": "语域混搭（待验证）",
    "H4": "名词近义替换（对照组）",
}


def load_sample(idx: int) -> dict:
    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    if not 0 <= idx < len(samples):
        raise SystemExit(f"样本序号越界: {idx}（共{len(samples)}条）")
    return samples[idx]


async def rewrite(client, text: str, instruction: str) -> str:
    return await client.chat(
        messages=[
            {"role": "system", "content": "你严格执行单维度改写指令，只输出正文。"},
            {"role": "user", "content": REWRITE_PREFIX + instruction + "\n\n【原文】\n" + text},
        ],
        temperature=0.7,
        max_tokens=8192,
    )


async def run(sample: dict, dims):
    from app.services.tencent_ai_detect import TencentAIDetectService
    from core.unified_llm_client import get_llm_client

    service = TencentAIDetectService()
    if not service.secret_id or not service.secret_key:
        raise SystemExit("错误：腾讯云密钥未配置")
    client = get_llm_client()
    text = sample["text"]
    base_len = len(text)
    results = []

    base = await service.detect_ai_content(text)
    results.append({"id": "基线", "dim": DIM_DESC.get("base", "AI基线"),
                    "ai_score": base.get("ai_score"), "success": base.get("success"),
                    "len": base_len, "ratio": 1.0, "error": base.get("error")})
    print(f"[基线] score={base.get('ai_score')} len={base_len}", flush=True)
    if not base.get("success"):
        raise SystemExit(f"基线检测失败: {base.get('error')}")

    for d in dims:
        inst = DIM_INSTRUCTIONS[d]
        try:
            variant = (await rewrite(client, text, inst)).strip()
        except Exception as exc:
            results.append({"id": d, "dim": DIM_DESC[d], "ai_score": None,
                            "success": False, "error": f"改写失败: {exc}"})
            print(f"[{d}] 改写失败: {exc}", flush=True)
            continue
        ratio = len(variant) / base_len
        det = await service.detect_ai_content(variant)
        results.append({"id": d, "dim": DIM_DESC[d], "ai_score": det.get("ai_score"),
                        "success": det.get("success"), "len": len(variant),
                        "ratio": round(ratio, 2), "keywords": det.get("keywords"),
                        "error": det.get("error")})
        print(f"[{d}] score={det.get('ai_score')} len={len(variant)} ratio={ratio:.2f}", flush=True)
        await asyncio.sleep(1)
    return results


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    idx = int(next((a.split("=")[1] for a in args if a.startswith("--sample=")), "0"))
    dims = next((a.split("=")[1].split(",") for a in args if a.startswith("--dims=")),
                list(DIM_INSTRUCTIONS))

    sample = load_sample(idx)
    n_calls = len(dims) + 1
    lines = ["=== 朱雀反向隔离实验（AI基线 + 单维度人味化） ===",
             f"样本: {sample['sample_id']} 题材={sample.get('genre')} 长度={len(sample['text'])}字",
             f"预计调用: 改写{len(dims)}次 + 检测{n_calls}次"]
    for d in dims:
        lines.append(f"[{d}] {DIM_DESC[d]}")
    if not apply:
        lines.append("（dry-run：加 --apply 实际执行）")
        OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines), flush=True)
        return

    results = asyncio.run(run(sample, dims))
    base_score = results[0]["ai_score"]
    lines += ["", f"=== 结果（基线 {base_score} 分） ===",
              f"{'case':6s} {'维度':22s} 分数  Δ     长度比"]
    for r in results:
        sc = r["ai_score"] if r.get("success") else f"ERR:{r.get('error')}"
        delta = "-" if r["id"] == "基线" or not isinstance(sc, (int, float)) else f"{sc - base_score:+.0f}"
        lines.append(f"{r['id']:6s} {r['dim']:22s} {str(sc):5s} {delta:5s} {r.get('ratio', '-')}")
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines[-(len(results) + 2):]), flush=True)
    print(f"报告：{OUT_TXT}", flush=True)


if __name__ == "__main__":
    main()
