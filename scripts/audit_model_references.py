#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型 ID 引用审计工具（只读，不发起任何远程调用）。

用途：模型完全替换或退役时，给出旧 ID 在全仓的分层引用清单，作为"删干净了没有"的
客观判据。人工 rg 子串检索不可靠——例如搜 `mimo-v2.5` 会连带命中仍在线上使用的
`mimo-v2.5-tts`，本脚本一律用词边界精确匹配。

检查项：
1. 分层引用统计：config / adapters / core / backend / frontend / pipeline /
   scripts / tests / agents / 根文件，逐层给出命中数与 file:line。
2. 结构体检：
   - adapters/registry.py 自动导入清单里的模块文件是否都存在（该处 import 被
     try/except 吞掉，模块缺失不会报错，只会静默不注册）
   - 同一 model ID 是否被多个 @register_model / @register_llm_model 注册
   - 是否存在同名适配器类（跨文件重名会让"哪个实现在跑"不可判断）
     注：同名类只作提示、不计入门禁——adapters/model_adapters.py 是保留的旧式门面，
     其中重名类不带注册装饰器，不参与注册中心。
3. 已弃用条目盘点：两份 YAML 里 status=deprecated 的条目及其替代目标。
   注：本项目 2026-10-09 起采用"退役即物理删除"，YAML 常态不存在 deprecated 条目，
   因此盘点退役 ID 请用 --all-retired（事实源是 tests/ 下的退役登记表）。
4. 命中分类：每条命中区分「待改残留」与「合法记录」。合法记录只有三类——
   记录性文件（退役登记表、改写工具、带日期的实验记录）、上游真名（wire name，
   如 request_model 与 model="真名"）、与旧 ID 同名的引擎标识符（DreamWeaver 档位）。
   判据见 WIRE_NAME_CONTEXT_RE / ENGINE_IDENTIFIER_CONTEXT_RE 的注释。
5. 环境变量文件取值扫描：`.env` 被 gitignore，git 清单永远取不到它，曾导致"门禁归零
   而 .env 里仍留着已退役 ID"。现将 env 纳入扫描范围，只解析模型名类键的取值，
   并遵守两条安全约束：带密钥语义的键（KEY/SECRET/TOKEN/...）一律跳过，
   命中项只重建 `KEY=值` 而**不保留整行原文**（同行注释与相邻行都可能是密钥）。
   若 env 取值确实是发给供应商的上游真名，需在行尾注释里写"上游线名"，重建行会带上该
   标记并按线名放行；纯数字值（平台侧资源 ID）与非模型键不参与。

示例：
    python scripts/audit_model_references.py                       # 只做结构体检与 deprecated 盘点
    python scripts/audit_model_references.py --all-retired
    python scripts/audit_model_references.py --all-retired --expect-zero
    python scripts/audit_model_references.py --model-id wan2.7-i2v --model-id step-3.7-flash
    python scripts/audit_model_references.py --model-id wan2.7-t2v --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIA_CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"
LLM_CONFIG_PATH = PROJECT_ROOT / "config" / "llm_models.yaml"
REGISTRY_PATH = PROJECT_ROOT / "adapters" / "registry.py"

TEXT_SUFFIXES = {
    ".py", ".yaml", ".yml", ".ts", ".tsx", ".js", ".jsx", ".md", ".json",
    ".txt", ".ps1", ".bat", ".sh", ".conf", ".ini", ".html", ".css", ".toml",
}

