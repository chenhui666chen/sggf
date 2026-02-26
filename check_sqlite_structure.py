import sqlite3

db_path = '/root/novel_writing_agent/database_backups/novel_app.db.bak-20260102-181959'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 查看用户表的结构
cursor.execute("PRAGMA table_info(users)")
columns = cursor.fetchall()
print('users 表结构:')
for col in columns:
    print(f'  {col[1]}: {col[2]}')

# 查看用户数据
print('\n用户数据示例:')
cursor.execute("SELECT * FROM users LIMIT 2")
users = cursor.fetchall()
for user in users:
    print(f'  {user}')

conn.close()
