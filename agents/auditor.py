from __future__ import annotations

from typing import Any

from adapters.mock.review import MockReviewAdapter


def run(ctx: Any) -> dict:
    review = MockReviewAdapter()
    result = review.check(ctx.payload)
    ctx.payload["audit"] = result
    return result
