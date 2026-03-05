
import typing as t
from collections import abc as cabc


K = t.TypeVar("K")
V = t.TypeVar("V")
T = t.TypeVar("T")
F = t.TypeVar("F", bound=cabc.Callable[..., t.Any])


class ImmutableDictMixin(t.Generic[K, V]):
    """使一个:class:`dict`不可变。"""
    pass

class ImmutableMultiDictMixin(ImmutableDictMixin[K, V]):
    """使得一个:class:`MultiDict`不可变。"""

    pass

class ImmutableHeadersMixin:
    """Makes a class (Headers) immutable. We do not mark them as hashable 
    though since the only usecase for this datastructure in Werkzeug is a
    view on a mutable structure.
    
    .. versionchanged::
    3.1 - Disallow (|=) operator
    """
    pass

class UpdateDictMixin(dict[K, V]):
    """使字典在修改时调用`self.on_update`方法"""
    pass

