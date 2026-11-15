"""Shared fixtures."""

import gc
import os
from collections.abc import Iterator

import pytest

from pyfect.schema.compiler import _registry

pytest_plugins = ["pytester", "_timeout", "_asyncio_reports", "_shards", "_skips", "_parallel"]

# pytest imports readline before this file loads, and GNU readline (Linux) exports COLUMNS and
# LINES into the C environment behind os.environ's back; children would inherit an 80-column
# terminal (``ps aux`` cuts its lines there). tests/test_session_environment.py pins this.
for _name in ("COLUMNS", "LINES"):
    if _name not in os.environ:
        os.unsetenv(_name)

_COMPILER_LEFT = (
    "a schema compiler installed (pyfect.schema.compiler: set, install, enable, or an "
    "import of pyfect.schema.jit_compiler.install), so every later test would parse through it; "
    "reset it with _registry.reset(), as the fresh_registry fixture in "
    "tests/oracle/_schema_compiler.py does, and walk modules with tests/_pyfect_modules.py"
)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Keep imported modules out of the collector's work: with them, a full run holds over five
    million objects and one collection pauses the running test for up to 2.5 s."""
    if _registry.active():
        raise pytest.UsageError(f"collecting the tests left {_COMPILER_LEFT}")
    gc.collect()
    gc.freeze()


@pytest.fixture(autouse=True)
def no_schema_compiler_left_installed() -> Iterator[None]:
    """Each Effect test file runs in its own module graph; here one process runs them all, so
    a test that installs a compiler must remove it."""
    yield
    if _registry.active():
        _registry.reset()
        pytest.fail(f"this test left {_COMPILER_LEFT}")


@pytest.fixture
def pytester(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Pytester whose inner runs keep their files' order: pytest-randomly loads in every
    session from its entry point, and the inner tests here are written as sequences."""
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p no:randomly")
    return pytester
