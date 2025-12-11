import sqlite3

conn = sqlite3.connect('novel_app.db')
cursor = conn.cursor()

# 查询最近的优化任务
cursor.execute('''
    SELECT task_id, status, progress, message, error, created_at, updated_at
    FROM generation_history 
    WHERE task_type = "optimize_chapter" 
    ORDER BY created_at DESC 
    LIMIT 5
''')

print('=' * 80)
print('最近的优化任务状态:')
print('=' * 80)
for row in cursor.fetchall():
    print(f'\n任务ID: {row[0]}')
    print(f'状态: {row[1]}')
    print(f'进度: {row[2]}%')
    print(f'消息: {row[3]}')
    print(f'错误: {row[4]}')
    print(f'创建时间: {row[5]}')
    print(f'更新时间: {row[6]}')
    print('-' * 80)

conn.close()
