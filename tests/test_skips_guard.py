"""CI fails a run in which a test skipped for a reason tests/_skips.py does not allow."""

from pathlib import Path

import _skips
import pytest

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _plugin_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(_skips.__file__).parent))


_FILE = """
import pytest

def test_needs_a_server():
    pytest.skip("no local PostgreSQL: initdb / pg_ctl not found")

def test_runs():
    pass
"""


def test_an_unexplained_skip_fails_the_run_in_ci(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(_skips.ENV, "1")
    pytester.makepyfile(_FILE)
    result = pytester.runpytest_subprocess("-p", "_skips")
    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*test_needs_a_server: no local PostgreSQL*"])


def test_outside_ci_a_skip_is_only_reported(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(_skips.ENV, raising=False)
    pytester.makepyfile(_FILE)
    result = pytester.runpytest_subprocess("-p", "_skips")
    assert result.ret == pytest.ExitCode.OK


def test_an_allowed_skip_passes_in_ci(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_skips.ENV, "1")
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize("dialect", ["sqlite"])
        def test_helper(dialect):
            pytest.skip(f"{dialect} has no update_values helper")
        """
    )
    result = pytester.runpytest_subprocess("-p", "_skips")
    result.assert_outcomes(skipped=1)
    assert result.ret == pytest.ExitCode.OK


@pytest.mark.parametrize(
    "reason",
    [
        "no local PostgreSQL: initdb / pg_ctl not found",
        "no local Redis: redis-server not found",
        "needs Node 24.22.1 (found 24.22.2)",
        "no free-threaded CPython 3.14t (uv python install 3.14t)",
        "no Docker, or no SQL Server image",
    ],
)
def test_the_skips_ci_hid_are_not_allowed(reason: str):
    assert _skips.allowed(reason) is None
