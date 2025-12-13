"""检查epic_framework字段是否包含锚点标记"""
import sqlite3
import re

db_path = "c:/Users/cuigu/novel_writing_agent/backend/novel_app.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查询最新的项目框架数据
    cursor.execute("""
        SELECT 
            project_id,
            CASE WHEN epic_framework IS NULL THEN 'NULL' 
                 WHEN epic_framework = '' THEN 'EMPTY' 
                 ELSE 'EXISTS' END as epic_framework_status,
            LENGTH(epic_framework) as epic_framework_length,
            CASE WHEN plot_outline IS NULL THEN 'NULL' 
                 WHEN plot_outline = '' THEN 'EMPTY' 
                 ELSE 'EXISTS' END as plot_outline_status,
            LENGTH(plot_outline) as plot_outline_length,
            epic_framework_generated_at,
            epic_framework
        FROM project_settings
        ORDER BY project_id DESC
        LIMIT 3
    """)
    
    results = cursor.fetchall()
    
    print("\n" + "="*80)
    print("📊 数据库中的epic_framework检查")
    print("="*80 + "\n")
    
    if not results:
        print("❌ 没有找到任何工作流数据")
    else:
        for row in results:
            project_id, epic_status, epic_len, outline_status, outline_len, generated_at, epic_content = row
            print(f"🆔 项目ID: {project_id}")
            print(f"   📖 epic_framework: {epic_status} (长度: {epic_len or 0})")
            print(f"   📝 plot_outline: {outline_status} (长度: {outline_len or 0})")
            print(f"   🕐 生成时间: {generated_at or '未设置'}")
            
            # 检查是否有锚点标记
            if epic_content:
                has_anchor = 'VOLUME_' in epic_content and 'ANCHOR_' in epic_content
                print(f"   🔗 是否有锚点标记: {'✅ 是' if has_anchor else '❌ 否'}")
                
                # 统计锚点数量
                anchor_pattern = re.compile(r'<!-- VOLUME_(\d+)_ANCHOR_START -->')
                anchors = anchor_pattern.findall(epic_content)
                if anchors:
                    print(f"   📍 锚点数量: {len(anchors)} 个 (卷{sorted(set(anchors))})")
                
                # 显示前200字符
                preview = epic_content[:200].replace('\n', ' ')
                print(f"   👀 前200字符: {preview}...")
            else:
                print(f"   ⚠️  epic_framework为空")
            
            print("-" * 80)
    
    conn.close()
    print("\n✅ 检查完成\n")
    
except Exception as e:
    print(f"\n❌ 错误: {e}\n")
    import traceback
    traceback.print_exc()
