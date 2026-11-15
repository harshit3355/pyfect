"""Text decoding by a peer's encoding label, as ``new TextDecoder(label)`` reads it.

Only the WHATWG Encoding Standard's labels name a decoder; anything else, and
``replacement`` (which ``TextDecoder`` refuses), decodes as UTF-8. A label from
the wire must never reach ``codecs.lookup``: that would let a peer pick any
CPython codec, some of them costly (``punycode`` decodes in quadratic time).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

_ENCODINGS: dict[str, tuple[str, ...]] = {
    "utf-8": (
        "unicode-1-1-utf-8", "unicode11utf8", "unicode20utf8", "utf-8", "utf8", "x-unicode20utf8",
    ),
    "cp866": ("866", "cp866", "csibm866", "ibm866"),
    "iso8859_2": (
        "csisolatin2", "iso-8859-2", "iso-ir-101", "iso8859-2", "iso88592", "iso_8859-2",
        "iso_8859-2:1987", "l2", "latin2",
    ),
    "iso8859_3": (
        "csisolatin3", "iso-8859-3", "iso-ir-109", "iso8859-3", "iso88593", "iso_8859-3",
        "iso_8859-3:1988", "l3", "latin3",
    ),
    "iso8859_4": (
        "csisolatin4", "iso-8859-4", "iso-ir-110", "iso8859-4", "iso88594", "iso_8859-4",
        "iso_8859-4:1988", "l4", "latin4",
    ),
    "iso8859_5": (
        "csisolatincyrillic", "cyrillic", "iso-8859-5", "iso-ir-144", "iso8859-5", "iso88595",
        "iso_8859-5", "iso_8859-5:1988",
    ),
    "iso8859_6": (
        "arabic", "asmo-708", "csiso88596e", "csiso88596i", "csisolatinarabic", "ecma-114",
        "iso-8859-6", "iso-8859-6-e", "iso-8859-6-i", "iso-ir-127", "iso8859-6", "iso88596",
        "iso_8859-6", "iso_8859-6:1987",
    ),
    "iso8859_7": (
        "csisolatingreek", "ecma-118", "elot_928", "greek", "greek8", "iso-8859-7", "iso-ir-126",
        "iso8859-7", "iso88597", "iso_8859-7", "iso_8859-7:1987", "sun_eu_greek",
    ),
    "iso8859_8": (
        "csiso88598e", "csisolatinhebrew", "hebrew", "iso-8859-8", "iso-8859-8-e", "iso-ir-138",
        "iso8859-8", "iso88598", "iso_8859-8", "iso_8859-8:1988", "visual",
        # ISO-8859-8-I decodes the same bytes.
        "csiso88598i", "iso-8859-8-i", "logical",
    ),
    "iso8859_10": (
        "csisolatin6", "iso-8859-10", "iso-ir-157", "iso8859-10", "iso885910", "l6", "latin6",
    ),
    "iso8859_13": ("iso-8859-13", "iso8859-13", "iso885913"),
    "iso8859_14": ("iso-8859-14", "iso8859-14", "iso885914"),
    "iso8859_15": (
        "csisolatin9", "iso-8859-15", "iso8859-15", "iso885915", "iso_8859-15", "l9",
    ),
    "iso8859_16": ("iso-8859-16",),
    "koi8_r": ("cskoi8r", "koi", "koi8", "koi8-r", "koi8_r"),
    "koi8_u": ("koi8-ru", "koi8-u"),
    "mac_roman": ("csmacintosh", "mac", "macintosh", "x-mac-roman"),
    "cp874": ("dos-874", "iso-8859-11", "iso8859-11", "iso885911", "tis-620", "windows-874"),
    "cp1250": ("cp1250", "windows-1250", "x-cp1250"),
    "cp1251": ("cp1251", "windows-1251", "x-cp1251"),
    "cp1252": (
        "ansi_x3.4-1968", "ascii", "cp1252", "cp819", "csisolatin1", "ibm819", "iso-8859-1",
        "iso-ir-100", "iso8859-1", "iso88591", "iso_8859-1", "iso_8859-1:1987", "l1", "latin1",
        "us-ascii", "windows-1252", "x-cp1252",
        # Not in the standard's table, but pyfect has always read it as windows-1252.
        "latin-1",
    ),
    "cp1253": ("cp1253", "windows-1253", "x-cp1253"),
    "cp1254": (
        "cp1254", "csisolatin5", "iso-8859-9", "iso-ir-148", "iso8859-9", "iso88599",
        "iso_8859-9", "iso_8859-9:1989", "l5", "latin5", "windows-1254", "x-cp1254",
    ),
    "cp1255": ("cp1255", "windows-1255", "x-cp1255"),
    "cp1256": ("cp1256", "windows-1256", "x-cp1256"),
    "cp1257": ("cp1257", "windows-1257", "x-cp1257"),
    "cp1258": ("cp1258", "windows-1258", "x-cp1258"),
    "mac_cyrillic": ("x-mac-cyrillic", "x-mac-ukrainian"),
    "gbk": (
        "chinese", "csgb2312", "csiso58gb231280", "gb2312", "gb_2312", "gb_2312-80", "gbk",
        "iso-ir-58", "x-gbk",
    ),
    "gb18030": ("gb18030",),
    "big5hkscs": ("big5", "big5-hkscs", "cn-big5", "csbig5", "x-x-big5"),
    "euc_jp": ("cseucpkdfmtjapanese", "euc-jp", "x-euc-jp"),
    "iso2022_jp": ("csiso2022jp", "iso-2022-jp"),
    "cp932": (
        "csshiftjis", "ms932", "ms_kanji", "shift-jis", "shift_jis", "sjis", "windows-31j",
        "x-sjis",
    ),
    "cp949": (
        "cseuckr", "csksc56011987", "euc-kr", "iso-ir-149", "korean", "ks_c_5601-1987",
        "ks_c_5601-1989", "ksc5601", "ksc_5601", "windows-949",
    ),
    "utf_16_be": ("unicodefffe", "utf-16be"),
    "utf_16_le": (
        "csunicode", "iso-10646-ucs-2", "ucs-2", "unicode", "unicodefeff", "utf-16", "utf-16le",
    ),
}  # fmt: skip

LABELS: Mapping[str, str] = MappingProxyType(
    {label: codec for codec, labels in _ENCODINGS.items() for label in labels}
)
"""Each Encoding Standard label to the CPython codec that decodes it."""

_X_USER_DEFINED = {byte: 0xF780 + byte - 0x80 for byte in range(0x80, 0x100)}


def decode(label: str, data: bytes) -> str:
    """``new TextDecoder(label).decode(data)``, or UTF-8 for a label it refuses;
    bad bytes become U+FFFD."""
    name = label.strip(" \t\n\f\r").lower()
    if name == "x-user-defined":
        return data.decode("latin-1").translate(_X_USER_DEFINED)
    return data.decode(LABELS.get(name, "utf-8"), "replace")
