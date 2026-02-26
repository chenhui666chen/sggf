from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json

engine = create_engine('postgresql://novel_user:NovelPostgres0t649OyRUaI@postgres:5432/novel_db')
Session = sessionmaker(bind=engine)
session = Session()

try:
    with open('users_export.json', 'r', encoding='utf-8') as f:
        users_data = json.load(f)
    
    print(f'准备导入 {len(users_data)} 个用户')
    
    for user_data in users_data:
        try:
            session.execute(text('''
                INSERT INTO users (id, username, email, password_hash, full_name, is_active, created_at, updated_at)
                VALUES (:id, :username, :email, :password_hash, :full_name, :is_active, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    full_name = EXCLUDED.full_name,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
            '''), user_data)
            print(f'导入用户: {user_data["username"]} ({user_data["email"]})')
        except Exception as e:
            print(f'导入用户 {user_data["username"]} 失败: {e}')
    
    session.commit()
    print('所有用户数据导入成功！')
    
except Exception as e:
    print(f'Error: {e}')
    session.rollback()
finally:
    session.close()
    engine.dispose()
