"""Backward-compatible re-export hub.
All outline expansion code has been split into the outline_expansion package.
"""
from ..consistency_validator import get_chapter_renumberer, get_consistency_validator
from .outline_expansion import OutlineExpander, create_outline_expander

__all__ = [
    "OutlineExpander",
    "create_outline_expander",
    "get_chapter_renumberer",
    "get_consistency_validator",
]
