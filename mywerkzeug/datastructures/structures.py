import collections.abc as cabc
import typing as t

from .mixins import ImmutableDictMixin
from .mixins import ImmutableMultiDictMixin
from .mixins import UpdateDictMixin

if t.TYPE_CHECKING:
    import typing_extensions as te

K = t.TypeVar("K")
V = t.TypeVar("V")
T = t.TypeVar("T")

def iter_multi_items(
    mapping: (
        MultiDict[K, V]
        | cabc.Mapping[K, V | list[V] | tuple[V, ...] | set[V]]
        | cabc.Iterable[tuple[K, V]]
    ),
) -> cabc.Iterable[tuple[K, V]]:
    """Iterates over the items of a mapping yielding keys and values 
    without dropping any from more complex structures."""
    if isinstance(mapping, MultiDict):
        yield from mapping.items(multi=True)
    elif isinstance(mapping, cabc.Mapping):
        for key, value in mapping.items():
            if isinstance(value, (list, tuple, set)):
                for v in value:
                    yield key, v 
            else:
                yield key, value
    else:
        yield from mapping

class TypeConversionDict(dict[K, V]):
    """类似普通字典的类，但是它的`get`方法可以进行类型转换。
    class (MultiDict) 和 class (CombinedMultiDict) 是该类的子类并提供了相同的特性.
    
    .. versionadded:: 0.5
    """
    pass

class MultiDict(TypeConversionDict[K, V]):
    """:class:`MultiDict` 是一个定制字典子类，专门用于处理同一键对应多个值的情况，
    例如这种特性被封装函数使用。因为某些HTML表单元素对于单个键传递多个值，因此很有必要

    :class:`MultiDict`实现了所有标准的字典方法。内部实现中，将键的所有值保存为一个
    列表，但是标准的字典access方法只会返回key的第一个值。如果像获取其他值，必须使用
    `list`方法。参考下面：

    >>> d = MultiDict([('a', 'b'), ('a', 'c')])
    >>> d
    MultiDict([('a', 'b'), ('a', 'c')])
    >>> d['a']
    'b'
    >>> d.getlist('a')
    ['b', 'c']
    >>> 'a' in d
    True

    它行为类似于普通字典，因此所有的的字典给方法当发现一个key对应多值时只会返回第一个值。

    从Werkzeug 0.3之后，被该类抛出的`KeyError`也是:exc:`~exceptions.BadRequest`的
    HTTP异常的子类，并会渲染一个 ``400 BAD REQUEST`` 页面如果陷入了一个处理所有 
    HTTP 异常情况的通用机制中。

    :class:`MultiDict`可以由``(key, value)`` 元组，字典，:class:`MultiDict`，或
    Werkzeug 0.2 开始的一些关键字参数构造。

    :param mapping: :class:`MultiDict`的初始化值.  要么是标准dict，要么是可迭代的
                    ``(key, value)`` tuples或者None
    
    .. versionchanged:: 3.1
        实现 ``|`` and ``|=`` operators.                
    """

    def __init__(
        self,
        mapping: (
            MultiDict[K, V]
            | cabc.Mapping[K, V | list[V] | tuple[V, ...] | set[V]]
            | cabc.Iterable[tuple[K, V]]
            | None
        ) = None,
    ) -> None:
        if mapping is None:
            super().__init__()
        elif isinstance(mapping, MultiDict):
            super().__init__((k, vs[:]) for k, vs in mapping.lists()) # type: ignore[misc]
        elif isinstance(mapping, cabc.Mapping):
            tmp = {}
            for key, value in mapping.items():
                if isinstance(value, (list, tuple, set)):
                    value = list(value)

                    if not value: continue
                else:
                    value = [value]
                tmp[key] = value
            super().__init__(tmp) # type: ignore[arg-type]
        else:
            tmp = {}
            for key, value in mapping:
                tmp.setdefault(key, []).append(value)
            super().__init__(tmp) # type: ignore[arg-type]

class ImmutableDict(ImmutableDictMixin[K, V], dict[K, V]): #type: ignore[misc]
    """一个不可变的:class:`dict`."""

    pass

class ImmutableMultiDict(ImmutableMultiDictMixin[K, V], MultiDict[K, V]): # type: ignore[misc]
    """一个不可变的:class:`MultiDict`."""

    def copy(self) -> MultiDict[K, V]: # type: ignore[override]
        """返回此对象的浅层可变副本。牢记标准库的:func:`copy`方法对该类是一个no-op
        就像它对于其他不可变python对象(如 :class:`tuple`).
        """
        return MultiDict(self)

    def __copy__(self) -> te.Self:
        return self
    
class CallbackDict(UpdateDictMixin[K, V], dict[K, V]):
    """一个字典，当字典中的元素发生变化时会调用传入的方法，函数接收字典实例作为参数"""

    def __init__(
        self,
        initial: cabc.Mapping[K, V] | cabc.Iterable[tuple[K, V]] | None = None,
        on_update: cabc.Callable[[te.Self], None] | None = None,
    ) -> None:
        if initial is None:
            super().__init__()
        else:
            super().__init__(initial)
        
        self.on_update = on_update
    
    def __repr__(self) -> str:
        return f"<{type(self).__name__} {super().__repr__()}>"

class HeaderSet(cabc.MutableSet[str]):
    """与:class:`ETags`相似，实现了一个类set的结构，与:class:`Etags`不同，不区分
    大小写，并且用于vary, allow,和content-language头

    如果不使用:func:`parse_set_header`方法构建，实例化过程如下

    >>> hs = HeaderSet(['foo', 'bar', 'baz'])
    >>> hs
    HeaderSet(['foo', 'bar', 'baz'])
    """

    def __init__(
        self,
        headers: cabc.Iterable[str] | None = None,
        on_update: cabc.Callable[[te.Self], None] | None = None,
    ) -> None:
        self._headers = list(headers or ())
        self._set = {x.lower() for x in self._headers}
        self.on_update = on_update
        

    def to_header(self) -> str:
        """将header set转换为HTTP header string"""
        return ", ".join(map(http.quote_header_value, self._headers))


# circular dependencies
from .. import http # noqa: E402