# 命中即视为"记录性引用"，--expect-zero 不计入失败
ALLOWED_LAYER_PREFIXES = (
    "docs/",
    # 会话笔记，不是交付物
    ".workbuddy/",
    # 退役登记表必须逐个点名旧 ID，否则反向断言无从写起
    "tests/test_model_retirement_registry.py",
    # 同一理由：折叠行为与"旧 ID 不在任何注册表"的断言必须写出旧 ID 本身
    "backend/tests/test_audiobook_tts_model_ids.py",
    "backend/tests/test_audiobook_tts_provider_payloads.py",
    # 前端同源守卫同样要靠"点名旧 ID 的反向断言"锁住页面不自持档位表
    "frontend/src/components/home/__tests__/assetStudioVisionModelSource.test.ts",
    # 本脚本 docstring 用旧 ID 举例说明词边界检索的必要性
    "scripts/audit_model_references.py",
    # 一次性 ID 改写工具同样必须逐个点名旧 ID，它是改写口径的事实源
    "scripts/rewrite_legacy_model_ids.py",
    # 带日期的实验记录：模型名是取证事实的一部分，改写等于篡改实验数据
    "backend/app/services/ai_trace_competition.py",
    "backend/app/services/prompt_evolution/meta_optimizer.py",
    ".agent/optimization-guide-ai-trace-multimodel.md",
    # 付费探针的原始台账（manifest/评分/听评表），同样是取证事实不可改写
    "backend/data/tts_debug/",
    # 供应商价格调研的当日快照：内容是从旧 models.yaml / .env.example 原样粘贴的取证材料，
    # 改写等于篡改当时的报价证据，因此整份按记录放行
    "调研API价格_2026-10-11_18-49.md",
    # 自动合成的仓库知识页，描述的是历史模型名，不驱动任何运行逻辑
    ".qoder/repowiki/",
)

# 无法归入下列层的文件统一记为该层名
ROOT_LAYER = "(根文件)"

ENV_LAYER = "env"

# env 文件不会被 git 清单收录（.env 在 .gitignore 中），必须显式点名后按需存在判定
ENV_FILE_RELPATHS = (
    ".env",
    ".env.example",
    "backend/.env",
    "backend/.env.example",
    "frontend/.env",
    "frontend/.env.example",
)
ENV_ASSIGN_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
ENV_MODEL_KEY_RE = re.compile(r"MODEL", re.IGNORECASE)
ENV_SECRET_KEY_RE = re.compile(
    r"KEY|SECRET|TOKEN|PASSWORD|PASSWD|SALT|CREDENTIAL|PRIVATE|ACCESS",
    re.IGNORECASE,
)
ENV_WIRE_NAME_MARKER = "上游线名"

REGISTER_DECORATOR_RE = re.compile(
    r"""@(?:register_model|register_llm_model)\(\s*["']([^"']+)["']"""
)
CLASS_DEF_RE = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
REGISTRY_MODULE_RE = re.compile(r'"(adapters\.[A-Za-z0-9_.]+)"')


def _layer_of(rel_path: str) -> str:
    if rel_path in ENV_FILE_RELPATHS:
        return ENV_LAYER
    parts = rel_path.split("/")
    if len(parts) == 1:
        return ROOT_LAYER
    return parts[0]


def _git_ls_files(*extra_flags: str) -> str:
    """取 git 清单，且保证中文/非 ASCII 路径可用。

    git 默认 core.quotepath=true，会把非 ASCII 路径转义成 `\350\220\275` 形式；Windows 下
    `text=True` 又按本地 GBK 解码，两个后果叠加：中文命名的文件（架构知识库、带日期的
    调研记录）确实出现在清单里，却因拼不出真实路径而被 _read 静默当成"无内容"跳过，
    门禁对这些文件永远绿灯。因此显式关闭转义，并按 UTF-8 解码原始字节。
    """
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", *extra_flags],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def tracked_text_files() -> List[str]:
    """确定扫描范围：受版本管理的文本文件 + 未跟踪但未被忽略的文本文件。

    只扫 git 索引会漏掉大量新增测试（本仓库 tests/ 下过半迁移回归测试尚未 add），
    而"删干净了没有"必须覆盖工作区实际内容，故补上 --others --exclude-standard，
    并显式并入存在的 env 文件。
    """
    try:
        tracked = _git_ls_files()
        untracked = _git_ls_files("--others", "--exclude-standard")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"无法取得 git 文件清单，请在仓库根目录运行：{exc}") from exc

    files = []
    seen = set()
    for line in (tracked + untracked).splitlines():
        rel = line.strip().strip('"')
        if not rel or rel in seen:
            continue
        suffix = Path(rel).suffix.lower()
        if suffix in TEXT_SUFFIXES or rel.endswith(".env.example"):
            seen.add(rel)
            files.append(rel)

    # .env 系列被 gitignore，上面的清单拿不到；不补进来环境变量就是门禁盲区
    for rel in env_files_present():
        if rel not in seen:
            seen.add(rel)
            files.append(rel)
    return files


