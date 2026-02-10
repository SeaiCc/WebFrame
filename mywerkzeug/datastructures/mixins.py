


class ImmutableHeadersMixin:
    """Makes a class (Headers) immutable. We do not mark them as hashable 
    though since the only usecase for this datastructure in Werkzeug is a
    view on a mutable structure.
    
    .. versionchanged::
    3.1 - Disallow (|=) operator
    """

    pass


