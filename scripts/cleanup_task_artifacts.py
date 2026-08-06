"""任务完成后的一次性测试产物清理脚本（白名单机制）。

每次修复/修改/增添功能完成并验证通过后执行，清理本次运行产生的、
可安全重新生成的临时产物。默认 dry-run，加 --apply 才真正删除。

清理范围（白名单）：
- pytest 临时目录与缓存：.pytest_cache、.pytest_tmp、.pytest_tmp_*、
  根目录与 backend 下的 .pytest-* 临时运行目录
- Python __pycache__（排除 .venv / node_modules / .git）
- 覆盖率缓存：.coverage、htmlcov
- Vitest/Vite 缓存：frontend/node_modules/.vite、.vitest

绝不清理：
- data/prompt_evolution（提示词进化运行数据）
- backend/data/audio_library、audiobooks 等正式音频产物
- 用户剧本、项目配置、数据库、memory_data、previews、runs
- 任何无明确证据证明由当前任务生成的未跟踪文件
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = "--apply" in sys.argv

# 白名单：相对仓库根的临时目录/文件模式
DIR_PATTERNS = [
    ".pytest_cache",
    ".pytest_tmp",
    ".pytest_tmp_*",
    ".pytest-*",          # .pytest-voice-identity-*、.pytest-candidate-* 等临时运行目录
    "htmlcov",
]
BACKEND_DIR_PATTERNS = [
    ".pytest_cache",
    ".pytest_tmp",
    ".pytest_tmp_*",
    ".pytest_preview_cache_policy*",
    ".pytest-*",
]
FRONTEND_CACHE_DIRS = [
    "node_modules/.vite",
    "node_modules/.vitest",
]
FILE_PATTERNS = [".coverage"]

# 保护清单：任何情况下不得触碰
PROTECTED_PARTS = {
    ".venv", ".git", "node_modules", "data", "audiobooks",
    "memory_data", "previews", "runs", "prompt_evolution",
    "audio_library", "_media_backup_20260806",
}

removed_count = 0
removed_bytes = 0


def _dir_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def remove_path(path: Path, *, allow_node_modules_cache: bool = False) -> None:
    global removed_count, removed_bytes
    if not path.exists():
        return
    # 双重保险：路径任何一段命中保护清单则跳过
    # （node_modules 内的 Vite/Vitest 缓存目录为显式白名单，豁免）
    if not allow_node_modules_cache and any(
        part in PROTECTED_PARTS for part in path.relative_to(ROOT).parts
    ):
        print(f"跳过(受保护): {path.relative_to(ROOT)}")
        return
    size = _dir_size(path) if path.is_dir() else path.stat().st_size
    label = str(path.relative_to(ROOT))
    if APPLY:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        print(f"已删除: {label} ({size / 1048576:.1f} MB)")
    else:
        print(f"将删除: {label} ({size / 1048576:.1f} MB)")
    removed_count += 1
    removed_bytes += size


def scan_patterns(base: Path, patterns: list[str]) -> None:
    if not base.is_dir():
        return
    for pattern in patterns:
        for match in sorted(base.glob(pattern)):
            if match.is_dir() or match.is_file():
                remove_path(match)


def scan_pycache() -> None:
    for dirpath, dirnames, _filenames in os.walk(ROOT):
        # 剪枝：不进入受保护/无关目录
        dirnames[:] = [
            d for d in dirnames
            if d not in {".venv", ".git", "node_modules"} and not d.startswith("_media_backup_")
        ]
        if "__pycache__" in dirnames:
            remove_path(Path(dirpath) / "__pycache__")
            dirnames.remove("__pycache__")


def main() -> int:
    scan_patterns(ROOT, DIR_PATTERNS)
    scan_patterns(ROOT / "backend", BACKEND_DIR_PATTERNS)
    for rel in FRONTEND_CACHE_DIRS:
        remove_path(ROOT / "frontend" / rel, allow_node_modules_cache=True)
    for pattern in FILE_PATTERNS:
        for match in list(ROOT.glob(pattern)) + list((ROOT / "backend").glob(pattern)):
            remove_path(match)
    scan_pycache()

    print(f"\n{'[dry-run] ' if not APPLY else ''}合计: {removed_count} 项, {removed_bytes / 1048576:.1f} MB")
    if not APPLY:
        print("确认无误后加 --apply 执行删除")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

