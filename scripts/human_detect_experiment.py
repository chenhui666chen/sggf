# -*- coding: utf-8 -*-
"""朱雀特征隔离实验：0分真人基线 + 单维度注入。

方法：对已确认朱雀0分的真人文本做单维度确定性注入，送检观察分数变化，
隔离验证各特征对 AI 率的独立影响（复用既往"0分基线+单维度注入"方法）。

维度：
  A 升华结尾     —— 追加哲理化收尾（已知最强升分项，0分真人底本复验）
  B 套路句型注入 —— 插入4条AI腔意象句（预期升分）
  C 名词近义替换 —— 仅替换名词/专名近义项（对照组，预期分数不变）
  D 语域净化     —— 俗语口语词替换为书面语（检验语域混搭假设）

用法：
  python tmp/human_detect_experiment.py            # dry-run：列出全部变体与预计调用次数
  python tmp/human_detect_experiment.py --apply    # 实际送检（按次计费）
  附加参数：--dims A,B --texts 02,03 --verify-baseline
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASE_DIR = ROOT / "data" / "prompt_evolution" / "human_baselines"
OUT_TXT = ROOT / "tmp" / "human_detect_report.txt"
OUT_JSON = ROOT / "tmp" / "human_detect_report.json"

# ---------------- 注入定义（确定性字符串操作） ----------------

SUB_LIM_02 = "\n\n或许，这就是生命给予我最真实的馈赠：孤独从来不是匮乏，而是灵魂为自己开辟出的、得以深深扎根的土地。"
SUB_LIM_03 = "\n\n也许，含蓄正是岁月留给深情者最后的尊严：真正的爱，从不需要喧哗来证明自己的存在。"

FORMULA_02 = [
    "斑驳的光影落在岁月的书页上。",
    "情绪像一张细密的网，悄无声息地笼罩住心脏。",
    "一股暖流从心底蔓延开来。",
    "那一刻，孤独像潮水般将我温柔包裹。",
]
FORMULA_03 = [
    "时光仿佛在这一刻静止了。",
    "那份深情，像一张细密的网，悄悄笼罩在岁月之上。",
    "斑驳的光影里，藏着说不出口的温柔。",
    "一种莫名的感动，从心底缓缓蔓延开来。",
]

# C 组：仅名词替换，语义/词性/语境等价
NOUN_02 = [("学校", "校园"), ("讲座", "报告"), ("午饭", "中餐"),
           ("朋友", "友人"), ("向日葵", "葵花"), ("博客", "随笔专栏")]
NOUN_03 = [("生日礼物", "寿礼"), ("情书", "信札"), ("窗户纸", "窗纸"),
           ("羽翼未丰的小鸟", "尚未长全羽毛的雀儿"), ("送玫瑰", "送鲜花")]

# D 组：俗语/口语词 -> 书面语（语域净化）
REG_02 = [("好招儿", "好办法"), ("狗屁歌词", "粗浅的歌词"),
          ("风流成性的老不死", "风流倜傥的前辈"), ("烂书", "平庸之作")]
REG_03 = [("三陪嫖娼的票据报销", "风月开销的票据报销"), ("席梦思", "软床"),
          ("酸词", "情话"), ("露水姻缘", "短暂情缘"), ("杯水风波", "细微波澜")]


def _replace_all(text: str, pairs):
    detail = []
    for old, new in pairs:
        n = text.count(old)
        assert n > 0, f"替换源缺失: {old}"
        text = text.replace(old, new)
        detail.append(f"{old}→{new}×{n}")
    return text, "；".join(detail)


def _insert_formulas(text: str, formulas, sep: str):
    """将套路句依次插入前 N 个段落分隔处之后。"""
    parts = text.split(sep)
    assert len(parts) > len(formulas), "段落分隔不足，无法插入"
    for i, f in enumerate(formulas):
        parts[i + 1] = f + sep + parts[i + 1]
    return sep.join(parts), "插入%d条套路句" % len(formulas)


def build_cases():
    t02 = (BASE_DIR / "02_liuyu_gudu.txt").read_text(encoding="utf-8").strip()
    t03 = (BASE_DIR / "03_xiaofuxing_hanxu.txt").read_text(encoding="utf-8").strip()
    cases = []  # (case_id, dim, text_id, desc, text, change_detail)

    def add(cid, dim, tid, desc, text, detail):
        cases.append({"id": cid, "dim": dim, "text": tid, "desc": desc,
                      "variant": text, "change": detail,
                      "len_base": None, "len_var": len(text)})

    # A 升华结尾
    add("02-A", "A升华结尾", "02", "追加哲理化结尾", t02 + SUB_LIM_02, "尾部追加约50字升华句")
    add("03-A", "A升华结尾", "03", "追加哲理化结尾", t03 + SUB_LIM_03, "尾部追加约45字升华句")
    # B 套路句型
    tb2, d2 = _insert_formulas(t02, FORMULA_02, "---")
    add("02-B", "B套路句型", "02", "插入4条AI腔意象句", tb2, d2)
    # 03 按换行段落插入
    lines = t03.split("\n")
    insert_at = [4, 6, 8, 10]  # 正文段落之间
    assert len(lines) > max(insert_at), "03段落数不足"
    for i, f in zip(insert_at, FORMULA_03):
        lines.insert(i, f)
    add("03-B", "B套路句型", "03", "插入4条AI腔意象句", "\n".join(lines), "插入4条套路句")
    # C 名词替换
    tc2, dc2 = _replace_all(t02, NOUN_02)
    add("02-C", "C名词替换", "02", "名词近义替换（对照组）", tc2, dc2)
    tc3, dc3 = _replace_all(t03, NOUN_03)
    add("03-C", "C名词替换", "03", "名词近义替换（对照组）", tc3, dc3)
    # D 语域净化
    td2, dd2 = _replace_all(t02, REG_02)
    add("02-D", "D语域净化", "02", "俗语口语词→书面语", td2, dd2)
    td3, dd3 = _replace_all(t03, REG_03)
    add("03-D", "D语域净化", "03", "俗语口语词→书面语", td3, dd3)

    base_len = {"02": len(t02), "03": len(t03)}
    for c in cases:
        c["len_base"] = base_len[c["text"]]
    return {"02": t02, "03": t03}, cases


def filter_cases(cases, dims, texts):
    out = []
    for c in cases:
        if dims and not any(c["dim"].startswith(d) for d in dims):
            continue
        if texts and c["text"] not in texts:
            continue
        out.append(c)
    return out


async def detect(service, text: str) -> dict:
    return await service.detect_ai_content(text)


async def run(cases, baselines, verify_baseline):
    from app.services.zhuque_ai_detect import ZhuqueAIDetectService
    service = ZhuqueAIDetectService()
    if not service.gateway_url or not service.api_key:
        print("错误：朱雀网关未配置（ZHUQUE_GATEWAY_URL / ZHUQUE_API_KEY）", flush=True)
        sys.exit(1)

    results = []
    if verify_baseline:
        for tid in sorted(baselines):
            r = await detect(service, baselines[tid])
            results.append({"id": f"{tid}-基线", "dim": "基线", "text": tid,
                            "ai_score": r.get("ai_score"), "success": r.get("success"),
                            "keywords": r.get("keywords"), "error": r.get("error"),
                            "hit_type": r.get("hit_type")})
            await asyncio.sleep(1)

    for c in cases:
        r = await detect(service, c["variant"])
        results.append({"id": c["id"], "dim": c["dim"], "text": c["text"],
                        "change": c["change"],
                        "ai_score": r.get("ai_score"), "success": r.get("success"),
                        "keywords": r.get("keywords"), "error": r.get("error"),
                        "hit_type": r.get("hit_type")})
        print(f"[{c['id']}] score={r.get('ai_score')} err={r.get('error') or ''}", flush=True)
        await asyncio.sleep(1)
    return results


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    dims = next((a.split("=")[1].split(",") for a in args if a.startswith("--dims=")), None)
    texts = next((a.split("=")[1].split(",") for a in args if a.startswith("--texts=")), None)
    verify_baseline = "--verify-baseline" in args

    baselines, cases = build_cases()
    cases = filter_cases(cases, dims, texts)

    lines = ["=== 朱雀特征隔离实验（0分真人基线 + 单维度注入） ==="]
    n_calls = len(cases) + (len(baselines) if verify_baseline else 0)
    lines.append(f"预计检测调用次数：{n_calls}（按次计费）")
    for c in cases:
        lines.append(f"[{c['id']}] {c['dim']} | {c['len_base']}字→{c['len_var']}字 | {c['change']}")
    if not apply:
        lines.append("（dry-run：加 --apply 实际送检）")
        OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines), flush=True)
        return

    results = asyncio.run(run(cases, baselines, verify_baseline))
    lines.append("")
    lines.append("=== 检测结果（基线0分） ===")
    lines.append(f"{'case':8s} {'维度':12s} 分数  命中关键词")
    for r in results:
        kw = ",".join(r.get("keywords") or []) or "-"
        sc = r["ai_score"] if r.get("success") else f"ERR:{r.get('error')}"
        lines.append(f"{r['id']:8s} {r['dim']:12s} {str(sc):5s} {kw}")
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines[-(len(results) + 2):]), flush=True)
    print(f"报告：{OUT_TXT}", flush=True)


if __name__ == "__main__":
    main()
