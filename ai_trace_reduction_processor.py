"""Compatibility wrapper for AI trace reduction processor.

This file allows legacy code and docs to import::

    from ai_trace_reduction_processor import AITraceReductionProcessor, reduce_ai_traces

while the real implementation lives in
``backend.app.services.agents.ai_trace_reduction_processor``.
"""

from backend.app.services.agents.ai_trace_reduction_processor import (
    AITraceReductionProcessor,
    reduce_ai_traces,
)

__all__ = [
    "AITraceReductionProcessor",
    "reduce_ai_traces",
]

