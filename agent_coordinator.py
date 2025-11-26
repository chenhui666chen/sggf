"""Compatibility wrapper for CreativeDirectorCoordinator.

Historically the coordinator was imported as::

    from agent_coordinator import CreativeDirectorCoordinator

The actual implementation now lives in
``backend.app.services.agents.agent_coordinator``. This thin wrapper keeps
existing tests and docs working without changing the core package layout.
"""

from backend.app.services.agents.agent_coordinator import CreativeDirectorCoordinator

__all__ = ["CreativeDirectorCoordinator"]

