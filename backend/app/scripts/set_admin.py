"""
将指定用户设置为管理员
"""
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.user import User
from app.models.role import Role


def set_user_as_admin(email: str):
    """将用户设置为管理员"""
    db: Session = SessionLocal()
    
    try:
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            print(f"❌ 未找到邮箱为 {email} 的用户")
            return False
        
        admin_role = db.query(Role).filter(Role.code == "admin").first()
        
        if not admin_role:
            print("❌ 未找到管理员角色，请先运行 init_admin_data.py 初始化数据")
            return False
        
        if admin_role in user.roles:
            print(f"ℹ️  用户 {user.username} ({email}) 已经是管理员")
            return True
        
        user.roles.append(admin_role)
        db.commit()
        
        print(f"✅ 已将用户 {user.username} ({email}) 设置为管理员")
        print(f"   用户ID: {user.id}")
        print(f"   当前角色: {[r.name for r in user.roles]}")
        
        return True
        
    except Exception as e:
        print(f"❌ 操作失败: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    
    email = sys.argv[1] if len(sys.argv) > 1 else "371640372@qq.com"
    
    print("\n" + "="*50)
    print(f"设置用户为管理员: {email}")
    print("="*50 + "\n")
    
    set_user_as_admin(email)
    
    print("\n" + "="*50 + "\n")
