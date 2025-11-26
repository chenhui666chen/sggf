"""Compatibility facade for legacy imports.

This module exposes the Config class used by the AI trace / multi-agent
modules so that older code and tests can simply use::

    from config import Config

Internally it forwards to backend.app.services.agents.config.Config.
"""

from backend.app.services.agents.config import Config

__all__ = ["Config"]

