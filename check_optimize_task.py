import sqlite3

conn = sqlite3.connect('novel_app.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT task_id, task_type, status, progress, message, error, created_at
    FROM generation_history 
    WHERE task_type = "optimize_chapter" 
    ORDER BY created_at DESC 
    LIMIT 3
''')

print('最近的优化任务:')
for row in cursor.fetchall():
    print(f'  TaskID: {row[0]}')
    print(f'  Status: {row[2]}')
    print(f'  Progress: {row[3]}')
    print(f'  Message: {row[4]}')
    print(f'  Error: {row[5]}')
    print(f'  Created: {row[6]}')
    print('---')

conn.close()
