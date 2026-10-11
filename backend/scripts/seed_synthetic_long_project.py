# -*- coding: utf-8 -*-
"""长篇上下文压测数据生成脚本（阶段 A）。

在开发库创建合成项目与固定规模章节，供章节生成链路跑真实查询/payload/RAG 观测：
- 正文固定约 3000 字、摘要固定，保证三档项目口径一致、结果可复现；
- 每章正文带章节号标记，便于检索与覆盖验证；
- 默认 dry-run，落库须显式 `--apply`；`--rebuild` 删除同名旧项目后重建。

用法（backend 目录下）：

    # 预览 500 章合成项目
    python scripts/seed_synthetic_long_project.py --chapters 500
    # 落库 1000 章
    python scripts/seed_synthetic_long_project.py --chapters 1000 --apply
    # 重建 2000 章（删除同名旧项目）
    python scripts/seed_synthetic_long_project.py --chapters 2000 --rebuild --apply
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402

# 单章正文目标字符数（约 3000 字）
TARGET_CONTENT_CHARS = 3000
# 批量插入每批章节数
BATCH_SIZE = 100


def _build_content(chapter_number: int) -> str:
    """生成确定性的合成正文，约 3000 字符，含章节号便于检索验证。"""
    marker = (
        f"第{chapter_number}章 合成标题{chapter_number}\n\n"
        f"[SYNTHETIC] 本章关键事件：事件{chapter_number}发生，"
        f"人物甲推动第{chapter_number}段剧情，结尾留下悬念{chapter_number}。\n\n"
    )
    sentence = (
        f"这是第{chapter_number}章的合成正文，用于长篇上下文压测，"
        "内容固定且可复现，角色按既定安排推进情节，场景在固定地点展开。"
    )
    parts = [marker]
    current = len(marker)
    while current < TARGET_CONTENT_CHARS:
        parts.append(sentence)
        current += len(sentence) + 1
    parts.append(f"\n（合成正文结束，章节号 {chapter_number}）")
    return "\n".join(parts)


def _build_summary(chapter_number: int) -> str:
    """生成固定的章节摘要。"""
    return f"第{chapter_number}章摘要：事件{chapter_number}发生，剧情按合成计划推进。"


def _resolve_user(db: Session, user_id: int | None) -> User:
    if user_id is not None:
        user = db.get(User, user_id)
        if user is None:
            raise SystemExit(f"用户不存在：id={user_id}")
        return user
    first = db.execute(select(User).order_by(User.id.asc()).limit(1)).scalar_one_or_none()
    if first is None:
        raise SystemExit("数据库中无用户，请先用 --user-id 指定或创建用户")
    return first


def _next_display_no(db: Session, user_id: int) -> int:
    projects = db.execute(
        select(Project.display_no)
        .where(Project.user_id == user_id)
        .order_by(Project.display_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    return int(projects or 0) + 1


def _find_project(db: Session, title: str) -> Project | None:
    return db.execute(
        select(Project).where(Project.title == title).limit(1)
    ).scalar_one_or_none()


def seed(db: Session, *, chapters: int, user_id: int | None, rebuild: bool) -> None:
    user = _resolve_user(db, user_id)
    title = f"[合成压测]{chapters}章"
    project = _find_project(db, title)

    if project is not None and rebuild:
        print(f"[REBUILD] 删除旧合成项目：id={project.id} title={title}")
        db.delete(project)
        db.commit()
        project = None

    if project is None:
        project = Project(
            display_no=_next_display_no(db, user.id),
            user_id=user.id,
            title=title,
            description="阶段 A 长篇上下文压测合成项目（自动生成，可安全删除）",
            genre="玄幻",
            status="writing",
        )
        db.add(project)
        db.commit()
        print(f"[CREATE] 合成项目：id={project.id} title={title} user={user.id}")
    else:
        print(f"[REUSE] 已存在合成项目：id={project.id} title={title}")

    existing_numbers = {
        num
        for num in db.execute(
            select(Chapter.chapter_number).where(Chapter.project_id == project.id)
        ).scalars()
    }
    missing = [n for n in range(1, chapters + 1) if n not in existing_numbers]
    print(f"[SEED] 待写入章节：{len(missing)} 章（已有 {len(existing_numbers)} 章）")

    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        mappings = [
            {
                "project_id": project.id,
                "chapter_number": number,
                "title": f"第{number}章 合成标题{number}",
                "content": _build_content(number),
                "summary": _build_summary(number),
                "status": "published",
                "word_count": TARGET_CONTENT_CHARS,
            }
            for number in batch
        ]
        db.bulk_insert_mappings(Chapter, mappings)
        db.commit()
        print(f"  ...已写入至第 {batch[-1]} 章")

    print(f"[DONE] 合成项目就绪：project_id={project.id}，共 {chapters} 章")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="长篇上下文压测合成数据")
    parser.add_argument("--chapters", type=int, default=500, help="章节数（500/1000/2000）")
    parser.add_argument("--user-id", type=int, default=None, help="归属用户 ID（默认首个用户）")
    parser.add_argument("--rebuild", action="store_true", help="删除同名旧项目后重建")
    parser.add_argument("--apply", action="store_true", help="落库（默认 dry-run）")
    args = parser.parse_args(argv)

    if args.chapters <= 0:
        parser.error("--chapters 必须为正整数")

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as db:
        if not args.apply:
            user = _resolve_user(db, args.user_id)
            title = f"[合成压测]{args.chapters}章"
            project = _find_project(db, title)
            print("[DRY-RUN] 将写入合成数据：")
            print(f"  项目标题：{title}（{'重建' if args.rebuild and project else '新建/复用'}）")
            print(f"  归属用户：id={user.id}")
            print(f"  章节数量：{args.chapters}，单章约 {TARGET_CONTENT_CHARS} 字")
            print("  加 --apply 落库")
            return 0

        seed(db, chapters=args.chapters, user_id=args.user_id, rebuild=args.rebuild)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
