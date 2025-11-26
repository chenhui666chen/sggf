"""Compatibility wrapper for author voice system.

Exposes the public API from ``backend.app.services.agents.author_voice_system``
so that code can use the flat imports documented in the guides, e.g.::

    from author_voice_system import (
        AuthorVoiceProfile, AuthorVoiceManager,
        create_voice_profile, get_voice_manager,
    )
"""

from backend.app.services.agents.author_voice_system import (
    AuthorVoiceProfile,
    AuthorVoiceManager,
    create_voice_profile,
    get_voice_manager,
)

__all__ = [
    "AuthorVoiceProfile",
    "AuthorVoiceManager",
    "create_voice_profile",
    "get_voice_manager",
]

