"""The README, the docs home and PARITY.md state the same parity number, computed from the
weighted table in docs/PARITY.md (``scripts/parity_summary.py``). They drifted apart once
(the docs home said 64% while the README said 95%)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_page_states_the_parity_the_table_gives() -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "parity_summary.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr


def test_the_parity_summary_is_the_first_paragraph_of_parity_md() -> None:
    lines = (ROOT / "docs" / "PARITY.md").read_text().splitlines()
    first = next(line for line in lines[1:] if line.strip())
    assert first.startswith("pyfect covers about "), first
