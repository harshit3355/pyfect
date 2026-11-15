"""CI's test shards (tests/_shards.py): check they ran the whole suite, and refresh the
durations they are packed by. Standard library only, so CI runs it without installing.

    python scripts/test_shards.py verify FULL_MANIFEST SHARD_MANIFEST...
        Fails unless the shards' test ids together are the full collection's, each once.

    python scripts/test_shards.py update TIMINGS_JSON...
        Writes tests/shard_durations.json from the shards' --shard-durations files (download
        a CI run's with `gh run download RUN -p 'durations-*'`), the slower Python's time
        for each file.
"""

import json
import sys
from collections import Counter
from pathlib import Path

DURATIONS = Path(__file__).resolve().parent.parent / "tests" / "shard_durations.json"


def _ids(path: Path) -> Counter[str]:
    return Counter(path.read_text(encoding="utf-8").splitlines())


def verify(full: Path, shards: list[Path]) -> list[str]:
    """The problems with ``shards`` as a split of ``full``; none means they match."""
    expected = _ids(full)
    ran: Counter[str] = Counter()
    for shard in shards:
        ran.update(_ids(shard))
    problems = [f"twice in the full collection: {test}" for test, n in expected.items() if n > 1]
    problems += [f"run {n} times: {test}" for test, n in sorted(ran.items()) if n > 1]
    problems += [f"in no shard: {test}" for test in sorted(expected.keys() - ran.keys())]
    problems += [f"not in the full collection: {test}" for test in sorted(ran.keys() - expected)]
    if not expected:
        problems.append(f"{full} lists no tests")
    return problems


def update(timings: list[Path]) -> dict[str, float]:
    slowest: dict[str, float] = {}
    for path in timings:
        recorded: dict[str, float] = json.loads(path.read_text(encoding="utf-8"))
        for file, seconds in recorded.items():
            slowest[file] = max(slowest.get(file, 0.0), seconds)
    return dict(sorted(slowest.items()))


def main(argv: list[str]) -> int:
    match argv:
        case ["verify", full, first, *rest]:
            problems = verify(Path(full), [Path(first), *map(Path, rest)])
            for problem in problems[:200]:
                print(problem, file=sys.stderr)
            if problems:
                print(f"{len(problems)} problems", file=sys.stderr)
                return 1
            print(f"{len(_ids(Path(full)))} tests, each run by exactly one of {len(rest) + 1}")
            return 0
        case ["update", first, *rest]:
            durations = update([Path(first), *map(Path, rest)])
            DURATIONS.write_text(json.dumps(durations, indent=1) + "\n", encoding="utf-8")
            print(f"{len(durations)} files, {sum(durations.values()) / 60:.1f} min")
            return 0
        case _:
            print(__doc__, file=sys.stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
