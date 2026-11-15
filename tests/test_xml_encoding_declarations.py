"""Every encoding a byte document can declare, with and without a UTF-8 byte
order mark: the bytes were read as ASCII, so a declaration of a wider encoding,
or of a single-byte one after the BOM, contradicts them (``Syntax``); UTF-8 and
US-ASCII are decoded; anything else is ``Unsupported``."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import xml

BOM = "﻿"

_WIDE = [
    *(f"utf-{bits}{order}" for bits in (16, 32) for order in ("", "be", "le")),
    *(f"{prefix}ucs-{size}" for prefix in ("", "iso-10646-") for size in (2, 4)),
]
_SINGLE_BYTE = ["us-ascii", "iso-8859-1"]
_OTHER = ["utf8", "utf-7", "utf-16x", "ucs-8", "windows-1252", "shift_jis", "unknown"]

# Declared encoding -> (result without a BOM, result after a UTF-8 BOM)
_EXPECTED: dict[str, tuple[str, str]] = {
    **dict.fromkeys(_WIDE, ("Syntax", "Syntax")),
    "utf-8": ("ok", "ok"),
    "us-ascii": ("ok", "Syntax"),
    "iso-8859-1": ("Unsupported", "Syntax"),
    **dict.fromkeys(_OTHER, ("Unsupported", "Unsupported")),
}


def _outcome(document: str) -> fx.Effect[object]:
    def kind(error: xml.XmlError) -> tuple[str, int | None, int | None]:
        return (error.kind, error.line, error.column)

    return (
        stream.make(document.encode())
        .pipe_through_channel(xml.decode())
        .run_drain()
        .map(lambda _: "ok")
        .catch_all(lambda error: fx.succeed(kind(error)))
    )


def test_the_table_covers_every_family() -> None:
    assert set(_EXPECTED) == {*_WIDE, *_SINGLE_BYTE, "utf-8", *_OTHER}


@pytest.mark.parametrize("bom", [False, True], ids=["no-bom", "bom"])
@pytest.mark.parametrize("encoding", sorted(_EXPECTED))
@testing.effect
def test_declared_encoding_against_the_bytes(encoding: str, bom: bool) -> Any:
    expected = _EXPECTED[encoding][bom]
    for spelling in (encoding, encoding.upper()):
        prefix = BOM if bom else ""
        outcome: object = yield from _outcome(
            prefix + f'<?xml version="1.0" encoding="{spelling}"?><a/>'
        )
        assert outcome == (expected if expected == "ok" else (expected, 1, 1))
