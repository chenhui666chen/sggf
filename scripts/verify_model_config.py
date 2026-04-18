#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三层模型配置校验脚本

检查 intent_domains.yaml、models.yaml、semantic_matcher.py 之间的一致性。
用法:
    python scripts/verify_model_config.py [--fix] [--verbose]
"""

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

# Fix Windows console encoding
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    os.environ["PYTHONIOENCODING"] = "utf-8"

ROOT = Path(__file__).resolve().parent.parent


# ── 配置加载 ──────────────────────────────────────────────
def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_domains():
    path = ROOT / "config" / "intent_domains.yaml"
    data = load_yaml(path)
    domains = data.get("domains", {})
    wan = domains.get("wan")
    if not wan:
        raise SystemExit("❌ intent_domains.yaml 中未找到 wan domain")
    return wan


def load_models():
    path = ROOT / "config" / "models.yaml"
    data = load_yaml(path)
    return data.get("models", [])


def load_matcher_vocab():
    path = ROOT / "core" / "semantic_matcher.py"
    src = path.read_text(encoding="utf-8")
    m = re.search(r"STYLE_VOCABULARY\s*=\s*\{([\s\S]*?)\n\}", src)
    if not m:
        raise SystemExit("❌ 无法在 semantic_matcher.py 中找到 STYLE_VOCABULARY")
    block = m.group(1)
    vocab = {}
    for entry in block.split("{"):
        if "}" not in entry:
            continue
        k_v = entry[: entry.index("}")].strip().rstrip(",")
        colon_idx = k_v.find(":")
        if colon_idx < 0:
            continue
        key = k_v[:colon_idx].strip().strip("\"'")
        list_str = k_v[colon_idx + 1 :].strip().strip("[]").strip()
        items = [i.strip().strip("\"'") for i in list_str.split(",") if i.strip()]
        vocab[key] = items
    return vocab


# ── 校验逻辑 ──────────────────────────────────────────────
class Issues:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.fixes: list[str] = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def fix(self, msg):
        self.fixes.append(msg)

    def ok(self):
        return len(self.errors) == 0 and len(self.warnings) == 0

    def report(self):
        lines = []
        if self.errors:
            lines.append(f"\n{'=' * 60}")
            lines.append(f"❌ 错误 ({len(self.errors)})")
            for e in self.errors:
                lines.append(f"  • {e}")
        if self.warnings:
            lines.append(f"\n{'=' * 60}")
            lines.append(f"⚠️  警告 ({len(self.warnings)})")
            for w in self.warnings:
                lines.append(f"  • {w}")
        if self.fixes:
            lines.append(f"\n{'=' * 60}")
            lines.append(f"🔧 建议修复 ({len(self.fixes)})")
            for f in self.fixes:
                lines.append(f"  • {f}")
        return "\n".join(lines)


def check_style_vocab(domains, matcher_vocab, issues: Issues):
    """检查1: intent_domains 风格 vs semantic_matcher 词汇"""
    domain_styles = set(domains.get("styles", {}).keys())
    matcher_styles = set(matcher_vocab.keys())

    missing_in_matcher = domain_styles - matcher_styles
    for s in sorted(missing_in_matcher):
        issues.warn(f"风格 '{s}' 在 intent_domains.yaml 中定义，但 semantic_matcher.py 的 STYLE_VOCABULARY 中缺失")

    extra_in_matcher = matcher_styles - domain_styles
    for s in sorted(extra_in_matcher):
        issues.warn(f"风格 '{s}' 在 semantic_matcher.py 中存在，但 intent_domains.yaml 的 wan domain 中未定义")

    for style in domain_styles & matcher_styles:
        domain_keywords = domains["styles"][style]
        if isinstance(domain_keywords, list):
            domain_kw_set = set(domain_keywords)
        else:
            domain_kw_set = set(domain_keywords.get("keywords", []))
        matcher_keywords = set(matcher_vocab[style])
        if domain_kw_set != matcher_keywords:
            domain_only = domain_kw_set - matcher_keywords
            matcher_only = matcher_keywords - domain_kw_set
            if domain_only or matcher_only:
                issues.warn(
                    f"风格 '{style}' 关键词不一致: "
                    f"domains有但matcher无={domain_only}, "
                    f"matcher有但domains无={matcher_only}"
                )


def check_model_tags(domains, models, issues: Issues):
    """检查2: 模型 tags 是否引用了未定义的风格"""
    domain_styles = set(domains.get("styles", {}).keys())
    model_tag_styles = set()
    for m in models:
        tags = m.get("tags", [])
        for tag in tags:
            if tag not in ("image", "video", "audio", "alibaba", "bytedance", "chinese",
                           "text-to-image", "text-to-video", "image-to-video",
                           "reference_image", "reference_video", "first_last_frame",
                           "multi_shot", "camera_control", "subject_consistency",
                           "style_transfer", "video_edit", "music", "sound_effect",
                           "fast", "pro", "realistic", "anime", "cinematic", "fantasy",
                           "high_quality"):
                model_tag_styles.add(tag)

    undefined = model_tag_styles - domain_styles
    for s in sorted(undefined):
        models_using = [m["id"] for m in models if s in m.get("tags", [])]
        issues.error(f"风格标签 '{s}' 被模型 {', '.join(models_using)} 引用，但在 intent_domains.yaml 中未定义")

    for m in models:
        if m.get("modality", [])[0] in ("text_to_image", "image_to_image"):
            style_tags = set(m.get("tags", [])) & domain_styles
            if not style_tags:
                issues.warn(f"模型 {m['id']} 没有定义任何风格标签")


def check_model_capabilities(models, issues: Issues):
    """检查3: 模型能力描述是否缺失溯源信息"""
    for m in models:
        caps = m.get("capabilities", [])
        for cap in caps:
            if not cap.get("source"):
                issues.fix(f"模型 {m['id']} 的能力 '{cap['name']}' 缺少 source 溯源字段")
            if not cap.get("verified_at"):
                issues.fix(f"模型 {m['id']} 的能力 '{cap['name']}' 缺少 verified_at 字段")
            if not cap.get("confidence"):
                issues.fix(f"模型 {m['id']} 的能力 '{cap['name']}' 缺少 confidence 字段")


def check_video_models_in_tags(domains, models, issues: Issues):
    """检查4: 视频模型是否在 domains 的 video_generation 中注册"""
    registered_video_models = {m["id"] for m in domains.get("video_generation", {}).get("models", [])}
    for m in models:
        if m.get("modality", [])[0] in ("text_to_video", "image_to_video"):
            if m["id"] not in registered_video_models:
                issues.warn(f"视频模型 {m['id']} 未在 intent_domains.yaml 的 video_generation.models 中注册")


def check_camera_terms(domains, matcher_vocab, issues: Issues):
    """检查5: 运镜术语一致性"""
    domain_terms = set(domains.get("camera_control", {}).get("terms", {}).keys())
    matcher_terms = set(matcher_vocab.get("CAMERA_VOCABULARY", {}).keys()) if "CAMERA_VOCABULARY" in matcher_vocab else set()

    if not matcher_terms:
        path = ROOT / "core" / "semantic_matcher.py"
        src = path.read_text(encoding="utf-8")
        m = re.search(r"CAMERA_VOCABULARY\s*=\s*\{([\s\S]*?)\n\}", src)
        if m:
            block = m.group(1)
            for entry in block.split("{"):
                if "}" not in entry:
                    continue
                k_v = entry[: entry.index("}")].strip().rstrip(",")
                colon_idx = k_v.find(":")
                if colon_idx < 0:
                    continue
                key = k_v[:colon_idx].strip().strip("\"'")
                matcher_terms.add(key)

    missing_camera = domain_terms - matcher_terms
    for t in sorted(missing_camera):
        issues.warn(f"运镜术语 '{t}' 在 intent_domains.yaml 中定义，但 semantic_matcher.py 的 CAMERA_VOCABULARY 中缺失")


# ── 自动修复 ──────────────────────────────────────────────
def fix_missing_capability_metadata(models, verbose=False):
    """为缺失 source/verified_at/confidence 的能力补充默认值"""
    path = ROOT / "config" / "models.yaml"
    data = load_yaml(path)
    changed = False

    for m in data.get("models", []):
        caps = m.get("capabilities", [])
        for cap in caps:
            if not cap.get("source"):
                cap["source"] = "TODO: verify from official docs"
                changed = True
            if not cap.get("verified_at"):
                cap["verified_at"] = "2026-04-17"
                changed = True
            if not cap.get("confidence"):
                cap["confidence"] = "medium"
                changed = True

    if not changed:
        print("  所有能力已具备溯源信息，无需修复")
        return

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    print(f"  已更新 {path}")


def fix_missing_styles_in_matcher(domains, verbose=False):
    """补全 semantic_matcher.py 中缺失的风格词汇"""
    path = ROOT / "core" / "semantic_matcher.py"
    src = path.read_text(encoding="utf-8")

    matcher_vocab = load_matcher_vocab()
    domain_styles = domains.get("styles", {})
    missing = {k: v for k, v in domain_styles.items() if k not in matcher_vocab}

    if not missing:
        print("  STYLE_VOCABULARY 已完整，无需修复")
        return

    print(f"\n  将补全 {len(missing)} 种缺失风格到 STYLE_VOCABULARY:")
    for style_name, style_def in missing.items():
        keywords = style_def if isinstance(style_def, list) else style_def.get("keywords", [])
        print(f"  + {style_name}: {keywords}")

    additions = []
    for style_name, style_def in missing.items():
        keywords = style_def if isinstance(style_def, list) else style_def.get("keywords", [])
        kw_str = ", ".join(f'"{k}"' for k in keywords)
        additions.append(f'    "{style_name}": [{kw_str}]')

    new_block = ",\n".join(additions)

    pattern = r"(STYLE_VOCABULARY\s*=\s*\{[\s\S]*?)(\n\})"
    match = re.search(pattern, src)
    if not match:
        print("  无法定位 STYLE_VOCABULARY 的结束位置")
        return

    insertion_point = match.end(1)
    new_src = src[:insertion_point] + ",\n" + new_block + src[insertion_point:]

    path.write_text(new_src, encoding="utf-8")
    print(f"  已写入 {path}")


def run_all_fixes(domains, models):
    """执行所有自动修复"""
    fix_missing_capability_metadata(models)
    fix_missing_styles_in_matcher(domains)


# ── 主流程 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="三层模型配置校验")
    parser.add_argument("--fix", action="store_true", help="自动修复可修复的问题")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    args = parser.parse_args()

    print("=" * 60)
    print("  三层模型配置校验工具")
    print("=" * 60)

    domains = load_domains()
    models = load_models()
    matcher_vocab = load_matcher_vocab()

    issues = Issues()

    print("\n 检查 1/5: 风格词汇一致性 (intent_domains <-> semantic_matcher)")
    check_style_vocab(domains, matcher_vocab, issues)

    print(" 检查 2/5: 模型标签引用 (models.yaml tags -> intent_domains styles)")
    check_model_tags(domains, models, issues)

    print(" 检查 3/5: 模型能力溯源 (source / verified_at / confidence)")
    check_model_capabilities(models, issues)

    print(" 检查 4/5: 视频模型注册 (models.yaml -> intent_domains video_generation)")
    check_video_models_in_tags(domains, models, issues)

    print(" 检查 5/5: 运镜术语一致性 (intent_domains camera <-> semantic_matcher)")
    check_camera_terms(domains, matcher_vocab, issues)

    print(issues.report())

    if args.fix:
        print("\n  执行自动修复...")
        run_all_fixes(domains, models)

    if issues.ok():
        print("\n 所有检查通过！")
        return 0
    else:
        print(f"\n  共发现 {len(issues.errors)} 个错误, {len(issues.warnings)} 个警告")
        return 1


if __name__ == "__main__":
    sys.exit(main())
