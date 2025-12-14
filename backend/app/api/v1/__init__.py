"""
API v1 路由模块
"""
from . import auth, projects, chapters, reviews, workflow, settings
from . import characters
from . import book_parser


__all__ = [
    "auth",
    "projects",
    "chapters",
    "reviews",
    "workflow",
    "settings",
    "characters",
    "book_parser",
]

