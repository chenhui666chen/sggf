"""
初始化管理控制台数据
创建预设角色和权限
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.role import Role, Permission
from app.models.user import User
from app.core.security import hash_password


def init_permissions(db: Session):
    """初始化权限"""
    permissions_data = [
        # 用户管理
        {"code": "user:read", "name": "查看用户", "resource": "user", "action": "read"},
        {"code": "user:write", "name": "编辑用户", "resource": "user", "action": "write"},
        {"code": "user:delete", "name": "删除用户", "resource": "user", "action": "delete"},
        
        # 角色管理
        {"code": "role:read", "name": "查看角色", "resource": "role", "action": "read"},
        {"code": "role:write", "name": "编辑角色", "resource": "role", "action": "write"},
        {"code": "role:delete", "name": "删除角色", "resource": "role", "action": "delete"},
        
        # 日志管理
        {"code": "log:read", "name": "查看日志", "resource": "log", "action": "read"},
        {"code": "log:export", "name": "导出日志", "resource": "log", "action": "export"},
        
        # 统计数据
        {"code": "stats:read", "name": "查看统计", "resource": "stats", "action": "read"},
        
        # 系统配置
        {"code": "system:read", "name": "查看配置", "resource": "system", "action": "read"},
        {"code": "system:write", "name": "修改配置", "resource": "system", "action": "write"},
    ]
    
    created_count = 0
    for perm_data in permissions_data:
        existing = db.query(Permission).filter(Permission.code == perm_data["code"]).first()
        if not existing:
            permission = Permission(**perm_data)
            db.add(permission)
            created_count += 1
    
    db.commit()
    print(f"✅ 初始化权限完成，创建了 {created_count} 个权限")
    
    return db.query(Permission).all()


def init_roles(db: Session, permissions: list):
    """初始化角色"""
    roles_data = [
        {
            "code": "super_admin",
            "name": "超级管理员",
            "description": "拥有所有权限",
            "is_system": True,
            "permission_codes": ["*"]
        },
        {
            "code": "admin",
            "name": "管理员",
            "description": "用户管理、日志查看、统计",
            "is_system": True,
            "permission_codes": [
                "user:read", "user:write",
                "role:read",
                "log:read", "log:export",
                "stats:read",
                "system:read"
            ]
        },
        {
            "code": "user",
            "name": "普通用户",
            "description": "基础用户角色",
            "is_system": True,
            "permission_codes": []
        }
    ]
    
    created_count = 0
    for role_data in roles_data:
        existing = db.query(Role).filter(Role.code == role_data["code"]).first()
        if not existing:
            role = Role(
                code=role_data["code"],
                name=role_data["name"],
                description=role_data["description"],
                is_system=role_data["is_system"]
            )
            
            if role_data["permission_codes"] != ["*"]:
                role_permissions = [
                    p for p in permissions 
                    if p.code in role_data["permission_codes"]
                ]
                role.permissions = role_permissions
            
            db.add(role)
            created_count += 1
    
    db.commit()
    print(f"✅ 初始化角色完成，创建了 {created_count} 个角色")


def create_super_admin(db: Session):
    """创建超级管理员账号"""
    super_admin_role = db.query(Role).filter(Role.code == "super_admin").first()
    
    if not super_admin_role:
        print("❌ 未找到超级管理员角色")
        return
    
    existing_admin = db.query(User).filter(User.email == "admin@sggf.net").first()
    
    if existing_admin:
        print("ℹ️  超级管理员账号已存在")
        if not existing_admin.roles:
            existing_admin.roles = [super_admin_role]
            db.commit()
            print("✅ 已为现有管理员分配超级管理员角色")
        return
    
    admin_user = User(
        username="admin",
        email="admin@sggf.net",
        password_hash=hash_password("Admin@123456"),
        full_name="超级管理员",
        is_active=True,
        roles=[super_admin_role]
    )
    
    db.add(admin_user)
    db.commit()
    
    print("✅ 创建超级管理员账号成功")
    print("   邮箱: admin@sggf.net")
    print("   密码: Admin@123456")
    print("   ⚠️  请登录后立即修改密码！")


def init_admin_data():
    """初始化管理控制台数据"""
    print("\n" + "="*50)
    print("开始初始化管理控制台数据...")
    print("="*50 + "\n")
    
    db = SessionLocal()
    
    try:
        permissions = init_permissions(db)
        init_roles(db, permissions)
        create_super_admin(db)
        
        print("\n" + "="*50)
        print("✅ 管理控制台数据初始化完成！")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n❌ 初始化失败: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_admin_data()
