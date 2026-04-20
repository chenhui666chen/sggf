"""Backward-compatible re-export hub.
All outline expansion code has been split into the outline_expansion package.
"""
from outline_expansion import OutlineExpander, create_outline_expander

__all__ = ["OutlineExpander", "create_outline_expander"]
