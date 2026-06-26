"""
标记模型中心卡片为已验证

将指定模型的校验状态更新为 verified。由于全量联网校验功能已移除，
对于已通过官方文档人工核对过的接入模型，使用本脚本手动标记为已验证。

用法:
    # 预览（默认标记本批次新接入的4个模型）
    python -m backend.app.scripts.mark_catalog_cards_verified

    # 实际执行
    python -m backend.app.scripts.mark_catalog_cards_verified --execute

    # 指定其他模型
    python -m backend.app.scripts.mark_catalog_cards_verified --models "model-a" "model-b" --execute

警告: 此操作会永久修改数据库，请谨慎执行。
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.model_catalog import ModelCatalogEntry

# 本批次新接入并已通过官方文档人工校验的模型
DEFAULT_TARGET_MODELS: tuple[str, ...] = (
    "qwen3.7-plus",
    "kimi/kimi-k2.6",
    "glm-5.2",
    "MiniMax/MiniMax-M3",
    "step-3.7-flash",
    "mimo-v2.5-pro",
    "mimo-v2.5",
)

VERIFICATION_SCOPE = "manual_verified"
VERIFICATION_SCORE = 1.0
VERIFICATION_NOTES = (
    "已通过官方文档人工校验：能力描述、价格信息、约束限制、来源链接均已核对，"
    "配置与官方文档一致，适配器已注册并可正常加载。"
)


def mark_entries_verified(
    db: Session,
    model_keys: list[str],
    *,
    dry_run: bool = True,
) -> dict:
    """将指定模型卡片的校验状态更新为 verified。"""

    now = datetime.now(timezone.utc)
    entries = (
        db.query(ModelCatalogEntry)
        .filter(ModelCatalogEntry.model_key.in_(model_keys))
        .all()
    )

    found_keys = {entry.model_key for entry in entries}
    missing_keys = sorted(set(model_keys) - found_keys)

    updated_entries: list[str] = []
    skipped_entries: list[tuple[str, str]] = []

    for entry in entries:
        if entry.verification_status == "verified" and entry.verification_scope == VERIFICATION_SCOPE:
            skipped_entries.append((entry.model_key, "已是已验证状态"))
            continue

        if not dry_run:
            entry.verification_status = "verified"
            entry.verification_scope = VERIFICATION_SCOPE
            entry.verification_score = VERIFICATION_SCORE
            entry.reachable_source_count = entry.total_source_count
            entry.verified_source_count = entry.total_source_count
            entry.verification_notes = VERIFICATION_NOTES
            entry.last_verified_at = now

        updated_entries.append(entry.model_key)

    return {
        "requested_count": len(model_keys),
        "found_count": len(entries),
        "updated_count": len(updated_entries),
        "updated_keys": updated_entries,
        "skipped_count": len(skipped_entries),
        "skipped": skipped_entries,
        "missing_keys": missing_keys,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="标记模型中心卡片为已验证")
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_TARGET_MODELS),
        help="要标记为已验证的模型 key 列表（默认为本批次新接入的4个模型）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="执行实际标记（默认仅预览）",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()

    try:
        print("=" * 60)
        print("模型中心卡片验证状态标记工具")
        print("=" * 60)

        if args.execute:
            print("⚠️  警告: 即将执行数据库修改！")
        else:
            print("🔍 预览模式（添加 --execute 参数实际执行）")

        result = mark_entries_verified(db, args.models, dry_run=not args.execute)

        print(f"\n📊 标记结果:")
        print(f"   请求数: {result['requested_count']}")
        print(f"   找到数: {result['found_count']}")
        print(f"   将更新数: {result['updated_count']}")
        print(f"   已跳过数: {result['skipped_count']}")

        if result["updated_keys"]:
            print(f"\n   将标记为已验证的模型:")
            for key in result["updated_keys"]:
                print(f"     - {key}")

        if result["skipped"]:
            print(f"\n   已跳过的模型（已是已验证状态）:")
            for key, reason in result["skipped"]:
                print(f"     - {key}: {reason}")

        if result["missing_keys"]:
            print(f"\n   ⚠️ 未在数据库中找到的模型:")
            for key in result["missing_keys"]:
                print(f"     - {key}")

        if not args.execute:
            print(f"\n⏸️  未执行任何修改。请添加 --execute 参数实际运行。")
        else:
            db.commit()
            print(f"\n✅ 标记完成！{result['updated_count']} 个模型已更新为 verified 状态。")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
