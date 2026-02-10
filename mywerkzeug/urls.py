import typing as t
import re

from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

def _make_unquote_part(name: str, chars: str) -> t.Callable[[str], str]:
    """Create a function that unquotes all percent encoded characters
    except those give.
    This allows working with unquoted characters if possible while 
    not changing the meaning of a given part of URL.
    """
    choices = "|".join(f"{ord(c):02X}" for c in sorted(chars))
    pattern = re.compile(f"((?:%(?:{choices}))+)", re.I)

    def _unquote_partial(value: str) -> str:
        parts = iter(pattern.split(value))
        out = []

        for part in parts:
            out.append(unquote(part, "utf-8", "mywerkzeug.url_quote"))
            out.append(next(parts, ""))
        return "".join(out)
    
    _unquote_partial.__name__ = f"_unquote_{name}"
    return _unquote_partial

_always_unsafe = bytes((*range(0x21), 0x25, 0x7F)).decode()
_unquote_fragment = _make_unquote_part("fragment", _always_unsafe)
_unquote_path = _make_unquote_part("path", _always_unsafe + "/?#")
_unquote_query = _make_unquote_part("query", _always_unsafe + "&=+#")
_unquote_user = _make_unquote_part("user", _always_unsafe + ":@/?#")


def uri_to_iri(uri: str) -> str:
    """Convert a URI to an IRI. All valid UTF-8 characters are unquoted,
    leaving all reserved and invalid characters quoted. If the URL has
    a domain, it is decoded from Punycode.

    >>> uri_to_iri("http://xn--n3h.net/p%C3%A5th?q=%C3%A8ry%DF")
    'http://\\u2603.net/p\\xe5th?q=\\xe8ry%DF'

    :param_uri: The URI to convert.
    .. verisonchanged::
    3.0 - Passing a tuple or bytes, and the (charset) and (erros) parameters
        are removed.
    2.3 - Which characters remain quoted is specific to each part of the URL.
    0.15 - All reserved and invalid characters remain quoted. Previously,
        only some reserved characters were preserved, and invalid bytes
        were replaced instead of left quoted.
    """
    parts = urlsplit(uri)
    path = _unquote_path(parts.path)
    query = _unquote_query(parts.query)
    fragment = _unquote_fragment(parts.fragment)

    if parts.hostname:
        netloc = _decode_idna(parts.hostname)
    else:
        netloc = ""
    
    if ":" in netloc: netloc = f"[{netloc}]"
    if parts.port: netloc = f"{netloc}:{parts.port}"
    if parts.username:
        auth = _unquote_user(parts.username)
        if parts.password:
            password = _unquote_user(parts.password)
            auth = f"{auth}:{password}"
        netloc = f"{auth}@{netloc}"
    
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


def iri_to_uri(iri: str) -> str:
    """Convert an IRI to a URI. All non-ASCII and unsafe characters are
    quoted. If the URI has a domain, it is encoded to Punycode.

    >>> iri_to_uri('http://\\u2603.net/p\\xe5th?q=\\xe8ry%DF')
    'http://xn--n3h.net/p%C3%A5th?q=%C3%A8ry%DF'

    :param iri: The IRI to convert

    .. verisonchanged:: 
    3.0 - Passing a tuple or bytes, the (charset) and (errors) parameters,
        and the (safe_conversion) parameter, are removed.
    2.3 - Which characters remain unquoted is specific to each part of the URL.
    0.15 - All reserved characters remain unquoted. Previously, only some 
        reserved characters were left unquoted.
    0.9.6 - The (safe_conversion) parameter was added.
    """

    parts = urlsplit(iri)
    # safe = https://url.spec.whatwg.org/#url-path-segment-string
    # as well as percent for things that are already quoted
    path = quote(parts.path, safe="%!$&'()*+,/:;=@")
    query = quote(parts.query, safe="%!$&'()*+,/:;=?@")
    fragment = quote(parts.fragment, safe="%!#$&'()*+,/:;=?@")

    if parts.hostname:
        netloc = parts.hostname.encode("idna").decode("ascii")
    else:
        netloc = ""
    
    if ":" in netloc: netloc = f"[{netloc}]"

    if parts.port: netloc = f"{netloc}:{parts.port}"

    if parts.username:
        auth = quote(parts.username, safe="%!$&'()*+,;=")
        if parts.password:
            password = quote(parts.password, safe="%!$&'()*+,;=")
            auth = f"{auth}:{password}"
        netloc = f"{auth}@{netloc}"
    
    return urlunsplit((parts.scheme, netloc, path, query, fragment))

def _decode_idna(domain: str) -> str:
    try:
        data = domain.encode("ascii")
    except UnicodeEncodeError:
        # If the domain is not ASCII, it's decoded already.
        return domain

    try:
        # Try decoding in one shot.
        return data.decode("idna")
    except UnicodeDecodeError:
        pass

    # Decode each part separately, leaving invalid parts as punycode.
    parts = []

    for part in data.split(b"."):
        try:
            parts.append(part.decode("idna"))
        except UnicodeDecodeError:
            parts.append(part.decode("ascii"))

    return ".".join(parts)

