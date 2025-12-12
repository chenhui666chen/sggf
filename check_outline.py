import sqlite3

conn = sqlite3.connect('novel_app.db')
cursor = conn.cursor()

# 查看所有表
print('📂 数据库中的表：')
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(tables)
print()

# 获取最新项目
cursor.execute('''SELECT id, title, genre, planned_length_type, 
                  planned_chapters_min, planned_chapters_max 
                  FROM projects ORDER BY id DESC LIMIT 1''')
row = cursor.fetchone()

if row:
    print(f'📝 项目ID: {row[0]}')
    print(f'📚 标题: {row[1]}')
    print(f'🎭 题材: {row[2]}')
    print(f'📊 篇幅: {row[3]}')
    print(f'📚 章节范围: {row[4]}-{row[5]}')
    
    project_id = row[0]
    
    # 查找大纲内容（尝试多个可能的表名）
    possible_tables = ['workflow_stages', 'stages', 'project_stages', 'outlines']
    outline_content = None
    
    for table_name in possible_tables:
        if table_name in tables:
            try:
                cursor.execute(f'''SELECT content FROM {table_name} 
                                 WHERE project_id = ? AND (stage = 'structure' OR stage = 'outline')''', (project_id,))
                outline_row = cursor.fetchone()
                if outline_row and outline_row[0]:
                    outline_content = outline_row[0]
                    print(f'\n✅ 从表 {table_name} 找到大纲')
                    break
            except:
                pass
    
    if outline_content:
        print(f'\n📏 大纲总长度: {len(outline_content)} 字符')
        print(f'\n🔍 大纲内容预览（前3000字符）：')
        print('='*70)
        print(outline_content[:3000])
        print('='*70)
        print(f'\n... (还有 {len(outline_content) - 3000} 字符)')
    else:
        print('\n⚠️ 未找到大纲内容')
        print('尝试查询所有表的结构...')
        for table in tables:
            cursor.execute(f'PRAGMA table_info({table})')
            columns = cursor.fetchall()
            print(f'\n表 {table} 的字段：')
            print([col[1] for col in columns])
else:
    print('⚠️ 未找到项目')

conn.close()
