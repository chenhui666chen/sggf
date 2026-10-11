"""
把数据库历史数据里的旧模型 ID 改写成现行 ID（不保留 original_model_id 副本）。

内部 ID 已改成不含版本号的中性名，旧模型也已物理退役，因此库里残留的旧 ID 属于
待清理数据而非需要保真的取证字段——按项目决定一律改写，改完就像当初接入的就是新 ID。

默认只扫描并预览，不写库；需要显式加 `--apply` 才会更新。

用法：
  - 预览：python "scripts/rewrite_legacy_model_ids.py"
  - 写入：python "scripts/rewrite_legacy_model_ids.py" --apply
  - 不生成回滚备份：python "scripts/rewrite_legacy_model_ids.py" --apply --no-backup

不改写的旧 ID（有意排除）：
  - `cosyvoice-v3-plus` / `cosyvoice_v3_plus`：音色资产数据保持原样，归一别名长期保留。
  - `wan2.6-t2v-fast`：悬空别名，归一目标 `wan2.6-t2v` 任何注册中心都不存在，
    改写只会把一个不存在的 ID 换成另一个不存在的 ID。
  - 拼写变体别名（`qwen3_vl_plus`、`qwen3_tts`、`qwen_image_edit_*` 等）：属媒体线格式归一，
    库中无命中，且改写无收益。
  - `wan2.7-i2v` / `wan2.7-t2v` / `wan_auto`：DreamWeaver 引擎标识符，不是模型 ID，
    其迁移由 wan2.7→wan3.0 媒体线单独负责。

匹配一律带词边界，故 `mimo-v2.5-tts`、`glm-5.2[1m]` 这类更长的名字不会被前缀误伤。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402


# 长名在前：同一族的短名不会先吃掉长名的匹配位置
ID_REWRITES: Tuple[Tuple[str, str], ...] = (
    # 中性化改名（内部 ID 去版本号，上游线名由 default_params.request_model 钉死）
    ("MiniMax/MiniMax-M3", "minimax-m"),
    ("kimi/kimi-k2.8-preview", "kimi-preview"),
    ("mimo-v2.6-pro", "mimo-pro"),
    ("mimo-v2.6-flash", "mimo-flash"),
    ("deepseek-v4-pro", "deepseek-pro"),
    ("qwen3.7-plus", "qwen-plus"),
    ("qwen3.7-flash", "qwen-flash"),
    ("step-5-preview", "step-preview"),
    ("minimax-m3", "minimax-m"),
    ("glm-5.3", "glm"),
    # 物理退役（上游已下线或本项目主动升级）
    ("glm-5.2", "glm"),
    ("kimi/kimi-k2.6", "kimi-preview"),
    ("deepseek-v4-flash", "deepseek-flash"),
    ("doubao-seedream-4-5", "doubao-seedream-5-0-pro"),
    ("doubao-seed-2-0-pro", "doubao-seed-2-1-pro"),
    ("doubao-seed-2-0-lite", "doubao-seed-2-1-lite"),
    ("step-3.7-flash", "step-preview"),
    ("mimo-v2.5-pro", "mimo-pro"),
    ("kimi-k2.6", "kimi-preview"),
    ("mimo-v2.5", "mimo-flash"),
    ("stepaudio-2.5-tts", "stepaudio-3-tts"),
)

# `[` 计入右边界，`glm-5.2[1m]` 是上游 1M 上下文线名，改写成 `glm[1m]` 没有意义
_BOUNDARY_LEFT = r"(?<![A-Za-z0-9._/-])"
_BOUNDARY_RIGHT = r"(?![A-Za-z0-9._\[-])"

_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = tuple(
    (new, re.compile(_BOUNDARY_LEFT + re.escape(old) + _BOUNDARY_RIGHT, re.IGNORECASE))
    for old, new in ID_REWRITES
)

# 命中的旧 ID 计数，供预览报告与退出码使用
_HIT_IDS = {old for old, _ in ID_REWRITES}


def rewrite_text(value: str) -> str:
    """按 ID_REWRITES 逐条替换；顺序即优先级，长名先替换避免短名抢位。"""
    result = value
    for new, pattern in _PATTERNS:
        result = pattern.sub(new, result)
    return result


def scan_columns(db) -> List[Tuple[str, str]]:
    """找出所有可能装文本的列，逐列探测是否含旧 ID，返回 (表, 列) 列表。"""
    rows = db.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type ~ 'character|text|json'
            ORDER BY table_name, ordinal_position
            """
        )
    ).fetchall()

    hits: List[Tuple[str, str]] = []
    for table, column in rows:
        # 用 ILIKE 逐 ID 探测：改写正则不分大小写，扫描口径必须一致
        conditions = " OR ".join([f'"{column}"::text ILIKE :p{i}' for i in range(len(_HIT_IDS))])
        params = {f"p{i}": f"%{mid}%" for i, mid in enumerate(sorted(_HIT_IDS))}
        count = db.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE {conditions}'), params
        ).scalar()
        if count:
            hits.append((table, column))
    return hits


