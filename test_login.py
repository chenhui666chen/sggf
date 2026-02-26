import sys
sys.path.insert(0, '/app')

from app.api.v1.auth import login
from app.db.base import SessionLocal
from app.schemas.user import UserLogin

db = SessionLocal()
try:
    credentials = UserLogin(username='admin', password='admin123')
    result = login(credentials, db)
    print(f'登录成功！')
    print(f'Token: {result["access_token"][:50]}...')
    print(f'User: {result["user"]}')
except Exception as e:
    print(f'登录失败: {e}')
finally:
    db.close()
