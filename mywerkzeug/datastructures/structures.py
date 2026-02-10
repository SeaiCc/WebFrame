import collections.abc as cabc
import typing as t

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
    """Works like a reqular dict but method (get) can perform type conversions.
    class (MultiDict) and class (CombinedMultiDict) are subclasses of this 
    class and provide the same feature.
    
    .. versionadded:: 0.5
    """
    pass



class MultiDict(TypeConversionDict[K, V]):
    """A :class:`MultiDict` is a dictionary subclass customized to deal with
    multiple values for the same key which is for example used by the parsing
    functions in the wrappers.  This is necessary because some HTML form
    elements pass multiple values for the same key.
    
    :class:`MultiDict` implements all standard dictionary methods.
    Internally, it saves all values for a key as a list, but the standard dict
    access methods will only return the first value for a key. If you want to
    gain access to the other values, too, you have to use the `list` methods as
    explained below.

    >>> d = MultiDict([('a', 'b'), ('a', 'c')])
    >>> d
    MultiDict([('a', 'b'), ('a', 'c')])
    >>> d['a']
    'b'
    >>> d.getlist('a')
    ['b', 'c']
    >>> 'a' in d
    True

    It behaves like a normal dict thus all dict functions will only return the
    first value when multiple values for one key are found.
    
    From Werkzeug 0.3 onwards, the `KeyError` raised by this class is also a
    subclass of the :exc:`~exceptions.BadRequest` HTTP exception and will
    render a page for a ``400 BAD REQUEST`` if caught in a catch-all for HTTP
    exceptions.

    A :class:`MultiDict` can be constructed from an iterable of
    ``(key, value)`` tuples, a dict, a :class:`MultiDict` or from Werkzeug 0.2
    onwards some keyword parameters.

    :param mapping: the initial value for the :class:`MultiDict`.  Either a
                    regular dict, an iterable of ``(key, value)`` tuples
                    or `None`.
    
    .. versionchanged:: 3.1
        Implement ``|`` and ``|=`` operators.                
    """

    pass
