"""
DreamWeaver 语义索引（SQLite）维护脚本：默认只读预览，需 `--apply` 才会写入/删除。

用法：
  - 查看统计（默认）：python "scripts/semantic_index_admin.py"
  - 预览清理缺失文件记录：python "scripts/semantic_index_admin.py" --prune-missing
  - 实际清理缺失文件记录：python "scripts/semantic_index_admin.py" --prune-missing --apply
  - 预览/执行 VACUUM：python "scripts/semantic_index_admin.py" --vacuum [--apply]
  - 指定 DB：python "scripts/semantic_index_admin.py" --db-path "runs/_semantic_cache/semantic_assets.sqlite3"
  - 仅处理某项目：python "scripts/semantic_index_admin.py" --project-id 123 --prune-missing [--apply]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def _default_db_path() -> Path:
    raw = str(os.getenv("DREAMWEAVER_SEMANTIC_INDEX_DB") or "runs/_semantic_cache/semantic_assets.sqlite3").strip()
    return Path(raw)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (name,),
    ).fetchone()
    return bool(row)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_asset_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return _repo_root() / p


def _print_stats(conn: sqlite3.Connection, *, project_id: int | None) -> None:
    where = ""
    params: tuple[object, ...] = ()
    if project_id is not None:
        where = "WHERE project_id = ?"
        params = (int(project_id),)

    total_row = conn.execute(f"SELECT COUNT(1) AS n FROM semantic_assets {where};", params).fetchone()
    total = int(total_row["n"]) if total_row else 0

    time_row = conn.execute(
        f"SELECT MIN(created_at) AS min_ts, MAX(created_at) AS max_ts FROM semantic_assets {where};",
        params,
    ).fetchone()

    print(f"rows: {total}")
    if time_row and time_row["min_ts"] is not None and time_row["max_ts"] is not None:
        print(f"created_at: {float(time_row['min_ts']):.0f} .. {float(time_row['max_ts']):.0f}")

    rows = conn.execute(
        f"""
        SELECT project_id, kind, COUNT(1) AS n
        FROM semantic_assets
        {where}
        GROUP BY project_id, kind
        ORDER BY project_id ASC, kind ASC;
        """,
        params,
    ).fetchall()
    if not rows:
        return

    print("by project/kind:")
    for r in rows:
        print(f"  - project_id={int(r['project_id'])} kind={str(r['kind'])}: {int(r['n'])}")


def _prune_missing(
    conn: sqlite3.Connection,
    *,
    project_id: int | None,
    apply: bool,
    sample_limit: int,
) -> int:
    where = ""
    params: list[object] = []
    if project_id is not None:
        where = "WHERE project_id = ?"
        params.append(int(project_id))

    rows = conn.execute(f"SELECT id, path FROM semantic_assets {where};", tuple(params)).fetchall()
    missing_ids: list[str] = []
    sample: list[str] = []
    for r in rows:
        pid = str(r["id"] or "")
        path_str = str(r["path"] or "")
        if not pid or not path_str:
            continue
        if _resolve_asset_path(path_str).exists():
            continue
        missing_ids.append(pid)
        if len(sample) < max(0, int(sample_limit)):
            sample.append(path_str)

    if not missing_ids:
        print("prune-missing: 0")
        return 0

    print(f"prune-missing: {len(missing_ids)}")
    if sample:
        print("sample:")
        for s in sample:
            print(f"  - {s}")

    if not apply:
        print("未执行删除：使用 --apply 以实际写入")
        return 0

    chunk = 500
    for i in range(0, len(missing_ids), chunk):
        batch = missing_ids[i : i + chunk]
        conn.executemany("DELETE FROM semantic_assets WHERE id = ?;", [(x,) for x in batch])
    conn.commit()
    print("已删除缺失文件记录")
    return 0


def _vacuum(conn: sqlite3.Connection, *, apply: bool) -> int:
    if not apply:
        print("vacuum: 预览（未执行），使用 --apply 以实际写入")
        return 0
    conn.execute("VACUUM;")
    print("vacuum: done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DreamWeaver semantic_assets.sqlite3 管理工具（默认只读预览）")
    parser.add_argument("--db-path", default=None, help="SQLite 路径（默认读取 DREAMWEAVER_SEMANTIC_INDEX_DB）")
    parser.add_argument("--project-id", type=int, default=None, help="仅处理某 project_id")
    parser.add_argument("--prune-missing", action="store_true", help="清理 path 不存在的记录（需 --apply 才会写入）")
    parser.add_argument("--vacuum", action="store_true", help="执行 VACUUM 压缩 DB（需 --apply 才会写入）")
    parser.add_argument("--apply", action="store_true", help="实际写入/删除（默认仅预览）")
    parser.add_argument("--sample-limit", type=int, default=10, help="预览时输出缺失样本数量")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    if not db_path.is_absolute():
        db_path = _repo_root() / db_path

    print(f"db: {db_path}")
    if not db_path.exists():
        print("db 不存在（无可操作内容）")
        return 0

    conn = _connect(db_path)
    try:
        if not _table_exists(conn, "semantic_assets"):
            print("表 semantic_assets 不存在（无可操作内容）")
            return 0

        _print_stats(conn, project_id=args.project_id)

        if args.prune_missing:
            _prune_missing(conn, project_id=args.project_id, apply=bool(args.apply), sample_limit=int(args.sample_limit))
        if args.vacuum:
            _vacuum(conn, apply=bool(args.apply))
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

