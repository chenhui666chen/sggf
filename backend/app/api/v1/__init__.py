"""
API v1 路由模块
"""
from . import auth, projects, chapters, knowledge_base, reviews, workflow, settings
from . import characters


__all__ = [
    "auth",
    "projects",
    "chapters",
    "knowledge_base",
    "reviews",
    "workflow",
    "settings",
    "characters",
]

