"""``positions=True`` start-element positions are the ones an ``XmlError`` at the
tag's ``<`` reports, and leaving them off keeps ``StartElement`` as it was."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import xml
from pyfect.encoding.xml import StartElement

DOCUMENT = "﻿<?xml version='1.0'?>\r\n<a>\r\r<b/>😀<c x='\r\n'>\n\r\n  <d/></c>\t<e/></a>"


def _decode(document: str, **options: Any) -> fx.Effect[list[xml.Event], xml.XmlError]:
    return stream.make(document).pipe_through_channel(xml.decode_string(**options)).run_collect()


@testing.effect
def test_positions_match_errors_at_each_start_tag() -> Any:
    events = yield from _decode(DOCUMENT, positions=True)
    starts = [event for event in events if isinstance(event, StartElement)]
    offsets = [i for i, char in enumerate(DOCUMENT) if char == "<" and DOCUMENT[i + 1] not in "/?"]
    assert len(starts) == len(offsets) == 5
    for start, offset in zip(starts, offsets, strict=True):
        # An invalid character at the "<" fails there
        error = yield from _decode(DOCUMENT[:offset] + "\x01" + DOCUMENT[offset:]).flip()
        assert (start.line, start.column) == (error.line, error.column)


@testing.effect
def test_positions_are_off_by_default() -> Any:
    events = yield from _decode("<a/>")
    assert events[0] == StartElement("a")
    assert repr(events[0]) == "StartElement(name='a', attributes={})"
    assert repr(StartElement("a", {}, 1, 2)) == (
        "StartElement(name='a', attributes={}, line=1, column=2)"
    )
    assert StartElement("a", {}, 1, 1) != StartElement("a")
