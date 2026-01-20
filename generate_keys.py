"""
生成生产环境安全密钥
"""
import secrets
import os

def generate_password(length=32):
    """生成随机密码"""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password

def generate_hex_key(length=64):
    """生成十六进制密钥"""
    return secrets.token_hex(length)

def generate_base64_key(length=32):
    """生成Base64密钥"""
    return secrets.token_urlsafe(length)

print("=" * 60)
print("拾光工坊 - 生产环境安全密钥生成")
print("=" * 60)
print()

# 生成PostgreSQL密码
postgres_password = generate_password(32)
print(f"PostgreSQL密码: {postgres_password}")
print()

# 生成Redis密码
redis_password = generate_password(16)
print(f"Redis密码: {redis_password}")
print()

# 生成JWT密钥
jwt_secret = generate_hex_key(32)
print(f"JWT密钥: {jwt_secret}")
print()

# 生成数据库连接URL
database_url = f"postgresql://novel_user:{postgres_password}@localhost:5432/novel_db"
print(f"DATABASE_URL: {database_url}")
print()

# 生成Redis连接URL
redis_url = f"redis://:{redis_password}@localhost:6379/0"
print(f"REDIS_URL: {redis_url}")
print()

print("=" * 60)
print("请将以上密钥复制到配置文件中")
print("=" * 60)
