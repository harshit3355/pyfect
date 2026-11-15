"""(pyfect) Text from outside reaches the terminal with its control characters escaped (#22).

A file name holding ESC or C1 sequences, listed by ``prompt.file``, could clear the screen,
rewrite the listing or the target path the user confirms, or set the window title. Names,
the target line and the submitted path go through ``_terminal_text.escape_control``.
"""

from __future__ import annotations

import io
import os
import tempfile

import pyfect as fx
from pyfect import platform, terminal
from pyfect.cli import prompt
from pyfect.cli._terminal_text import escape_control

HOSTILE = "a\x1b]0;title\x07\x1b[2J\x9b2Jb\nc"


def _written(keys: bytes) -> str:
    with tempfile.TemporaryDirectory() as directory:
        for name in (HOSTILE, "ok.txt"):
            with open(os.path.join(directory, name), "w"):
                pass
        read_end, write_end = os.pipe()
        os.write(write_end, keys)
        os.close(write_end)
        output = io.StringIO()
        try:
            program = (
                prompt.run(prompt.file(starting_path=directory))
                .pipe(fx.provide_service(fx.Terminal, terminal.live(input=read_end, output=output)))
                .pipe(fx.provide(platform.layer))
            )
            fx.run_blocking_exit(program)
        finally:
            os.close(read_end)
        return output.getvalue()


def test_file_prompt_escapes_listed_names_and_the_submitted_path() -> None:
    # Down past "..": the hostile name sorts before ok.txt; Enter submits it.
    written = _written(b"\x1b[B\r")
    assert "\x1b]0;" not in written and "\x1b[2J" not in written and "\x9b" not in written
    assert "\\x1b]0;title\\x07\\x1b[2J\\x9b2Jb\\x0ac" in written


def test_escape_control_keeps_only_what_it_is_told() -> None:
    assert escape_control("a\tb\x1b\x7f\x85é") == "a\\x09b\\x1b\\x7f\\x85é"
    assert escape_control("a\tb\n", keep="\t\n") == "a\tb\n"
