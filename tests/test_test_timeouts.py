"""Every effect test's real-time timeout is a hang detector, never a speed limit.

``@testing.effect`` interrupts a test after a real-time timeout (5 s by default, as
``@effect/vitest`` inherits vitest's ``testTimeout``). A busy machine stretches every
test's real time: ``test_holds_durable_messages_while_entity_layers_are_still_building``
takes 1.7 s of CPU, and under pytest-xdist on a loaded runner it took over 5 s and failed
about half its runs, and 270 tests had raised their own timeout one flake at a time.
What a test checks about time it checks on the ``TestClock``, so this suite's default
(``pyfect_timeout`` in ``pyproject.toml``) is the hang limit ``_timing.HANG_SECONDS``, and
a test may only lengthen it. A short timeout is for the tests of the timeout itself.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from _timing import HANG_SECONDS

from pyfect.duration import from_input_unsafe

TESTS = Path(__file__).resolve().parent
_DECORATORS = frozenset({"effect", "live", "prop", "effect_prop", "live_prop", "layer_fixture"})

# Tests of the timeout itself, whose bodies outlast it whatever the machine's speed.
_TIMEOUT_TESTS = frozenset(
    {
        "oracle/test_vitest_prop.py:test_interrupts_property_checking_on_timeout",
        "test_testing_harness.py:test_a_test_that_finishes_after_its_timeout_fails_saying_it_finished",
    }
)


def _short_timeouts(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    name = path.relative_to(TESTS).as_posix()
    found: list[str] = []

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            function = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _DECORATORS
            and ast.unparse(node.func.value).endswith("testing")
        ):
            for keyword in node.keywords:
                value = keyword.value
                if keyword.arg != "timeout" or not isinstance(value, ast.Constant):
                    continue
                assert isinstance(value.value, str | int | float), ast.unparse(value)
                seconds = from_input_unsafe(value.value).to_seconds()
                if seconds < HANG_SECONDS and f"{name}:{function}" not in _TIMEOUT_TESTS:
                    found.append(f"{name}:{node.lineno} timeout={value.value!r}")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "")
    return found


def test_the_default_timeout_is_the_hang_limit() -> None:
    config = tomllib.loads((TESTS.parent / "pyproject.toml").read_text())
    assert float(config["tool"]["pytest"]["ini_options"]["pyfect_timeout"]) == HANG_SECONDS


def test_no_test_shortens_its_timeout() -> None:
    short = [found for path in sorted(TESTS.rglob("test_*.py")) for found in _short_timeouts(path)]
    assert short == [], "a real-time timeout is a hang detector: check timing on the TestClock"
