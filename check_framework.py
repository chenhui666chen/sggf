"""检查数据库中的框架数据"""
import sqlite3
from datetime import datetime

db_path = "c:/Users/cuigu/novel_writing_agent/backend/novel_app.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查询所有项目的框架信息
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
            SUBSTR(epic_framework, 1, 200) as epic_framework_preview
        FROM project_settings
        ORDER BY project_id DESC
        LIMIT 5
    """)
    
    results = cursor.fetchall()
    
    print("\n" + "="*80)
    print("📊 数据库中的框架数据状态")
    print("="*80 + "\n")
    
    if not results:
        print("❌ 没有找到任何项目设置数据")
    else:
        for row in results:
            project_id, epic_status, epic_len, outline_status, outline_len, generated_at, preview = row
            print(f"🆔 项目ID: {project_id}")
            print(f"   📖 epic_framework: {epic_status} (长度: {epic_len or 0})")
            print(f"   📝 plot_outline: {outline_status} (长度: {outline_len or 0})")
            print(f"   🕐 生成时间: {generated_at or '未设置'}")
            
            if preview:
                print(f"   👀 预览: {preview[:100]}...")
            
            # 检查是否有锚点标记
            if epic_len and epic_len > 0:
                cursor.execute("""
                    SELECT epic_framework
                    FROM project_settings
                    WHERE project_id = ?
                """, (project_id,))
                framework_content = cursor.fetchone()[0]
                
                has_anchor = 'VOLUME_' in framework_content and 'ANCHOR_' in framework_content
                print(f"   🔗 是否有锚点标记: {'✅ 是' if has_anchor else '❌ 否'}")
            
            print("-" * 80)
    
    conn.close()
    print("\n✅ 检查完成\n")
    
except Exception as e:
    print(f"\n❌ 错误: {e}\n")
