"""
检查项目4的数据保存情况
"""
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库连接
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./novel_app.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def check_project_4():
    """检查项目4的数据"""
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("📊 检查项目4的数据保存情况")
        print("=" * 80)
        
        # 1. 检查项目基本信息
        print("\n1️⃣ 项目基本信息:")
        project_query = text("""
            SELECT id, title, genre, created_at, updated_at
            FROM projects
            WHERE id = 4
        """)
        project = db.execute(project_query).fetchone()
        
        if project:
            print(f"   项目ID: {project[0]}")
            print(f"   标题: {project[1]}")
            print(f"   题材: {project[2]}")
            print(f"   创建时间: {project[3]}")
            print(f"   更新时间: {project[4]}")
        else:
            print("   ❌ 项目4不存在！")
            return
        
        # 2. 检查 project_settings 表
        print("\n2️⃣ 项目设定 (project_settings):")
        settings_query = text("""
            SELECT concept, world_setting, characters, plot_outline,
                   stage_one_status, stage_two_status, 
                   created_at, updated_at
            FROM project_settings
            WHERE project_id = 4
        """)
        settings = db.execute(settings_query).fetchone()
        
        if settings:
            # 解析 JSON 字段
            concept = settings[0]
            world_setting = settings[1]
            characters = settings[2]
            plot_outline = settings[3]
            
            print(f"   阶段一状态: {settings[4]}")
            print(f"   阶段二状态: {settings[5]}")
            print(f"   创建时间: {settings[6]}")
            print(f"   更新时间: {settings[7]}")
            
            # 概念数据
            if concept:
                try:
                    concept_data = json.loads(concept) if isinstance(concept, str) else concept
                    concept_len = len(str(concept_data))
                    print(f"\n   ✅ 故事概念: 已保存 ({concept_len} 字符)")
                    print(f"      预览: {str(concept_data)[:200]}...")
                except:
                    print(f"   ⚠️  故事概念: 数据格式异常")
                    print(f"      原始数据: {str(concept)[:200]}")
            else:
                print(f"   ❌ 故事概念: 未保存 (NULL)")
            
            # 世界观数据
            if world_setting:
                try:
                    world_data = json.loads(world_setting) if isinstance(world_setting, str) else world_setting
                    world_len = len(str(world_data))
                    print(f"\n   ✅ 世界观设定: 已保存 ({world_len} 字符)")
                    print(f"      预览: {str(world_data)[:200]}...")
                except:
                    print(f"   ⚠️  世界观设定: 数据格式异常")
                    print(f"      原始数据: {str(world_setting)[:200]}")
            else:
                print(f"   ❌ 世界观设定: 未保存 (NULL)")
            
            # 人物数据
            if characters:
                try:
                    char_data = json.loads(characters) if isinstance(characters, str) else characters
                    char_len = len(str(char_data))
                    print(f"\n   ✅ 人物设定: 已保存 ({char_len} 字符)")
                    print(f"      预览: {str(char_data)[:200]}...")
                except:
                    print(f"   ⚠️  人物设定: 数据格式异常")
                    print(f"      原始数据: {str(characters)[:200]}")
            else:
                print(f"   ❌ 人物设定: 未保存 (NULL)")
            
            # 情节大纲
            if plot_outline:
                try:
                    outline_data = json.loads(plot_outline) if isinstance(plot_outline, str) else plot_outline
                    outline_len = len(str(outline_data))
                    print(f"\n   ✅ 情节大纲: 已保存 ({outline_len} 字符)")
                except:
                    print(f"   ⚠️  情节大纲: 数据格式异常")
            else:
                print(f"   ❌ 情节大纲: 未保存 (NULL)")
                
        else:
            print("   ❌ project_settings 记录不存在！")
        
        # 3. 检查 generation_history 表
        print("\n3️⃣ 任务历史 (generation_history):")
        history_query = text("""
            SELECT task_id, task_type, status, created_at, completed_at
            FROM generation_history
            WHERE project_id = 4
            ORDER BY created_at DESC
            LIMIT 10
        """)
        histories = db.execute(history_query).fetchall()
        
        if histories:
            print(f"   最近10条任务记录:")
            for i, h in enumerate(histories, 1):
                print(f"   {i}. {h[1]}: {h[2]} (创建: {h[3]}, 完成: {h[4]})")
        else:
            print("   ❌ 无任务记录")
        
        # 4. 检查 characters 表
        print("\n4️⃣ 人物表 (characters):")
        char_query = text("""
            SELECT id, name, role, faction, summary
            FROM characters
            WHERE project_id = 4
            LIMIT 10
        """)
        chars = db.execute(char_query).fetchall()
        
        if chars:
            print(f"   已解析的人物 ({len(chars)} 个):")
            for char in chars:
                print(f"   - {char[1]} ({char[2]}, {char[3]}): {char[4][:50] if char[4] else ''}...")
        else:
            print("   ❌ 无人物记录")
        
        # 5. 检查 memory 表
        print("\n5️⃣ 记忆表 (memory):")
        memory_query = text("""
            SELECT current_scene, current_chapter, messages, updated_at
            FROM memory
            WHERE project_id = 4
        """)
        memory = db.execute(memory_query).fetchone()
        
        if memory:
            messages = memory[2]
            msg_count = len(messages) if messages else 0
            print(f"   当前场景: {memory[0]}")
            print(f"   当前章节: {memory[1]}")
            print(f"   消息数量: {msg_count}")
            print(f"   更新时间: {memory[3]}")
        else:
            print("   ❌ 无记忆记录")
        
        print("\n" + "=" * 80)
        print("✅ 检查完成")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_project_4()
