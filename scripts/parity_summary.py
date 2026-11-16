"""The one parity number the README, the docs home and PARITY.md state.

It is computed from the weighted table in docs/PARITY.md §1: the overall figure is the
weighted average of every row, the runtime core the same without the Platform row. Each page
states it as ``about N% of Effect v4 (about M% of the runtime core)``, and the table's
**Weighted total** row carries the same sum.

    python scripts/parity_summary.py           # print the numbers
    python scripts/parity_summary.py --check   # fail if a page disagrees
    python scripts/parity_summary.py --write   # rewrite the pages from the table
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARITY = ROOT / "docs" / "PARITY.md"
PAGES = (PARITY, ROOT / "README.md", ROOT / "website" / "content" / "docs" / "index.mdx")
PLATFORM_ROW = "Platform and libraries"

_PHRASE = re.compile(r"about \d+% of Effect v4 \(about \d+% of the runtime core\)")
_ROW = re.compile(r"^\| ([^|*][^|]*?) \| (\d+)%[^|]* \| (\d+) \|", re.MULTILINE)
_TOTAL = re.compile(r"\| \*\*Weighted total\*\* \| \*\*≈\d+%\*\* \([\d,]+ / 100,")


@dataclass(frozen=True)
class Parity:
    points: int
    weight: int
    core_points: int
    core_weight: int

    @property
    def overall(self) -> int:
        return _percent(self.points, self.weight)

    @property
    def core(self) -> int:
        return _percent(self.core_points, self.core_weight)

    @property
    def phrase(self) -> str:
        return f"about {self.overall}% of Effect v4 (about {self.core}% of the runtime core)"

    @property
    def total_cell(self) -> str:
        return f"| **Weighted total** | **≈{self.overall}%** ({self.points:,} / {self.weight},"


def _percent(points: int, weight: int) -> int:
    # Half up, so 94.5 reads 95 (Python's round() would give 94).
    return (2 * points + weight) // (2 * weight)


def compute(text: str) -> Parity:
    table = text[text.index("| Area | Coverage | Weight |") : text.index("| **Weighted total** |")]
    rows = [(area, int(pct), int(w)) for area, pct, w in _ROW.findall(table)]
    if not rows:
        raise ValueError("docs/PARITY.md: no rows in the parity table")
    points = sum(p * w for _, p, w in rows)
    weight = sum(w for _, _, w in rows)
    platform = [(p, w) for area, p, w in rows if area.startswith(PLATFORM_ROW)]
    if len(platform) != 1:
        raise ValueError(f"docs/PARITY.md: expected one {PLATFORM_ROW!r} row")
    (pp, pw) = platform[0]
    return Parity(points, weight, points - pp * pw, weight - pw)


def problems(parity: Parity) -> list[str]:
    found: list[str] = []
    for page in PAGES:
        text = page.read_text()
        stated = _PHRASE.findall(text)
        if len(stated) != 1:
            found.append(f"{page.relative_to(ROOT)}: states the parity {len(stated)} times, want 1")
        elif stated[0] != parity.phrase:
            found.append(
                f"{page.relative_to(ROOT)}: says {stated[0]!r}, the table gives {parity.phrase!r}"
            )
    if parity.total_cell not in PARITY.read_text():
        found.append(f"docs/PARITY.md: the Weighted total row should start {parity.total_cell!r}")
    return found


def write(parity: Parity) -> None:
    for page in PAGES:
        text = _PHRASE.sub(parity.phrase, page.read_text())
        if page == PARITY:
            text = _TOTAL.sub(parity.total_cell, text)
        page.write_text(text)


def main(argv: list[str]) -> int:
    parity = compute(PARITY.read_text())
    if "--write" in argv:
        write(parity)
    if "--check" in argv or "--write" in argv:
        found = problems(parity)
        for line in found:
            print(line, file=sys.stderr)
        if found:
            print("run: python scripts/parity_summary.py --write", file=sys.stderr)
        return 1 if found else 0
    print(parity.phrase)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
