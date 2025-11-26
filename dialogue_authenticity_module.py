"""Compatibility wrapper for dialogue authenticity module.

For legacy imports::

    from dialogue_authenticity_module import (
        DialogueAuthenticityEngine,
        optimize_dialogue_rhythm,
        analyze_dialogue_authenticity,
    )
"""

from backend.app.services.agents.dialogue_authenticity_module import (
    DialogueAuthenticityEngine,
    enhance_dialogue_authenticity,
    optimize_dialogue_rhythm,
    analyze_dialogue_authenticity,
)

__all__ = [
    "DialogueAuthenticityEngine",
    "enhance_dialogue_authenticity",
    "optimize_dialogue_rhythm",
    "analyze_dialogue_authenticity",
]

