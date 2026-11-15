"""Split the suite into shards CI runs on separate runners: ``--shard K/N`` collects only the
test files of shard K of N.

Files are packed by their recorded duration (``tests/shard_durations.json``, written by
``scripts/test_shards.py update``), longest first onto the lightest shard, so every runner
finishes at about the same time. A file with no recorded duration goes to the shard its path
hashes to. Either way every file lands in exactly one shard. ``--shard-manifest PATH`` writes
the collected test ids, which CI's ``check`` job compares with a full collection
(``scripts/test_shards.py verify``), so no test is skipped or run twice.
"""

import json
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

DURATIONS = Path(__file__).parent / "shard_durations.json"


@dataclass(frozen=True)
class Shard:
    index: int
    """1-based."""
    count: int


def parse_shard(text: str) -> Shard:
    index, sep, count = text.partition("/")
    if not (sep and index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        raise pytest.UsageError(f"--shard takes K/N with 1 <= K <= N, not {text!r}")
    return Shard(int(index), int(count))


def assign(durations: Mapping[str, float], count: int) -> dict[str, int]:
    """Each file's 1-based shard: longest file first onto the shard with the least time."""
    loads = [0.0] * count
    shards: dict[str, int] = {}
    for path, seconds in sorted(durations.items(), key=lambda item: (-item[1], item[0])):
        lightest = min(range(count), key=lambda shard: (loads[shard], shard))
        loads[lightest] += seconds
        shards[path] = lightest + 1
    return shards


def shard_of(path: str, shards: Mapping[str, int], count: int) -> int:
    known = shards.get(path)
    return known if known is not None else zlib.crc32(path.encode()) % count + 1


def load_durations() -> dict[str, float]:
    recorded: dict[str, float] = json.loads(DURATIONS.read_text(encoding="utf-8"))
    return recorded


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Selection:
    shard: Shard
    shards: dict[str, int]
    patterns: list[str]
    root: Path

    @pytest.hookimpl
    def pytest_ignore_collect(self, collection_path: Path) -> bool | None:
        is_test_file = collection_path.suffix == ".py" and any(
            collection_path.match(pattern) for pattern in self.patterns
        )
        if not is_test_file:
            return None
        path = collection_path.relative_to(self.root).as_posix()
        return True if shard_of(path, self.shards, self.shard.count) != self.shard.index else None


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Manifest:
    path: Path

    def write(self, ids: list[str]) -> None:
        self.path.write_text("".join(f"{nodeid}\n" for nodeid in ids), encoding="utf-8")

    @pytest.hookimpl
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if session.items:  # under xdist the controller collects nothing; the workers report
            self.write([item.nodeid for item in session.items])

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: object, ids: list[str]) -> None:
        # Every worker collects the same tests (xdist checks); the first one's ids are the run's.
        if not self.path.exists():
            self.write(ids)


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Timings:
    path: Path
    seconds: dict[str, float] = field(default_factory=dict[str, float])

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        file = report.nodeid.partition("::")[0]
        self.seconds[file] = self.seconds.get(file, 0.0) + report.duration

    @pytest.hookimpl
    def pytest_sessionfinish(self) -> None:
        rounded = {file: round(seconds, 2) for file, seconds in sorted(self.seconds.items())}
        self.path.write_text(json.dumps(rounded, indent=1) + "\n", encoding="utf-8")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("shards")
    group.addoption("--shard", type=parse_shard, help="collect only shard K of N (K/N)")
    group.addoption("--shard-manifest", type=Path, help="write the collected test ids here")
    group.addoption("--shard-durations", type=Path, help="write each file's seconds here (JSON)")


def pytest_configure(config: pytest.Config) -> None:
    shard: Shard | None = config.getoption("shard")
    manifest: Path | None = config.getoption("shard_manifest")
    timings: Path | None = config.getoption("shard_durations")
    if shard is not None:
        patterns: list[str] = config.getini("python_files")
        shards = assign(load_durations(), shard.count)
        config.pluginmanager.register(_Selection(shard, shards, patterns, config.rootpath))
    # Under xdist the controller sees every test's report, so only it writes; a worker would
    # overwrite the files with its own share.
    is_worker = hasattr(config, "workerinput")
    if manifest is not None and not is_worker:
        manifest.unlink(missing_ok=True)
        config.pluginmanager.register(_Manifest(manifest))
    if timings is not None and not is_worker:
        config.pluginmanager.register(_Timings(timings))