def _read(rel_path: str) -> Optional[str]:
    try:
        return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def boundary_pattern(model_id: str) -> re.Pattern:
    """词边界：前后都不能紧邻标识符字符，避免把长 ID 的前缀误判成命中。"""
    return re.compile(
        r"(?<![A-Za-z0-9._/-])" + re.escape(model_id) + r"(?![A-Za-z0-9._-])"
    )


def env_files_present() -> List[str]:
    return [rel for rel in ENV_FILE_RELPATHS if (PROJECT_ROOT / rel).is_file()]


def env_safe_line(line: str) -> Optional[str]:
    """把一行 env 赋值还原成只含键与模型取值的安全文本；不需要或不合规时返回 None。

    这里刻意不返回整行原文：同一行的注释与相邻行都可能是真实密钥，命中报告一旦带上
    原文就等于把密钥写进终端、日志与 CI 产物。
    """
    match = ENV_ASSIGN_RE.match(line.strip())
    if not match:
        return None
    key, raw_value = match.group(1), match.group(2)
    if ENV_SECRET_KEY_RE.search(key) or not ENV_MODEL_KEY_RE.search(key):
        return None
    head, *rest = re.split(r"\s+#", raw_value, maxsplit=1)
    value = head.strip().strip('"').strip("'")
    if not value or value.startswith(("$", "%")) or value.isdigit():
        return None
    # 同行注释里只有"上游线名"这四个字会被带进报告，注释原文一律不复制
    marker = f"  # {ENV_WIRE_NAME_MARKER}" if rest and ENV_WIRE_NAME_MARKER in rest[0] else ""
    return f"{key}={value}{marker}"[:160]


def env_assignment_lines(rel_path: str) -> List[Tuple[int, str]]:
    text = _read(rel_path)
    if not text:
        return []
    out: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        safe = env_safe_line(line)
        if safe:
            out.append((lineno, safe))
    return out


def scan_references(
    model_ids: Sequence[str], files: Iterable[str]
) -> Dict[str, List[Tuple[str, int, str]]]:
    """返回 {model_id: [(相对路径, 行号, 行内容), ...]}。"""
    patterns = {mid: boundary_pattern(mid) for mid in model_ids}
    hits: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)

    env_paths = set(ENV_FILE_RELPATHS)
    for rel in files:
        if rel in env_paths:
            lines = env_assignment_lines(rel)
        else:
            text = _read(rel)
            lines = (
                [(lineno, line.strip()[:160]) for lineno, line in enumerate(text.splitlines(), start=1)]
                if text
                else []
            )
        for lineno, line in lines:
            for mid, pattern in patterns.items():
                if pattern.search(line):
                    hits[mid].append((rel, lineno, line))
    return hits


