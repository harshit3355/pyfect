"""Base64 with the standard alphabet and padding (Effect's
``encoding/Base64``). ``encode`` takes bytes or text (encoded as UTF-8);
``decode`` ignores CR and LF and returns a ``Result``::

    base64.encode("hello")          # "aGVsbG8="
    base64.decode("aGVsbG8=")       # Ok(b"hello")
    base64.decode_string("8J+Riw==")  # Ok("👋")

``encode_unpadded`` leaves the ``=`` padding out, and ``decode_lenient`` reads
either alphabet, padded or not (protobuf's JSON ``bytes``, Connect)::

    base64.encode_unpadded("hello")  # "aGVsbG8"
    base64.decode_lenient("-_8")     # Ok(b"\xfb\xff")
"""

from __future__ import annotations

from pyfect._binary_codecs import Binary, EncodingError, decoded_text
from pyfect._binary_codecs import base64_decode as decode
from pyfect._binary_codecs import base64_decode_lenient as decode_lenient
from pyfect._binary_codecs import base64_encode as encode
from pyfect._binary_codecs import base64_encode_unpadded as encode_unpadded
from pyfect.result import Result


def decode_string(text: str) -> Result[str, EncodingError]:
    """``decode``, then the bytes as UTF-8 (bad bytes replaced, a leading U+FEFF kept)."""
    return decoded_text(decode(text))


__all__ = [
    "Binary",
    "decode",
    "decode_lenient",
    "decode_string",
    "encode",
    "encode_unpadded",
]
