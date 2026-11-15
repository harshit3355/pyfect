"""Header lines joined by name, as ``Headers`` holds them."""

from __future__ import annotations

from collections.abc import Iterable


def joined(lines: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Each name's values joined with ``", "``, in order. Collected first and
    joined once: appending to the joined text per line copies it each time,
    quadratic in a head of many lines of one name."""
    values: dict[str, list[str]] = {}
    for name, value in lines:
        values.setdefault(name, []).append(value)
    return {name: ", ".join(each) for name, each in values.items()}
