"""``_safe_decode_uri`` builds the escaped path in one pass (Effect #10619). It must agree
with the plain rewrite it replaced, which copied the whole path for every ``%25``."""

# pyright: reportPrivateUsage=false

from hypothesis import given
from hypothesis import strategies as st

from pyfect._js import decode_uri
from pyfect.http.find_my_way._router import _component_char, _safe_decode_uri


def _reference(path: str) -> tuple[str, str, bool]:
    should_decode = should_decode_param = False
    query = ""
    i = 1
    while i < len(path):
        char = path[i]
        if char == "%":
            if _component_char(path[i + 1 : i + 3]) is None:
                should_decode = True
            else:
                should_decode_param = True
                if path[i + 1 : i + 3] == "25":
                    should_decode = True
                    path = path[: i + 1] + "25" + path[i + 1 :]
                    i += 2
                i += 2
        elif char in "?;#":
            query = path[i + 1 :]
            path = path[:i]
            break
        i += 1
    return (decode_uri(path) if should_decode else path), query, should_decode_param


_PIECE = st.sampled_from(
    ["%25", "%2F", "%2f", "%C3%A9", "%20", "%zz", "%", "%2", "a", "/", "?", "#", ";", "="]
)


def _outcome(path: str) -> object:
    try:
        return _safe_decode_uri(path)
    except Exception as error:
        return type(error)


def _reference_outcome(path: str) -> object:
    try:
        return _reference(path)
    except Exception as error:
        return type(error)


@given(st.lists(_PIECE, max_size=12).map(lambda pieces: "/" + "".join(pieces)))
def test_safe_decode_uri_agrees_with_the_plain_rewrite(path: str) -> None:
    assert _outcome(path) == _reference_outcome(path)
