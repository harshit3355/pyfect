"""README.md is PyPI's long description: its links work there, and its quick look runs.

A relative link or image points nowhere on PyPI.

PyPI renders the README without the repository around it, so `assets/logo.svg`,
`examples/` or `LICENSE` are broken there. Every link and image in it is absolute:
`https://raw.githubusercontent.com/...` for images, `https://github.com/.../blob/main/...`
for files, or a pyfect.dev page. In-page anchors (`#installation`) are fine.
"""

import re
import subprocess
import sys
from pathlib import Path

README = Path(__file__).parent.parent / "README.md"

# Markdown links and images `[text](target)`, reference definitions `[id]: target`,
# and HTML `href`, `src` and `srcset` attributes.
_TARGETS = re.compile(
    r"\]\(\s*<?([^)\s>]+)"
    r"|^\s*\[[^\]]+\]:\s*<?(\S+?)>?\s*$"
    r"|\b(?:href|src|srcset)\s*=\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
_ABSOLUTE = re.compile(r"^(?:https?:|mailto:|#)")


def relative_links(text: str) -> list[str]:
    targets = (next(g for g in m.groups() if g is not None) for m in _TARGETS.finditer(text))
    # A srcset lists candidates separated by commas, each a URL and an optional size.
    urls = (url.split()[0] for target in targets for url in target.split(",") if url.strip())
    return [url for url in urls if not _ABSOLUTE.match(url)]


def test_the_readme_has_no_relative_links_or_images():
    assert relative_links(README.read_text()) == []


def test_relative_links_are_found_in_every_form():
    text = (
        '<img src="assets/logo.svg"> <a href="LICENSE">x</a>\n'
        '<source srcset="assets/dark.svg 2x, https://ok.example/a.svg">\n'
        "[Examples](examples/) ![logo](assets/a.png) [ok](https://pyfect.dev) [top](#a)\n"
        "[ref]: docs/PARITY.md\n"
    )
    assert relative_links(text) == [
        "assets/logo.svg",
        "LICENSE",
        "assets/dark.svg",
        "examples/",
        "assets/a.png",
        "docs/PARITY.md",
    ]


def test_the_quick_look_runs_and_prints_its_greeting():
    code = re.search(r"## A quick look\n\n```python\n(.*?)```", README.read_text(), re.DOTALL)
    assert code is not None
    run = subprocess.run(
        [sys.executable, "-c", code[1]], capture_output=True, text=True, timeout=60, check=False
    )
    assert (run.returncode, run.stdout, run.stderr) == (0, "Hello, Ada!\n", "")
