"""Effect's ``test/cli/Lexer.test.ts``."""

from hypothesis import assume, given
from hypothesis import strategies as st

from pyfect.cli._lexer import LongOption, ShortOption, Token, Value, format_token, lex


def test_preserves_every_equals_sign_in_a_long_options_inline_value():
    """preserves every equals sign in a long option's inline value"""
    assert lex(["--query=left=right"]).tokens == (
        LongOption("query", "--query=left=right", "left=right"),
    )


def test_lexes_negative_numbers_as_values():
    """lexes negative numbers as values"""
    assert lex(["--lon", "-3.70", "-2", "-.5", "-1e3"]).tokens == (
        LongOption("lon", "--lon"),
        Value("-3.70"),
        Value("-2"),
        Value("-.5"),
        Value("-1e3"),
    )


def test_treats_equals_value_as_a_plain_value_instead_of_a_flag_with_an_empty_name():
    """treats --=value as a plain value instead of a flag with an empty name"""
    assert lex(["--=value"]).tokens == (Value("--=value"),)


def test_gives_an_inline_value_to_the_last_flag_of_a_short_option_cluster():
    """gives an inline value to the last flag of a short option cluster"""
    assert lex(["-vn=3", "-n=4"]).tokens == (
        ShortOption("v", "-v"),
        ShortOption("n", "-n", "3"),
        ShortOption("n", "-n", "4"),
    )


def test_still_lexes_short_options_that_are_not_negative_numbers():
    """still lexes short options that are not negative numbers"""
    assert lex(["-1a", "-e"]).tokens == (
        ShortOption("1", "-1"),
        ShortOption("a", "-a"),
        ShortOption("e", "-e"),
    )


_ARG = st.one_of(
    st.sampled_from(
        ["-", "--x", "-3", "-3.5", "-a", "-ab", "-4", "-s4", "-n=3", "--name=v", "--="]
    ),
    st.text(alphabet="-ab4=.x", min_size=1, max_size=6),
)


def _meaning(token: Token) -> tuple[str, str, str | None]:
    """What the parser reads from a token: a value, or a flag's name and value."""
    match token:
        case Value(value=value):
            return ("value", value, None)
        case LongOption(name=name, value=value) | ShortOption(flag=name, value=value):
            return ("flag", name, value)


@given(st.lists(_ARG, max_size=6))
def test_formatted_tokens_lex_back_to_the_same_flags_and_values(argv: list[str]) -> None:
    """The wizard rebuilds a command line from tokens (Effect #10529); re-lexing what
    ``format_token`` writes must read the same flags and values, cluster or not."""
    tokens = lex(argv).tokens
    # A cluster such as ``-4-`` names a flag ``-``, which no command can declare.
    assume(not any(isinstance(t, ShortOption) and t.flag == "-" for t in tokens))
    again = lex([format_token(token) for token in tokens]).tokens
    assert [_meaning(t) for t in again] == [_meaning(t) for t in tokens]
