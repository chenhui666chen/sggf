"""
一次性补全历史经验报告中的 `genre` 字段（默认：通用）。

用法：
  - 预览（不写入）：
      python "scripts/migrate_experience_reports_genre.py"
  - 实际写入：
      python "scripts/migrate_experience_reports_genre.py" --apply
  - 指定默认题材：
      python "scripts/migrate_experience_reports_genre.py" --apply --default-genre "通用"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="补全 experience_reports 中缺失的 genre 字段")
    parser.add_argument("--apply", action="store_true", help="实际写入文件（默认仅预览）")
    parser.add_argument("--default-genre", default="通用", help="缺失 genre 时写入的默认值")
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="经验报告目录（默认：data/prompt_evolution/experience_reports）",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    reports_dir = Path(args.reports_dir) if args.reports_dir else repo_root / "data" / "prompt_evolution" / "experience_reports"

    if not reports_dir.exists():
        raise SystemExit(f"目录不存在: {reports_dir}")

    changed: list[Path] = []
    failed: list[Path] = []

    for path in sorted(reports_dir.glob("*_experience.json")):
        try:
            data = _load_json(path)
        except Exception:
            failed.append(path)
            continue

        if (data.get("genre") or "").strip():
            continue

        data["genre"] = args.default_genre
        changed.append(path)

        if args.apply:
            _dump_json(path, data)

    if failed:
        print(f"警告: 解析失败 {len(failed)} 个文件（未处理）")
        for p in failed[:10]:
            print(f"  - {p}")
        if len(failed) > 10:
            print(f"  ... 以及另外 {len(failed) - 10} 个")

    if args.apply:
        print(f"完成: 已写入 genre {len(changed)} 个文件（默认值：{args.default_genre}）")
    else:
        print(f"预览: 将写入 genre {len(changed)} 个文件（默认值：{args.default_genre}）")
        print("   使用 --apply 执行写入")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
