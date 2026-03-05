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

T = t.TypeVar("T")

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

    @t.overload
    def get(self, key: str) -> str | None: ...
    @t.overload
    def get(self, key: str, default: str) -> str: ...
    @t.overload
    def get(self, key: str, default: T) -> str | T: ...
    @t.overload
    def get(self, key: str, type: cabc.Callable[[str], T]) -> T | None: ...
    @t.overload
    def get(self, key: str, default: T, type: cabc.Callable[[str], T]) -> T: ...
    def get( # type: ignore[misc]
        self,
        key: str,
        default: str | T | None = None,
        type: cabc.Callable[[str], T] | None = None,
    ) -> str | T | None:
        """如果请求数据不存在返回默认值，如果`type`提供了并且可调用,应该对这个值进行转换，
        然后返回，或者无法转换，抛出一个:exc:`ValueError`. 这种情况下，function会返回
        默认值，就像这个值没有找到一样：

        >>> d = Headers(['Content-Length', '42'])
        >>> d.get('Content-Lenght', type=int)
        42

        :param key: 要寻找的key
        :param default: 如果key没有找到，应该返回的默认值，如果没有指定，返回`None`
        :param type: 在:class:`Headers`中用于转换value的可调用对象，如果callable抛出
            :exc:`ValueError`,返回默认值
        """
        try:
            rv = self._get_key(key)
        except KeyError:
            return default
        
        if type is None:
            return rv
        
        try:
            return type(rv)
        except ValueError:
            return default

    def _get_key(self, key: str) -> str:
        ikey = key.lower()

        for k, v in self._list:
            if k.lower() == ikey:
                return v
        raise BadRequestKeyError(key)

    @t.overload
    def getlist(self, key: str) -> list[str]: ...
    @t.overload
    def getlist(self, key: str, type: cabc.Callable[[str], T]) -> list[T]: ...
    def getlist(
        self, key: str, type: cabc.Callable[[str], T] | None = None
    ) -> list[str] | list[T]:
        """根据给定的key返回items的列表，如果key不在:class:`Headers`, 返回空list
        类似:meth:`get`, :meth:`getlist`接收一个`type`参数,所有的items将使用定义的
        可调用对象进行转换
        
        :param key: 需要查询的key
        :param type: 用来转换:class:`Headers`中值的可调用对象.如果callable抛出
            :exec:`ValueError`值会从list移除
        """
        ikey = key.lower()

        if type is not None:
            result = []

            for k, v in self:
                if k.lower() == ikey:
                    try:
                        result.append(type(v))
                    except ValueError:
                        continue
            
            return result
        
        return [v for k, v in self if k.lower() == ikey]

    def _del_key(self, key: str) -> None:
        key = key.lower()
        new = []

        for k, v in self._list:
            if k.lower() != key:
                new.append((k, v))

        self._list[:] = new

    def remove(self, key: str) -> None:
        """移除key
        :param key: 需要移除的key
        """
        return self._del_key(key)

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

    def setlist(self, key: str, values: cabc.Iterable[t.Any]) -> None:
        """移除存在的值并添加一个新的
        
        :param key: 需要设置的header key
        :param value: 给key设置的可迭代的value
        """
        if values:
            values_iter = iter(values)
            self.set(key, next(values_iter))

            for value in values_iter:
                self.add(key, value)
        else:
            self.remove(key)

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

    def update(
        self,
        arg: (
            Headers
            | MultiDict[str, t.Any]
            | cabc.Mapping[
                str, t.Any | list[t.Any] | tuple[t.Any, ...] | cabc.Set[t.Any]
            ]
            | cabc.Iterable[tuple[str, t.Any]]
            | None
        ) = None,
        /,
        **kwargs: t.Any | list[t.Any] | tuple[t.Any, ...] | cabc.Set[t.Any],
    ) -> None:
        """使用另一个header对象中的items替换此对象中的headers
        
        为了扩展当前keys而不是替换，使用:meth:`extend`

        如果提供，第一个参数可以是另外一个:class:`Headers`对象，一个:class:`MultiDict`
        :class:`dict` 或者可迭代对
        """
        if arg is not None:
            if isinstance(arg, (Headers, MultiDict)):
                for key in arg.keys():
                    self.setlist(key, arg.getlist(key))
            elif isinstance(arg, cabc.Mapping):
                for key, value in arg.items():
                    if isinstance(value, (list, tuple, set)):
                        self.setlist(key, value)
                    else:
                        self.set(key, value)
            else:
                for key, value in arg:
                    self.set(key, value)
        
        for key, value in kwargs.items():
            if isinstance(value, (list, tuple, set)):
                self.setlist(key, value)
            else:
                self.set(key, value)        

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

