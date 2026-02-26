import sys
sys.path.insert(0, '/app')

from app.db.base import SessionLocal
from app.models.user import User
from app.models.project import Project

db = SessionLocal()
try:
    # 查找用户
    user = db.query(User).filter(User.email == '371640372@qq.com').first()
    if user:
        print(f'用户存在: {user.username}, {user.email}, ID: {user.id}')
        
        # 查找该用户的项目
        projects = db.query(Project).filter(Project.user_id == user.id).all()
        print(f'\n项目数量: {len(projects)}')
        
        for project in projects:
            print(f'\n项目 ID: {project.id}')
            print(f'标题: {project.title}')
            print(f'描述: {project.description}')
            print(f'类型: {project.genre}')
            print(f'创建时间: {project.created_at}')
    else:
        print('用户不存在')
        
        # 查找所有用户
        all_users = db.query(User).all()
        print(f'\n数据库中的所有用户:')
        for u in all_users:
            print(f'  - {u.username}, {u.email}, ID: {u.id}')
finally:
    db.close()
