"""A multipart field's ``charset`` names a decoder as ``new TextDecoder(label)``
does (Effect's ``decodeField``): only the WHATWG Encoding Standard's labels,
UTF-8 for anything else. A peer's label never reaches ``codecs.lookup``, which
would let it pick any CPython codec (punycode decodes in quadratic time)."""

from __future__ import annotations

import codecs
import encodings.aliases

import pytest

from pyfect._whatwg_encoding import LABELS, decode
from pyfect.http import multipart_parser as mp


def _field(charset: str, value: bytes) -> str:
    info = mp.PartInfo(
        name="f",
        filename=None,
        content_type="text/plain",
        content_type_parameters={"charset": charset},
        content_disposition="form-data",
        content_disposition_parameters={"name": "f"},
        headers={},
    )
    return mp.decode_field(info, value)


@pytest.mark.parametrize("label", ["punycode", "idna", "rot13", "base64", "utf-7", "zlib"])
def test_a_label_outside_the_encoding_standard_decodes_as_utf8(label: str):
    assert _field(label, b"A-") == "A-"
    assert _field(label, "é".encode()) == "é"


@pytest.mark.parametrize(
    ("label", "data", "text"),
    [
        ("ISO-8859-1", b"\xe9", "é"),  # read as windows-1252
        (" latin1 ", b"\x80", "€"),
        ("windows-1251", b"\xc0", "\u0410"),
        ("shift_jis", b"\x82\xa0", "あ"),
        ("utf-16le", "hi".encode("utf-16-le"), "hi"),
        ("x-user-defined", b"a\x80", "a"),
        ("replacement", b"\xff", "�"),  # TextDecoder refuses it: UTF-8
    ],
)
def test_encoding_standard_labels(label: str, data: bytes, text: str):
    assert _field(label, data) == text


def test_no_label_picks_a_codec_outside_the_table():
    """Every CPython codec name and alias decodes through the table or as UTF-8."""
    names = set(encodings.aliases.aliases) | set(encodings.aliases.aliases.values())
    names |= {"punycode", "idna", "raw_unicode_escape", "unicode_escape", "uu", "hex", "bz2"}
    allowed = {codecs.lookup(codec).name for codec in LABELS.values()}
    for name in names:
        for spelling in (name, name.replace("_", "-")):
            data = b"\xe9A"
            got = decode(spelling, data)
            expected = {data.decode(codec, "replace") for codec in allowed}
            expected.add(decode("x-user-defined", data))
            assert got in expected, spelling
