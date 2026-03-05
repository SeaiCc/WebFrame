import typing as t
import weakref

if t.TYPE_CHECKING: # pragma: no cover

    from ..sansio.app import App


class JSONProvider:
    """application的JSON操作的标准集合。子类可以使用自定义JSON行为，或者使用不同的JSON库
    
    为了给特定的库实现一个provider，子类继承该类并至少实现:meth:`dumps`和:meth:`loads`
    方法。其他方法都有默认实现

    若使用不同的provider，需要子类``Flask``或:attr:`~myflask.Flask.json_provider_class`
    提供一个provider类。或者设置:attr:`app.json <myflask.Flask.json>` 为一个类的实例

    :param app: application的实例，会作为一个:class:`weakref.proxy`储存到
        :attr:`_app` attribute
    """
    def __init__(self, app: App) -> None:
        self._app: App = weakref.proxy(app)
    


class DefaultJSONProvider(JSONProvider):
    """使用python内置的:mod:`json`库提供JSON操作，序列化以下额外的数据类型:
    
    -   :class:`datetime.datetime` 和 :class:`datetime.date`序列化为:rfc:`822`字串
        与HTTP date格式相同
    -   :class:`uuid.UUID` 序列化为字符串
    -   :class:`dataclasses.dataclass`传递给:func:`dataclasses.asdict`
    -   :class:`~markupsafe.Markup`(或任何有``__html__``方法的对象)会调用
        ``__html__``获取字符串
    """
    pass

    