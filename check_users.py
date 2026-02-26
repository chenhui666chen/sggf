from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql://novel_user:NovelPostgres0t649OyRUaI@localhost:5432/novel_db')
Session = sessionmaker(bind=engine)
session = Session()

try:
    users = session.execute(text('SELECT id, username, email, is_active FROM users')).fetchall()
    print('Users:', users)
    
    if users:
        print('\n用户数据存在！')
        for user in users:
            print(f'ID: {user[0]}, Username: {user[1]}, Email: {user[2]}, Active: {user[3]}')
    else:
        print('\n用户数据为空！')
except Exception as e:
    print(f'Error: {e}')
finally:
    session.close()
    engine.dispose()
