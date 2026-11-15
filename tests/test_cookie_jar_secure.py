"""(pyfect) A plain-http response cannot set or replace a ``Secure`` cookie (RFC 6265bis 5.7,
strict secure cookies, and the ``__Secure-`` / ``__Host-`` prefixes), as browsers refuse it:
otherwise whoever answers one plain-http request chooses the cookie sent over https. Effect's
``Cookies.mergeIntoArray`` takes them; pyfect's jar is stricter."""

from __future__ import annotations

from pyfect.http import cookies

NOW = 0.0


def _merge(jar: tuple[cookies.Cookie, ...], url: str, header: str) -> tuple[cookies.Cookie, ...]:
    return cookies.merge_into_array(jar, url, cookies.from_set_cookie(header), NOW)


def _sent(jar: tuple[cookies.Cookie, ...], url: str) -> str | None:
    return cookies.to_request_cookie_header(jar, url, NOW)


def test_an_http_response_does_not_replace_a_secure_cookie():
    jar = _merge((), "https://example.com/", "sid=good; Secure; Path=/")
    jar = _merge(jar, "http://example.com/", "sid=evil; Path=/")
    assert _sent(jar, "https://example.com/") == "sid=good"


def test_an_http_response_does_not_shadow_a_secure_cookie_on_a_longer_path():
    jar = _merge((), "https://example.com/", "sid=good; Secure; Path=/")
    jar = _merge(jar, "http://example.com/app/", "sid=evil; Path=/app")
    assert _sent(jar, "https://example.com/app/x") == "sid=good"


def test_an_http_response_does_not_remove_a_secure_cookie():
    jar = _merge((), "https://example.com/", "sid=good; Secure; Path=/")
    jar = _merge(jar, "http://example.com/", "sid=; Path=/; Max-Age=0")
    assert _sent(jar, "https://example.com/") == "sid=good"


def test_an_http_response_cannot_set_a_secure_or_prefixed_cookie():
    for header in ("a=1; Secure", "__Secure-a=1", "__Host-a=1; Path=/"):
        assert _merge((), "http://example.com/", header) == (), header


def test_https_and_other_names_are_unchanged():
    jar = _merge((), "https://example.com/", "sid=good; Secure; Path=/")
    jar = _merge(jar, "https://example.com/", "sid=new; Secure; Path=/")
    jar = _merge(jar, "http://example.com/", "theme=dark; Path=/")
    assert _sent(jar, "https://example.com/") == "sid=new; theme=dark"
