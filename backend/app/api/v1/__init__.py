"""
API v1 路由模块
"""
from . import auth, projects, chapters, reviews, workflow, settings
from . import characters
from . import book_parser
from . import model_catalog
from . import asset_studio
from . import user_assets
from . import user_center


__all__ = [
    "auth",
    "projects",
    "chapters",
    "reviews",
    "workflow",
    "settings",
    "characters",
    "book_parser",
    "model_catalog",
    "asset_studio",
    "user_assets",
    "user_center",
]

