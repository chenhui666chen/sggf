"""
检查并运行 Alembic 迁移
"""
import sys
from pathlib import Path

# 切换到项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic.config import Config
from alembic import command

# 创建 Alembic 配置
ini_path = project_root / "alembic.ini"

print(f"项目根目录：{project_root}")
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
