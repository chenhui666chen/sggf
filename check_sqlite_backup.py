import sqlite3
import sys

db_path = '/root/novel_writing_agent/database_backups/novel_app.db.bak-20260102-181959'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print(f'SQLite 数据库中的表: {[t[0] for t in tables]}\n')

# 检查每个表的记录数
for table in tables:
    table_name = table[0]
    try:
        cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
        count = cursor.fetchone()[0]
        print(f'{table_name}: {count} 条记录')
    except Exception as e:
        print(f'{table_name}: 查询失败 - {e}')

# 查找用户 371640372@qq.com
print('\n查找用户 371640372@qq.com:')
cursor.execute("SELECT * FROM users WHERE email = ?", ('371640372@qq.com',))
user = cursor.fetchone()
if user:
    print(f'用户 ID: {user[0]}, 用户名: {user[1]}, 邮箱: {user[2]}')
    
    # 查找该用户的项目
    cursor.execute("SELECT * FROM projects WHERE user_id = ?", (user[0],))
    projects = cursor.fetchall()
    print(f'项目数: {len(projects)}')
    
    for project in projects:
        print(f'  - 项目 ID: {project[0]}, 标题: {project[2]}, 描述: {project[3]}')
else:
    print('用户不存在')

conn.close()
