"""
初始化管理控制台数据
创建预设角色和权限
"""
import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.password_policy import check_password_strength
from app.core.security import hash_password
from app.db.base import SessionLocal
from app.models.role import Role, Permission
from app.models.user import User
from app.services.password_history_service import password_history_service


def resolve_initial_admin_password() -> str:
    """初始超管密码（P2-4.6：去硬编码）。

    - 优先 INITIAL_ADMIN_PASSWORD 环境变量，**必须符合密码策略**（评审 #4：必填 ≠ 必强）；
    - production/staging 未配置必须报错（禁止再用可 grep 的固定默认密码建号）；
    - development 未配置随机生成直至符合策略（base64url 可能缺数字/大小写，需重试），
      仅 stdout 展示，不写日志文件。
    """
    configured = str(settings.INITIAL_ADMIN_PASSWORD or "").strip()
    if configured:
        message = check_password_strength(configured)
        if message is not None:
            raise RuntimeError(f"INITIAL_ADMIN_PASSWORD 不符合密码策略：{message}")
        return configured
    if settings.APP_ENV in ("production", "staging"):
        raise RuntimeError(
            "生产/预发布环境必须配置 INITIAL_ADMIN_PASSWORD（禁止使用可 grep 的固定默认密码）"
        )
    for _ in range(5):
        candidate = secrets.token_urlsafe(12)
        if check_password_strength(candidate) is None:
            return candidate
    raise RuntimeError("无法生成符合密码策略的随机初始密码")


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
    """创建超级管理员账号（P2-4.6：密码来自环境变量/随机，不再硬编码）。

    "已有超管不覆盖"语义保持：存在即补角色后 return，绝不重置现网超管密码。
    """
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
    
    password = resolve_initial_admin_password()
    admin_user = User(
        username="admin",
        email="admin@sggf.net",
        password_hash=hash_password(password),
        full_name="超级管理员",
        is_active=True,
        roles=[super_admin_role]
    )
    
    db.add(admin_user)
    db.flush()  # 取 id：初始密码与建号同事务登记入历史（评审收口，否则可改回初始密码）
    password_history_service.record(db, admin_user.id, password)
    db.commit()
    
    print("✅ 创建超级管理员账号成功")
    print("   邮箱: admin@sggf.net")
    print("   ⚠️  请登录后立即修改密码！")
    if settings.APP_ENV not in ("production", "staging"):
        # 仅 development：临时密码只在本次 stdout 出现，不入日志文件
        print(f"   临时密码: {password}（仅本次显示，请立即修改）")


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