def primary_key_of(db, table: str) -> str:
    row = db.execute(
        text(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = :t
            LIMIT 1
            """
        ),
        {"t": table},
    ).scalar()
    if not row:
        raise SystemExit(f"表 {table} 没有单列主键，无法安全定位行，请人工处理")
    return str(row)


def collect_changes(db, targets: Sequence[Tuple[str, str]]) -> List[Dict[str, object]]:
    """返回每条待改写记录：表、列、主键、原值、新值、命中的旧 ID。"""
    changes: List[Dict[str, object]] = []
    for table, column in targets:
        pk = primary_key_of(db, table)
        conditions = " OR ".join([f'"{column}"::text ILIKE :p{i}' for i in range(len(_HIT_IDS))])
        params = {f"p{i}": f"%{mid}%" for i, mid in enumerate(sorted(_HIT_IDS))}
        rows = db.execute(
            text(f'SELECT "{pk}", "{column}" FROM "{table}" WHERE {conditions}'), params
        ).fetchall()
        for pk_value, original in rows:
            if not original:
                continue
            updated = rewrite_text(original)
            if updated == original:
                # ILIKE 是子串匹配，词边界过滤后可能并无实际可改写内容
                continue
            matched = sorted(
                {
                    old
                    for old, _ in ID_REWRITES
                    if re.search(
                        _BOUNDARY_LEFT + re.escape(old) + _BOUNDARY_RIGHT, original, re.IGNORECASE
                    )
                }
            )
            changes.append(
                {
                    "table": table,
                    "column": column,
                    "pk": pk,
                    "pk_value": pk_value,
                    "matched_ids": matched,
                    "original": original,
                    "updated": updated,
                }
            )
    return changes


def write_backup(changes: Sequence[Dict[str, object]]) -> Path:
    backup_dir = ROOT_DIR / "database_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"model_id_rewrite_{stamp}.json"
    payload = [
        {
            "table": c["table"],
            "column": c["column"],
            "pk": c["pk"],
            "pk_value": c["pk_value"],
            "original": c["original"],
        }
        for c in changes
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def apply_changes(db, changes: Sequence[Dict[str, object]]) -> int:
    for change in changes:
        db.execute(
            text(
                f'UPDATE "{change["table"]}" SET "{change["column"]}" = :value '
                f'WHERE "{change["pk"]}" = :pk_value'
            ),
            {"value": change["updated"], "pk_value": change["pk_value"]},
        )
    db.commit()
    return len(changes)


def main() -> int:
    parser = argparse.ArgumentParser(description="改写数据库历史数据里的旧模型 ID")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    parser.add_argument("--no-backup", action="store_true", help="跳过回滚备份（不建议）")
    parser.add_argument("--max-samples", type=int, default=6, help="每个列最多展示几处替换样例")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        targets = scan_columns(db)
        if not targets:
            print("扫描完成：数据库中没有旧模型 ID 引用，无需改写")
            return 0

        print("命中列：")
        for table, column in targets:
            print(f"  {table}.{column}")

        changes = collect_changes(db, targets)
        if not changes:
            print("\n命中均为子串误报（词边界过滤后无可改写内容），无需改写")
            return 0

        print(f"\n待改写 {len(changes)} 行：")
        shown: Dict[str, int] = {}
        for change in changes:
            key = f'{change["table"]}.{change["column"]}'
            shown[key] = shown.get(key, 0) + 1
            if shown[key] > args.max_samples:
                continue
            original = str(change["original"])
            updated = str(change["updated"])
            # 只展示第一处差异的上下文，避免整段 JSON 刷屏
            idx = next(
                (i for i in range(min(len(original), len(updated))) if original[i] != updated[i]),
                0,
            )
            start, end = max(0, idx - 60), idx + 80
            print(
                f'  {key} {change["pk"]}={change["pk_value"]} '
                f'旧 ID: {", ".join(change["matched_ids"])}'
            )
            print(f"    - ...{original[start:end]}...")
            print(f"    + ...{updated[start:end]}...")

        if not args.apply:
            print("\n预览结束，未写库。使用 --apply 执行改写")
            return 0

        if not args.no_backup:
            backup_path = write_backup(changes)
            print(f"\n已写入回滚备份：{backup_path}")

        written = apply_changes(db, changes)
        print(f"完成：已改写 {written} 行")

        remaining = scan_columns(db)
        if remaining:
            print(f"警告：改写后仍有命中列 {remaining}，请人工复核")
            return 1
        print("复核通过：数据库中已无旧模型 ID 引用")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
