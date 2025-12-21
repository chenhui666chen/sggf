"""
测试 CosyVoice v3-plus 模型效果对比
选择精品章节进行测试
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.db.base import get_db
from app.models.project import Project, Chapter
from sqlalchemy.orm import Session


def select_test_chapters(db: Session):
    """选择用于测试的精品章节"""
    # 获取所有项目
    projects = db.query(Project).all()
    
    if not projects:
        print("❌ 没有找到项目")
        return None, None
    
    print(f"\n📚 找到 {len(projects)} 个项目:")
    for i, p in enumerate(projects[:10], 1):
        chapter_count = db.query(Chapter).filter(Chapter.project_id == p.id).count()
        print(f"  {i}. 项目{p.id}: {p.title} ({p.genre or '未知'}) - {chapter_count}章")
    
    # 选择第一个有章节的项目
    selected_project = None
    for p in projects:
        chapter_count = db.query(Chapter).filter(Chapter.project_id == p.id).count()
        if chapter_count > 0:
            selected_project = p
            break
    
    if not selected_project:
        print("❌ 没有找到有章节的项目")
        return None, None
    
    print(f"\n✅ 选择项目: {selected_project.title}")
    
    # 获取该项目的章节
    chapters = db.query(Chapter).filter(
        Chapter.project_id == selected_project.id
    ).order_by(Chapter.chapter_number).all()
    
    if not chapters:
        print("❌ 项目没有章节")
        return None, None
    
    # 推荐选择：第1章（开篇）和中间章节（可能是高潮）
    chapter_1 = chapters[0] if len(chapters) > 0 else None
    chapter_mid = chapters[len(chapters) // 2] if len(chapters) > 1 else None
    
    print(f"\n🎯 推荐测试章节:")
    print(f"  1. 第{chapter_1.chapter_number}章: {chapter_1.title} ({len(chapter_1.content)}字)")
    if chapter_mid and chapter_mid != chapter_1:
        print(f"  2. 第{chapter_mid.chapter_number}章: {chapter_mid.title} ({len(chapter_mid.content)}字)")
    
    return selected_project, [chapter_1, chapter_mid] if chapter_mid else [chapter_1]


def show_model_comparison():
    """显示模型对比信息"""
    print("\n" + "="*70)
    print("📊 CosyVoice 模型对比")
    print("="*70)
    print("\n🔹 qwen3-tts-flash (当前使用)")
    print("  - 音质: ⭐⭐⭐⭐ (优秀)")
    print("  - 速度: ⚡⚡⚡⚡⚡ (非常快)")
    print("  - 成本: 💰💰 (0.002元/100字)")
    print("  - 适用: 日常生产，批量生成")
    
    print("\n🔹 cosyvoice-v3-plus (待测试)")
    print("  - 音质: ⭐⭐⭐⭐⭐ (顶级)")
    print("  - 速度: ⚡⚡⚡⚡ (快)")
    print("  - 成本: 💰💰💰💰 (0.004元/100字，2倍价格)")
    print("  - 适用: 精品章节，重点内容")
    
    print("\n💡 测试目标:")
    print("  1. 对比音质提升是否明显")
    print("  2. 评估2倍成本是否值得")
    print("  3. 确定使用场景（全部用 or 仅精品章节）")
    print("="*70)


async def main():
    """主函数"""
    print("🎭 CosyVoice v3-plus 精品章节测试")
    
    # 显示模型对比
    show_model_comparison()
    
    # 获取数据库会话
    db = next(get_db())
    
    try:
        # 选择测试章节
        project, chapters = select_test_chapters(db)
        
        if not project or not chapters:
            print("\n❌ 无法选择测试章节")
            return
        
        print(f"\n📝 下一步操作:")
        print(f"  1. 修改 engine.py 和 tts_engine.py")
        print(f"  2. 将 model='qwen3-tts-flash' 改为 model='cosyvoice-v3-plus'")
        print(f"  3. 通过前端生成这些章节的有声书")
        print(f"  4. 下载并对比音质效果")
        
        print(f"\n🎯 测试章节ID:")
        for ch in chapters:
            if ch:
                print(f"  - Chapter {ch.id}: 第{ch.chapter_number}章 《{ch.title}》")
        
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
