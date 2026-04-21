"""
清理模型档案校验数据

将所有 model_catalog_entries 表中的校验相关字段重置为待验证状态。
由于全量校验功能已移除，相关字段不再更新，现将其重置为初始状态。

用法:
    python -m backend.app.scripts.cleanup_catalog_verification_data

警告: 此操作会永久修改数据库，请谨慎执行。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource


def cleanup_verification_data(db: Session, dry_run: bool = True) -> dict:
    """清理所有校验相关字段"""
    updated_entries = []
    deleted_sources = 0

    entries = db.query(ModelCatalogEntry).all()
    for entry in entries:
        if (
            entry.verification_status != "pending"
            or entry.verification_score != 0.0
            or entry.verification_scope is not None
            or entry.total_source_count != 0
            or entry.reachable_source_count != 0
            or entry.verified_source_count != 0
            or entry.verification_notes is not None
            or entry.last_synced_at is not None
            or entry.last_verified_at is not None
        ):
            if not dry_run:
                entry.verification_status = "pending"
                entry.verification_score = 0.0
                entry.verification_scope = None
                entry.total_source_count = 0
                entry.reachable_source_count = 0
                entry.verified_source_count = 0
                entry.verification_notes = None
                entry.last_synced_at = None
                entry.last_verified_at = None

            updated_entries.append(entry.model_key)

    sources = db.query(ModelCatalogSource).all()
    deleted_sources = len(sources)
    if not dry_run and deleted_sources > 0:
        for source in sources:
            db.delete(source)

    return {
        "total_entries": len(entries),
        "updated_entries_count": len(updated_entries),
        "updated_entry_keys": updated_entries,
        "deleted_sources_count": deleted_sources,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="清理模型档案校验数据")
    parser.add_argument("--execute", action="store_true", help="执行实际清理（默认仅预览）")
    args = parser.parse_args()

    db: Session = SessionLocal()

    try:
        print("=" * 60)
        print("模型档案校验数据清理工具")
        print("=" * 60)

        if args.execute:
            print("⚠️  警告: 即将执行数据库修改！")
        else:
            print("🔍 预览模式（添加 --execute 参数实际执行）")

        result = cleanup_verification_data(db, dry_run=not args.execute)

        print(f"\n📊 清理结果:")
        print(f"   总模型数: {result['total_entries']}")
        print(f"   需更新条目数: {result['updated_entries_count']}")
        print(f"   将删除来源记录数: {result['deleted_sources_count']}")

        if result["updated_entry_keys"]:
            print(f"\n   将更新的模型:")
            for key in result["updated_entry_keys"]:
                print(f"     - {key}")

        if not args.execute:
            print(f"\n⏸️  未执行任何修改。请添加 --execute 参数实际运行。")
        else:
            db.commit()
            print(f"\n✅ 清理完成！所有校验字段已重置为 pending 状态。")
            print(f"   来源表中的 {result['deleted_sources_count']} 条记录已删除。")

    finally:
        db.close()


if __name__ == "__main__":
    main()
