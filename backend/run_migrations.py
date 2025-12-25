"""
检查并运行 Alembic 迁移
"""
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from alembic.config import Config
from alembic import command

# 创建 Alembic 配置
alembic_dir = backend_dir / "alembic"
ini_path = backend_dir.parent / "alembic.ini"

print(f"Alembic 目录：{alembic_dir}")
print(f"配置文件：{ini_path}")
print(f"配置文件存在：{ini_path.exists()}")

# 创建配置对象
config = Config(str(ini_path))

try:
    # 查看当前版本
    print("\n📋 当前数据库版本：")
    command.current(config)
    
    # 显示迁移历史
    print("\n📋 迁移历史：")
    command.history(config)
    
    # 升级到最新版本
    print("\n🚀 开始升级数据库...")
    command.upgrade(config, "head")
    print("\n✅ 数据库升级完成！")
    
    # 再次查看当前版本
    print("\n📋 升级后的数据库版本：")
    command.current(config)

except Exception as e:
    print(f"❌ 错误：{e}")
    import traceback
    traceback.print_exc()