def deprecated_entries() -> List[Dict[str, str]]:
    """盘点两份 YAML 的 deprecated 条目；替代目标以 MODEL_ALIASES 为权威来源。"""
    aliases: Dict[str, str] = {}
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from core.model_resolution import MODEL_ALIASES

        aliases = {k.lower(): v for k, v in MODEL_ALIASES.items()}
    except Exception:
        aliases = {}

    entries: List[Dict[str, str]] = []
    for path, chain in ((MEDIA_CONFIG_PATH, "media"), (LLM_CONFIG_PATH, "llm")):
        if not path.exists():
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models = payload.get("models") or payload.get("llm_models") or []
        for model in models:
            if not isinstance(model, dict):
                continue
            if model.get("status") != "deprecated":
                continue
            model_id = str(model.get("id"))
            entries.append(
                {
                    "id": model_id,
                    "chain": chain,
                    "name": str(model.get("name") or ""),
                    "replacement": str(model.get("replacement") or aliases.get(model_id.lower(), "")),
                    "deprecated_since": str(model.get("deprecated_since") or ""),
                    "file": f"config/{path.name}",
                }
            )
    return entries


def retired_ledger_ids() -> List[str]:
    """从退役登记表取"必须彻底消失的旧 ID"。

    本项目采用"退役即物理删除"，两份 YAML 常态下没有 `status: deprecated` 条目，
    所以 `--all-deprecated` 在退役完成后会列出 0 条。旧 ID 的唯一权威清单是
    `tests/test_model_retirement_registry.py` 里的三张字典（该文件同时被
    ALLOWED_LAYER_PREFIXES 白名单豁免，因为它必须逐个点名旧 ID 才能写反向断言）。
    """
    path = PROJECT_ROOT / "tests" / "test_model_retirement_registry.py"
    if not path.exists():
        raise SystemExit(f"退役登记表不存在：{path}")
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_model_retirement_ledger", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:  # pytest 缺失或登记表语法错误都应给出明确提示
        raise SystemExit(f"无法加载退役登记表 {path}：{exc}") from exc

    ids: List[str] = []
    for name in (
        "RETIRED_MEDIA_MODELS",
        "RETIRED_LLM_MODELS",
        "RENAMED_LLM_MODELS",
        # 有声书 ASR/TTS 这类只有 HTTP 契约、不进注册中心的链路，同样必须进门禁视野
        "RETIRED_AUDIOBOOK_ASR_MODELS",
    ):
        ids.extend(str(mid) for mid in getattr(module, name, {}))
    ids.extend(getattr(module, "LEGACY_ALIAS_KEYS", set()))
    return sorted(set(ids))


def check_registry_imports() -> List[str]:
    """自动导入清单里的模块必须真实存在，否则适配器静默不注册。"""
    problems: List[str] = []
    if not REGISTRY_PATH.exists():
        return ["adapters/registry.py 不存在"]
    text = REGISTRY_PATH.read_text(encoding="utf-8", errors="ignore")
    for module_name in REGISTRY_MODULE_RE.findall(text):
        rel = module_name.replace(".", "/") + ".py"
        pkg_init = module_name.replace(".", "/") + "/__init__.py"
        if not (PROJECT_ROOT / rel).exists() and not (PROJECT_ROOT / pkg_init).exists():
            problems.append(f"{module_name} -> 缺失 {rel}")
    return problems


def check_registration_uniqueness(files: Iterable[str]) -> Tuple[List[str], List[str]]:
    """同一 ID 多注册点、跨文件同名适配器类。"""
    id_owners: Dict[str, List[str]] = defaultdict(list)
    class_owners: Dict[str, List[str]] = defaultdict(list)

    for rel in files:
        if not rel.endswith(".py"):
            continue
        if not (rel.startswith("adapters/") or rel.startswith("core/")):
            continue
        text = _read(rel)
        if not text:
            continue
        for model_id in REGISTER_DECORATOR_RE.findall(text):
            id_owners[model_id].append(rel)
        for class_name in CLASS_DEF_RE.findall(text):
            if class_name.endswith("Adapter"):
                class_owners[class_name].append(rel)

    dup_ids = [
        f"{mid}: 被 {len(paths)} 处注册 -> {', '.join(sorted(set(paths)))}"
        for mid, paths in sorted(id_owners.items())
        if len(set(paths)) > 1
    ]
    dup_classes = [
        f"{name}: 同名类出现在 {', '.join(sorted(set(paths)))}"
        for name, paths in sorted(class_owners.items())
        if len(set(paths)) > 1
    ]
    return dup_ids, dup_classes


