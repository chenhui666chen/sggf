"""
基础提示词模块

包含所有阶段共用的基础组件：
- role.py: 角色定义
- quality.py: 质量标准
- format.py: 输出格式
"""

from .role import ROLE_DEFINITIONS
from .quality import QUALITY_STANDARDS
from .format import OUTPUT_FORMATS

__all__ = ['ROLE_DEFINITIONS', 'QUALITY_STANDARDS', 'OUTPUT_FORMATS']
