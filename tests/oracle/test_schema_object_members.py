"""Every name an instance inherits from ``object`` is a field only as an own attribute.

Effect 4.1.4 (#9612) reads a struct field named after an ``Object.prototype`` member only from
the input's own properties. pyfect reads an instance's attributes as its keys through one
mapping (``ObjectKeys``), which the interpreter and the compiled parsers share; this checks
every such name, interpreted and compiled, so a new reading path or a new ``object`` member
can't bring inherited attributes back as fields.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import pyfect.schema as S
from pyfect.schema.ast._objects import OBJECT_MEMBERS
from pyfect.schema.compiler import _registry
from pyfect.schema.jit_compiler import compiler as jit

from ._schema_binary import Opt, struct

__all__ = ["compiled"]


class _Plain:
    pass


class _Slotted:
    __slots__ = ("__str__",)


@pytest.fixture(params=["interpreted", "jit"])
def compiled(request: pytest.FixtureRequest) -> Iterator[None]:
    _registry.reset()
    if request.param == "jit":
        _registry.install(jit)
    yield
    _registry.reset()


@pytest.mark.usefixtures("compiled")
@pytest.mark.parametrize("name", sorted(OBJECT_MEMBERS))
def test_an_inherited_object_member_is_absent(name: str) -> None:
    schema = struct(**{name: Opt(S.Unknown)})
    assert S.decode_unknown_sync(schema)(_Plain()) == {}
    with pytest.raises(S.SchemaError, match="Missing key"):
        S.decode_unknown_sync(struct(**{name: S.Unknown}))(_Plain())


@pytest.mark.usefixtures("compiled")
@pytest.mark.parametrize("name", sorted(OBJECT_MEMBERS - {"__dict__"}))
def test_an_own_object_member_is_read(name: str) -> None:
    own = _Plain()
    vars(own)[name] = "own"
    assert S.decode_unknown_sync(struct(**{name: S.String}))(own) == {name: "own"}


@pytest.mark.usefixtures("compiled")
def test_a_slot_named_after_an_object_member_is_own() -> None:
    slotted = _Slotted()
    assert S.decode_unknown_sync(struct(__str__=Opt(S.String)))(slotted) == {}
    slotted.__str__ = "own"  # pyright: ignore[reportAttributeAccessIssue]
    assert S.decode_unknown_sync(struct(__str__=S.String))(slotted) == {"__str__": "own"}
