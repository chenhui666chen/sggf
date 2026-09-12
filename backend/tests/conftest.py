"""测试级公共引导（pytest 收集前生效）。

把 backend 与仓库根目录加入 sys.path：`core.model_resolution` 等顶层包
位于仓库根目录，旧测试文件只插入 backend 时会在收集阶段 ImportError。
"""
import os
import sys
from pathlib import Path

# 测试专用 openid 密钥（P2-4.1），非生产密钥。
# 必须在任何 test 模块导入 app.* 之前注入：`app.core.config.settings` 在首次导入时
# 快照环境变量，若被其它测试文件抢先导入，crypto 单例会永久处于"未配置"状态，
# 导致认证相关测试依赖执行顺序。这里统一注入，消除顺序耦合。
os.environ["OPENID_LOOKUP_KEY"] = "test-openid-lookup-key"
os.environ["OPENID_ENCRYPTION_KEY"] = "iywK1Okx4dQcGCqh8OhpVIvg95jqLBfn2DASspPLK1Q="
# Cookie 认证（P2-4.5）：测试用非 Secure、空前缀（http 本地环境模拟）
os.environ["COOKIE_SECURE"] = "false"
os.environ["COOKIE_PREFIX"] = ""
# 审计日志（P2-4.4）：测试 pepper（与生产密钥无关）
os.environ["AUDIT_LOG_PEPPER"] = "test-audit-log-pepper"

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
