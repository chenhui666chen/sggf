import sys
sys.path.insert(0, '/app')

from app.api.v1.auth import verify_password
from app.models.user import User
from app.database import SessionLocal

db = SessionLocal()
try:
    user = db.query(User).filter(User.username == 'admin').first()
    if user:
        print(f'用户存在: {user.username}, {user.email}')
        print(f'密码哈希: {user.password_hash[:50]}...')
        result = verify_password('admin123', user.password_hash)
        print(f'密码验证结果: {result}')
    else:
        print('用户不存在')
finally:
    db.close()
