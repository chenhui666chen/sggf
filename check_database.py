import sys
sys.path.insert(0, '/app')

from app.db.base import SessionLocal, engine
from app.models.user import User
from app.models.project import Project
from app.models.chapter import Chapter
from sqlalchemy import inspect, text

db = SessionLocal()
try:
    # 检查所有表
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f'数据库中的表: {tables}\n')
    
    # 检查每个表的记录数
    for table in tables:
        try:
            result = db.execute(text(f'SELECT COUNT(*) FROM {table}'))
            count = result.scalar()
            print(f'{table}: {count} 条记录')
        except Exception as e:
            print(f'{table}: 查询失败 - {e}')
    
    # 查找所有用户
    print('\n所有用户:')
    users = db.query(User).all()
    for user in users:
        print(f'  - ID: {user.id}, 用户名: {user.username}, 邮箱: {user.email}')
        
        # 查找该用户的项目
        projects = db.query(Project).filter(Project.user_id == user.id).all()
        print(f'    项目数: {len(projects)}')
        
        # 查找该用户的章节
        chapters = db.query(Chapter).join(Project).filter(Project.user_id == user.id).all()
        print(f'    章节数: {len(chapters)}')
        
finally:
    db.close()
