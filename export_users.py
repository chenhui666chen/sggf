from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json
import sys

engine = create_engine('postgresql://novel_user:NovelPostgres0t649OyRUaI@localhost:5432/novel_db')
Session = sessionmaker(bind=engine)
session = Session()

try:
    users = session.execute(text('SELECT id, username, email, password_hash, full_name, is_active FROM users')).fetchall()
    
    print(f'找到 {len(users)} 个用户')
    
    user_data = []
    for user in users:
        user_data.append({
            'id': user[0],
            'username': user[1],
            'email': user[2],
            'password_hash': user[3],
            'full_name': user[4],
            'is_active': user[5]
        })
    
    with open('users_export.json', 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)
    
    print('用户数据已导出到 users_export.json')
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
finally:
    session.close()
    engine.dispose()
