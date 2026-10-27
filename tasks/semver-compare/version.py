"""Compare release versions such as "1.10.0" and "1.9.2"."""


def parse(version: str) -> tuple:
    return tuple(version.lstrip("v").split("."))


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly later release than ``current``."""
    return parse(candidate) > parse(current)
