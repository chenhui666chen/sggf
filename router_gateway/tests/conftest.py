# -*- coding: utf-8 -*-
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: 需要真实云凭证与公网网络的端到端测试，默认跳过（opt-in 环境变量开启）")
