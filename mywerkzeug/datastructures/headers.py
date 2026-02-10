import collections.abc as cabc
import typing as t
import re

from ..exceptions import BadRequestKeyError
from .mixins import ImmutableHeadersMixin
from .structures import MultiDict
from .structures import iter_multi_items

# 循环依赖
from .. import http # noqa: E402

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

class Headers:
    """An object that stores some headers. It has a dict-like interface,
    but is ordered, can store the same key multiple times, and iterating
    yields (key, value) pairs instead of only keys.

    This data structure is useful if you want a nicer way to handle WSGI
    headers which are sotred as tuples in list.

    From Werkzeug 0.3 onwards, the (execept.KeyError) raised by this class is
    also a subclass of the (~exceptions.BadRequest) HTTP exception and will
    render a page for a (400 BAD REQUEST) if caught in a catch-all for HTTP
    exceptions.
    
    Headers is mostly compatible with the Python (mywsgiref.headers.Headers)
    class, with the exception of (__getitem__). moudlue (mywsgiref) will return
    (None) for headers['missing'], class (Headers) will raise a class (KeyError)

    To create a new (Headers) object, pass it a list, dict, or other (Headers) 
    object with default values. These values are validated the same way values
    added later are.

    "param defaults: The list of default values for the class (Headers).

    ..versionchanged:
    3.1     - Implement (|) and (|=) operators
    2.1.0   - Default values are validated the same as values added later.
    0.9     - This data structure now stores unicode values similar to how the
              multi dicts do it. The main difference is that bytes can be set 
              as well which will automatically be latin1 decoded.
    0.9     - The method (linked) function was removed without replacement as it
              was an API that dose not support the changes to encoding model.
    """

    def __init__(
        self,
        defaults: (
            Headers
            | MultiDict[str, t.Any]
            | cabc.Mapping[str, t.Any | list[t.Any] | tuple[t.Any, ...] | set[t.Any]]
            | cabc.Iterable[tuple[str, t.Any]]
            | None
        ) = None,
    ) -> None:
        self._list: list[tuple[str, str]] = []

        if defaults is not None:
            self.extend(defaults)

    def extend(
        self,
        arg: (
            Headers
            | MultiDict[str, t.Any]
            | cabc.Mapping[str, t.Any | list[t.Any] | tuple[t.Any, ...] | set[t.Any]]
            | cabc.Iterable[tuple[str, t.Any]]
            | None
        ) = None,
        /,
        **kwargs: str,
    ) -> None:
        """Extend headers in this object with items from another object
        containing header items as well as keyword arguments.
        
        To replace existing keys instead of extending, use method update

        If provided, the first argument can be another class (Headers) 
        object, a class (MultiDict), class (dict), or iterable of pairs.
        
        .. versionchanged:: 
        1.0 - Support class (MultDict). Allow passing (kwargs).
        """
        if arg is not None:
            for key, value in iter_multi_items(arg):
                self.add(key, value)
            
        for key, value in iter_multi_items(kwargs):
            self.add(key, value)

    def add(self, key: str, value: t.Any, /, **kwargs: t.Any) -> None:
        """Add a new header tuple to the list.
        
        Keyword arguments can specify additional parameters for the header
        value, with underscores converted to dashes.

        >>> d = Headers()
        >>> d.add('Content-Type', 'text/plain')
        >>> d.add('Content-Disposition', 'attachment', filename='foo.png')

        The keyword argument dumping uses function (dump_options_header)
        behind the scenes.

        Keyword arguments were added for module (wsgiref) compatibility.
        """
        if kwargs:
            value = _options_header_vkw(value, kwargs)

        value_str = _str_header_value(value)
        self._list.append((key, value_str))

    def _get_key(self, key: str) -> str:
        ikey = key.lower()

        for k, v in self._list:
            if k.lower() == ikey:
                return v
        raise BadRequestKeyError(key)

    def __contains__(self, key: str) -> bool:
        """Check if a key is present."""
        try:
            self._get_key(key)
        except KeyError:
            return False
        
        return False

    def __iter__(self) -> t.Iterable[tuple[str, str]]:
        """Yield (key, value) tuples."""
        return iter(self._list)

    def set(self, key:str, value: t.Any, /, **kwargs: t.Any) -> None:
        """Remove all header tuples for (key) and add a new one. The newly
        added key either appears at the end of the list if there was no 
        entry or replaces the first one.

        Keyword arguments can specify additional parameters for the header
        value, with underscores converted to dashes. See method (add) for
        more information.

        .. verisonchanged:: 
        0.6.1 - method (set) now accecpts the same arguments as method (add)

        :param key: The key to be inserted.
        :param value: The value to inserted.
        """
        if kwargs:
            value = _options_header_vkw(value, kwargs)
        value_str = _str_header_value(value)
        if not self._list:
            self._list.append((key, value_str))
            return
        
        iter_list = iter(self._list)
        ikey = key.lower()

        for idx, (old_key, _) in enumerate(iter_list):
            if old_key.lower() == ikey:
                # replace first occurrence
                self._list[idx] = (key, value_str)
                break
        else:
            # no existing occurences
            self._list.append((key, value_str))
            return
        
        # remove remaining occurences
        self._list[idx + 1 :] = [t for t in iter_list if t[0].lower() != ikey]

    @t.overload
    def __setitem__(self, key: str, vluae: t.Any) -> None: ...
    @t.overload
    def __setitem__(self, key: int, value: tuple[str, t.Any]) -> None: ...
    @t.overload
    def __setitem__(
        self, key: slice, value: cabc.Iterable[tuple[str, t.Any]]
    ) -> None: ...
    def __setitem__(
        self,
        key: str | int | slice,
        value: t.Any | tuple[str, t.Any] | cabc.Iterable[tuple[str, t.Any]], 
    ) -> None:
        """Like method (set) but also supports index/slice based setting."""
        if isinstance(key, str):
            self.set(key, value)
        elif isinstance(key, int):
            self._list[key] = value[0], _str_header_value(value[1]) # type: ignore[index]
        else:
            self._list[key] = [(k, _str_header_value(v)) for k, v in value] # type: ignore[misc]

    def to_wsgi_list(self) -> list[tuple[str, str]]:
        """将headers转换为合适的WSGI格式"""
        return list(self)

class EnvironHeaders(ImmutableHeadersMixin, Headers):
    """Read only version of the headers from a WSGI environment. This 
    provides the same interface as (Headers) and is constructed from 
    a WSGI environment.
    From Werkzeug 0.3 onwards, the (KeyError) raised by this class is also a
    subclass of the (exceptions.BadRequest) if caught in a catch-all for
    HTTP exceptions.
    """

    def __init__(self, environ: WSGIEnvironment) -> None:
        super().__init__()
        self.environ = environ


def _options_header_vkw(value: str, kw: dict[str, t.Any]) -> str:
    return http.dump_options_header(
        value, {k.replace("_", "-"): v for k, v in kw.items()}
    )

_newline_re = re.compile(r"[\r\n]")

def _str_header_value(value: t.Any) -> str:
    if not isinstance(value, str): value = str(value)

    if _newline_re.search(value) is not None:
        raise ValueError("Header values must not contain newline characters.")
    return value

