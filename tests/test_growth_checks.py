"""A check that work grows linearly, or stays cheap, measures the work, never the wall clock.

Wall-clock time counts every moment the test waited for a CPU, so on a loaded machine a
linear call looks quadratic. ``tests/_growth.py`` measures the thread's CPU time; a test
that counts its work (visits, steps) needs no clock at all.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

_TESTS = Path(__file__).parent
_GROWTH_NAME = re.compile(r"linear|quadratic|backtrack|exponential|cheap")
_WALL_CLOCKS = frozenset({"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "time"})
_CPU_CLOCKS = frozenset({"thread_time", "thread_time_ns", "process_time", "process_time_ns"})
_OWNED_ELSEWHERE = frozenset({"test_persistent_collections.py"})
"""Files another change is converting."""


def _time_calls(tree: ast.AST) -> set[str]:
    """The ``time`` module's clocks a module reads (``time.x`` or ``from time import x``)."""
    used: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            used.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            used.update(alias.name for alias in node.names)
    return used


def _growth_tests(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and _GROWTH_NAME.search(node.name)
    ]


@functools.cache
def _modules() -> tuple[tuple[str, ast.Module], ...]:
    """The test modules that mention ``time`` at all, parsed."""
    texts = {
        path.relative_to(_TESTS).as_posix(): path.read_text()
        for path in sorted(_TESTS.rglob("*.py"))
        if path.name not in _OWNED_ELSEWHERE
    }
    return tuple((name, ast.parse(text)) for name, text in texts.items() if "time" in text)


def test_growth_checks_read_no_wall_clock() -> None:
    offenders = {
        name: sorted(_time_calls(tree) & _WALL_CLOCKS)
        for name, tree in _modules()
        if _growth_tests(tree) and _time_calls(tree) & _WALL_CLOCKS
    }
    assert offenders == {}, "measure the work with tests/_growth.py, or count it"


def test_tests_read_cpu_time_only_through_the_growth_helper() -> None:
    readers = [
        name
        for name, tree in _modules()
        if Path(name).name.startswith("test_") and _time_calls(tree) & _CPU_CLOCKS
    ]
    assert readers == [], "use tests/_growth.py (both sizes in turn, the least of each)"


def test_the_guard_sees_a_wall_clock_growth_check() -> None:
    tree = ast.parse(
        "import time\n"
        "def test_parse_is_linear():\n"
        "    start = time.perf_counter()\n"
        "    assert time.perf_counter() - start < 1\n"
    )
    assert _growth_tests(tree) == ["test_parse_is_linear"]
    assert _time_calls(tree) & _WALL_CLOCKS == {"perf_counter"}