def summarize(hits: Sequence[Tuple[str, int, str]]) -> Counter:
    counter: Counter = Counter()
    for rel, _lineno, _text in hits:
        counter[_layer_of(rel)] += 1
    return counter


# 退役后的旧字符串可能以三种身份继续合法存在，必须与"仍当作内部模型 ID 使用"区分开，
# 否则 --expect-zero 会被合法命中淹没，判据失去意义：
#
# 1) 上游真名（wire name）：内部 ID 已改成中性名，发给供应商的真名由
#    default_params.request_model 钉死；档案文案与示例代码里的 model="真名"、
#    "模型名为 X" 都是同一个事实。ID 后紧跟 "[" 的写法（如 glm-5.2[1m]）只可能是
#    上游变体名——本项目内部 ID 从不含方括号后缀。
# 2) 引擎标识符：DreamWeaver 的视频引擎档位（wan2.7-i2v / wan2.7-t2v）与已退役的
#    万相模型 ID 同名，但它是本项目的路由/计费键，不进注册中心、也不发给上游。
#    改名会牵动计费记录与配置快照，因此在此显式豁免该上下文，而不是放宽整个文件。
#
# 命中行内若不含下列上下文，仍按"待改残留"处理。
WIRE_NAME_CONTEXT_RE = re.compile(
    r"""request_model                       # 钉死上游真名的字段（含断言 default_params["request_model"]）
    | \bmodel\b\s*=\s*['"]                  # 示例代码里的 model="真名"
    | \[\s*['"]model['"]\s*\]               # 断言实际发出的 OpenAI 兼容 model 字段
    | 模型名[为：:]?\s                      # 档案文案：明确声明这是上游名
    | 上游线名                               # 文档约定用语
    """,
    re.VERBOSE,
)

ENGINE_IDENTIFIER_CONTEXT_RE = re.compile(
    r"""DREAMWEAVER                         # 常量名与环境变量名
    | ['"]engine['"]                        # "engine": 与 ["engine"]
    | \bengine\b\s*[:=]
    """,
    re.VERBOSE,
)


def _is_wire_variant(line_text: str, model_id: str) -> bool:
    """ID 后紧跟方括号后缀（glm-5.2[1m]）即上游变体名写法，本项目内部 ID 从不带此后缀。"""
    return bool(model_id) and f"{model_id}[" in line_text


def _is_allowed_hit(rel_path: str, line_text: str, model_id: str) -> bool:
    if rel_path.startswith(ALLOWED_LAYER_PREFIXES):
        return True
    if _is_wire_variant(line_text, model_id):
        return True
    return bool(WIRE_NAME_CONTEXT_RE.search(line_text) or ENGINE_IDENTIFIER_CONTEXT_RE.search(line_text))


def must_fix_count(model_id: str, hits: Sequence[Tuple[str, int, str]]) -> int:
    return sum(1 for rel, _lineno, text in hits if not _is_allowed_hit(rel, text, model_id))


