
import typing as t
from contextvars import ContextVar
from functools import partial
from operator import attrgetter

T = t.TypeVar("T")

class Local:
    pass

class LocalStack(t.Generic[T]):
    pass

class _ProxyLookup:
    """用于处理:class:`LocalProxy`中代理属性的描述
    
    :param f: 内置函数的this属性是通过以下方式访问的，不再去查找特殊方法，而是
        直接在对象上重新执行函数调用操作
    :param fallback: 如果proxy没有被绑定，返回这个方法，而不是抛出:exec:`RuntimeError`
    :param is_attr: 这个代理的名称是一个属性，不是一个方法，立即调用fallback以获取值
    :param class_value: 当从``LocalProxy``类直接获取时返回的值，用于``__doc__`` 
        生成文档的功能仍然有效
    """

    __slots__ = ("bind_f", "fallback", "is_attr", "class_value", "name")

    def __init__(
        self,
        f: t.Callable[..., t.Any] | None = None,
        fallback: t.Callable[[LocalProxy[t.Any]], t.Any] | None = None,
        class_value: t.Any | None = None,
        is_attr: bool = False,
    ) -> None:
        bind_f: t.Callable[[LocalProxy[t.Any], t.Any], t.Callable[..., t.Any]] | None

        if hasattr(f, "__get__"):
            # Python方法，可以被转换为一个绑定方法

            def bind_f(
                instance: LocalProxy[t.Any], obj: t.Any
            ) -> t.Callable[..., t.Any]:
                return f.__get__(obj, type(obj)) # type: ignore
        
        elif f is not None:
            # C函数，使用partial来绑定第一个参数

            def bind_f(
                instance: LocalProxy[t.Any], obj: t.Any
            ) -> t.Callable[..., t.Any]:
                return partial(f, obj)
            
        else:
            # 使用 getattr，产出一个绑定方法
            bind_f = None
        
        self.bind_f = bind_f
        self.fallback = fallback
        self.class_value = class_value
        self.is_attr = is_attr

    def __get__(self, instance: LocalProxy[t.Any], owner: type | None = None) -> t.Any:
        if instance is None:
            if self.class_value is not None:
                return self.class_value
            
            return self
        
        try:
            obj = instance._get_current_object()
        except RuntimeError:
            if self.fallback is None:
                raise

            fallback = self.fallback.__get__(instance, owner)

            if self.is_attr:
                # __class__ 和 __doc__是属性，不是方法，调用fallback获取值
                return fallback()

            return fallback
        
        if self.bind_f is not None:
            return self.bind_f(instance, obj)
        
        return getattr(obj, self.name)

    def __call__(
        self, instance: LocalProxy[t.Any], *args: t.Any, **kwargs: t.Any
    ) -> t.Any:
        """支持从类中调用未绑定的方法，例如，在``copy.copy``函数中，执行的是
        ``type(x).__copy__(x)``. ``type(x)``无法被代理，因此返回代理类型和装饰器
        """
        return self.__get__(instance, type(instance))(*args, **kwargs)

def _identity(o: T) -> T:
    return o

class LocalProxy(t.Generic[T]):
    """一个绑定到context-local对象的对象的proxy,所有proxy上的操作都会被转发到绑定对象
    如果对象被绑定，抛出``RuntimeError``

    :param local: 提供被代理对象的context-local对象
    :param name: 从被代理对象代理这个属性
    :param unbound_message: 如果context-local对象被绑定显示的信息

    代理一个:class:`~contextvars.ContextVar`使其更易访问。传递一个name来代理这个属性

    .. code-block:: python

        _request_var = ContextVar("request")
        request = LocalProxy(_request_var)
        session = LocalProxy(_session_var, "session")
    
    通过调用带有属性名的local来代理一个:class:`Local`命名空间的属性:

    .. code-block:: python

        data = Local()
        user = data("user")

    通过调用local代理:class:`LocalStack`的第一项，传递一个name来代理这个属性

    .. code-block::

        app_stack = LocalStack()
        current_app = app_stack()
        g = app_stack("g")

    传递一个fuction来代理此方法的返回值，以前曾使用此方法访问本地对象的属性直到现在才支持

    .. code-block:: python

        session = LocalProxy(lambda: request.session)

    ``__repr__``和``__class__``也被代理，因此``repr(x)``和``isinstance(x, cls)``
    看起来像被代理的对象.使用``issubclass(type(x), LocalProxy)``检查对象是否被代理

    .. code-block:: python

        repr(user) # <User admin>
        isinstance(user, User) # True
        issubclass(type(user), LocalProxy) # True
    """

    _get_current_object: t.Callable[[], T]
    """返回此代理绑定的当前对象，如果代理未绑定，抛出``RuntimeError``
    
    如果需要将此对象传递给不懂代理的东西时应该使用，如果在一个方法中多次获取对象时对性能
    也很有用，而不是多次调用代理
    """

    def __init__(
        self,
        local: ContextVar[T] | Local | LocalStack[T] | t.Callable[[], T],
        name: str | None = None,
        *,
        unbound_message: str | None = None,
    ) -> None:
        if name is None:
            get_name = _identity
        else:
            get_name = attrgetter(name) # type: ignore[assignment]
        
        if unbound_message is None:
            unbound_message = "object is not bound"
        
        if isinstance(local, Local):
            if name is None:
                raise TypeError("'name' is required when proxying as 'Local' object.")
            
            def _get_current_object() -> T:
                try:
                    return get_name(local) # type: ignore[return-value]
                except AttributeError:
                    raise RuntimeError(unbound_message) from None
        elif isinstance(local, LocalStack):

            def _get_current_object() -> T:
                obj = local.top

                if obj is None:
                    raise RuntimeError(unbound_message)
                
                return get_name(obj)
        elif isinstance(local, ContextVar):
            def _get_current_object() -> T:
                try:
                    obj = local.get()
                except LookupError:
                    raise RuntimeError(unbound_message) from None
                
                return get_name(obj)
        
        elif callable(local):
            def _get_current_object() -> T:
                return get_name(local())

        else:
            raise TypeError(f"Don't know how to proxy '{type(local)}'.")
        
        object.__setattr__(self, "_LocalProxy__wrapped", local)
        object.__setattr__(self, "_get_current_object", _get_current_object)

    __getattr__ = _ProxyLookup(getattr)