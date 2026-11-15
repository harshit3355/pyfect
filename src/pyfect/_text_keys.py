"""Text that names a tenant's records, as bytes.

A Python ``str`` may hold surrogate code points, which have no UTF-8.
``text_encode`` (JavaScript's ``TextEncoder``) writes each as U+FFFD, so
two different texts can share its bytes, and a key hashed from them would
join two tenants' records. Such keys hash ``key_bytes``, and text from
outside is checked with ``is_well_formed`` where it arrives.
"""

from __future__ import annotations

import re

_SURROGATE = re.compile("[\ud800-\udfff]")


def is_well_formed(text: str) -> bool:
    """Whether ``text`` holds no surrogate code point, so it has UTF-8 of its
    own (a JSON ``"\\ud800"`` decodes to one that does not)."""
    return _SURROGATE.search(text) is None


def key_bytes(text: str) -> bytes:
    """``text`` as UTF-8, with each surrogate code point kept as its own
    three bytes: distinct texts give distinct bytes. Well-formed text gives
    its UTF-8, the bytes ``text_encode`` gives, so persisted keys stay."""
    return text.encode("utf-8", "surrogatepass")


__all__ = ["is_well_formed", "key_bytes"]
