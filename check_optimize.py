import sqlite3
import json

conn = sqlite3.connect('novel_app.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT task_id, status, progress, message, result, completed_at 
    FROM generation_history 
    WHERE task_type = "optimize_chapter" 
    ORDER BY created_at DESC 
    LIMIT 1
''')

row = cursor.fetchone()

if row:
    print('=' * 60)
    print('📊 最新优化任务状态')
    print('=' * 60)
    print(f'  任务ID: {row[0]}')
    print(f'  状态: {row[1]}')
    print(f'  进度: {row[2]}%')
    print(f'  消息: {row[3]}')
    print(f'  完成时间: {row[5]}')
    
    if row[4]:
        result = json.loads(row[4])
        print(f'\n📝 优化结果:')
        print(f'  有优化内容: {"✅ 是" if result.get("optimized_content") else "❌ 否"}')
        
        content = result.get("optimized_content", "")
        print(f'  内容长度: {len(content)} 字符')
        print(f'  原始评分: {result.get("original_score", "N/A")}')
        
        if content:
            print(f'\n📄 内容预览（前200字）:')
            print(f'  {content[:200]}...')
    else:
        print(f'\n❌ 无结果数据')
else:
    print('未找到优化任务')

conn.close()