def print_report(
    requested: Sequence[str],
    hits: Dict[str, List[Tuple[str, int, str]]],
    structural: Dict[str, object],
    max_lines: int,
) -> int:
    total_must_fix = 0
    for mid in requested:
        entries = hits.get(mid, [])
        layers = summarize(entries)
        need_fix = must_fix_count(mid, entries)
        total_must_fix += need_fix
        print(f"\n### {mid}: 命中 {len(entries)} 处 / 待处理 {need_fix} 处")
        if layers:
            print("    分层: " + ", ".join(f"{k} {v}" for k, v in layers.most_common()))
        for rel, lineno, text in entries[:max_lines]:
            flag = "记录" if _is_allowed_hit(rel, text, mid) else "待改"
            print(f"    [{flag}] {rel}:{lineno}  {text}")
        if len(entries) > max_lines:
            print(f"    ... 其余 {len(entries) - max_lines} 处省略（--json 可取全量）")

    print("\n=== 结构体检 ===")
    for key in ("registry_imports", "duplicate_ids", "duplicate_classes"):
        items = structural.get(key) or []
        label = {
            "registry_imports": "自动导入清单缺失模块",
            "duplicate_ids": "同 ID 多注册点",
            "duplicate_classes": "跨文件同名适配器类（提示，不计入门禁）",
        }[key]
        if not items:
            print(f"  {label}: 无")
        else:
            print(f"  {label}: {len(items)} 项")
            for item in items:
                print(f"    - {item}")

    deprecated = structural.get("deprecated") or []
    print(f"\n=== 已弃用条目: {len(deprecated)} 条 ===")
    for item in deprecated:
        since = item["deprecated_since"] or "未记录"
        repl = item["replacement"] or "未声明替代"
        print(f"  {item['id']:<26} {item['chain']:<5} 替代={repl:<24} since={since}")

    print(f"\n合计待处理引用: {total_must_fix} 处")
    return total_must_fix


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Windows 控制台默认 GBK，中文报告会乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="模型 ID 引用审计（只读）")
    parser.add_argument("--model-id", action="append", default=[], help="要审计的模型 ID，可重复")
    parser.add_argument("--all-deprecated", action="store_true", help="审计两份 YAML 中全部 deprecated 条目")
    parser.add_argument("--all-retired", action="store_true", help="审计退役登记表列出的全部旧 ID（物理退役后的主力判据）")
    parser.add_argument("--expect-zero", action="store_true", help="存在待处理引用或结构问题时返回非零退出码")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--max-lines", type=int, default=12, help="每个 ID 最多展示多少条命中")
    args = parser.parse_args(argv)

    deprecated = deprecated_entries()
    requested: List[str] = list(args.model_id)
    if args.all_deprecated:
        requested.extend(item["id"] for item in deprecated)
    if args.all_retired:
        requested.extend(retired_ledger_ids())

    unique: List[str] = []
    for mid in requested:
        if mid and mid not in unique:
            unique.append(mid)
    requested = unique

    if not requested:
        # 不带 ID 时只跑结构体检与 deprecated 盘点：清单里列出的模块是否真实存在、
        # 同 ID 是否被多处注册，这两项与具体模型无关，值得单独作为一条常设检查
        print("未指定模型 ID：仅执行结构体检与 deprecated 盘点（引用扫描请用 --model-id / --all-retired）")

    files = tracked_text_files()
    hits = scan_references(requested, files)

    dup_ids, dup_classes = check_registration_uniqueness(files)
    structural = {
        "registry_imports": check_registry_imports(),
        "duplicate_ids": dup_ids,
        "duplicate_classes": dup_classes,
        "deprecated": deprecated,
    }

    if args.json:
        payload = {
            "scanned_files": len(files),
            "hits": {mid: [{"file": f, "line": n, "text": t} for f, n, t in hits.get(mid, [])] for mid in requested},
            "structural": structural,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        must_fix = sum(must_fix_count(mid, hits.get(mid, [])) for mid in requested)
    else:
        must_fix = print_report(requested, hits, structural, args.max_lines)

    if args.expect_zero:
        # duplicate_classes 只作提示：adapters/model_adapters.py 是保留下来的旧式门面，
        # 其中重名类不带 @register_model，不参与注册中心，不构成"哪个实现在跑"的歧义
        gate_keys = ("registry_imports", "duplicate_ids")
        blockers = must_fix + sum(
            len(structural[key] or []) for key in gate_keys
        )
        if blockers:
            print(f"\n审计未通过: {blockers} 项待处理", file=sys.stderr)
            return 1
        print("\n审计通过: 无待处理引用，无结构问题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
