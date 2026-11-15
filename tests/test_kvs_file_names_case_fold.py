"""The file-system ``KeyValueStore`` gives keys that differ only in ASCII
letter case, or by a trailing ``.``, files whose names differ however the
file system folds case (macOS and Windows do) or trims a trailing ``.``
(Windows): ``user:Alice`` and ``user:alice`` were one file there."""

import itertools
from pathlib import Path

import pyfect as fx
from pyfect import file_system, path
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence.key_value_store._layers import (
    _decode_file_key,  # pyright: ignore[reportPrivateUsage]
    _file_name,  # pyright: ignore[reportPrivateUsage]
)

_PLATFORM = fx.layer.merge(file_system.layer, path.layer)


def _folded(name: str) -> str:
    return name.casefold().rstrip(".")


def test_file_names_stay_apart_when_case_is_folded_and_round_trip() -> None:
    alphabet = ["a", "A", "z", "Z", ".", "%", "é", "É", "4", "1", ":"]
    keys = [
        "".join(chars)
        for size in range(1, 4)
        for chars in itertools.product(alphabet, repeat=size)
        if "".join(chars) not in (".", "..")
    ]
    names = {key: _file_name(key) for key in keys}
    assert all(name is not None for name in names.values())
    folded = {_folded(name) for name in names.values() if name is not None}
    assert len(folded) == len(keys)
    assert all(_decode_file_key(name) == key for key, name in names.items() if name is not None)


def test_lower_case_keys_keep_effects_file_names() -> None:
    assert _file_name("user:alice") == "user%3Aalice"
    assert _file_name("a b") == "a%20b"


def test_keys_differing_in_case_are_separate_entries(tmp_path: Path) -> None:
    def body():
        store = yield from kvs.KeyValueStore()
        yield from store.set("user:Alice", "alice's secret")
        yield from store.set("user:alice.", "dot")
        return (
            (yield from store.get("user:alice")),
            (yield from store.get("user:alice.")),
            sorted((yield from store.keys)),
        )

    layer = kvs.layer_file_system(str(tmp_path / "kv")).pipe(fx.provide(_PLATFORM))
    assert fx.run_blocking(fx.gen(body).pipe(fx.provide(layer)).or_die()) == (
        None,
        "dot",
        ["user:Alice", "user:alice."],
    )
