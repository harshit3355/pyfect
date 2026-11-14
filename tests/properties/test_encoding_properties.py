"""Round trips of ``pyfect.encoding``'s binary-to-text modules over generated input.

Every ``decode_string`` gives back the text its module's ``encode`` was given, a leading U+FEFF
included (Effect decodes with ``TextDecoder("utf-8", { ignoreBOM: true })``), and
``base64.decode_lenient`` reads every form the Base64 encoders write.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyfect.encoding import base64, base64_url, hex
from pyfect.encoding.encoding_error import EncodingError
from pyfect.result import Ok, Result

# Well-formed text: a lone surrogate has no UTF-8 form, so it can't come back.
_TEXT = st.text(st.characters(exclude_categories=["Cs"])).map(lambda text: "\ufeff" + text) | (
    st.text(st.characters(exclude_categories=["Cs"]))
)

_STRING_CODECS: dict[
    str, tuple[Callable[[str], str], Callable[[str], Result[str, EncodingError]]]
] = {
    "base64": (base64.encode, base64.decode_string),
    "base64_url": (base64_url.encode, base64_url.decode_string),
    "base64_url padded": (base64_url.encode_padded, base64_url.decode_string),
    "hex": (hex.encode, hex.decode_string),
}


@pytest.mark.parametrize("name", list(_STRING_CODECS))
@given(text=_TEXT)
def test_decode_string_gives_back_the_encoded_text(name: str, text: str) -> None:
    encode, decode_string = _STRING_CODECS[name]
    assert decode_string(encode(text)) == Ok(text)


_BASE64_FORMS: list[Callable[[bytes], str]] = [
    base64.encode,
    base64.encode_unpadded,
    base64_url.encode,
    base64_url.encode_padded,
]


@given(data=st.binary())
def test_decode_lenient_reads_every_base64_form(data: bytes) -> None:
    for encode in _BASE64_FORMS:
        assert base64.decode_lenient(encode(data)) == Ok(data)
