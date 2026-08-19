"""测试级公共引导（pytest 收集前生效）。

把 backend 与仓库根目录加入 sys.path：`core.model_resolution` 等顶层包
位于仓库根目录，旧测试文件只插入 backend 时会在收集阶段 ImportError。
"""
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
