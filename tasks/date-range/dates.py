"""Booking date helpers."""

from datetime import date


def nights(check_in: date, check_out: date) -> int:
    return (check_out - check_in).days


def days_in_range(start: date, end: date) -> int:
    """Number of calendar days from ``start`` to ``end``, both included.

    Raises ValueError if ``end`` is before ``start``.
    """
    return (end - start).days
