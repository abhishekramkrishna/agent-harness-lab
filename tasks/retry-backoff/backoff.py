"""Exponential backoff for retrying flaky calls."""


def delay(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    Doubles each attempt, starting at ``base``, never above ``cap``.
    """
    return min(cap, base * 2 * attempt)
