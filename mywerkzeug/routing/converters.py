import typing as t

if t.TYPE_CHECKING:
    from .map import Map

class ValidationError(ValueError):
    """有效错误.  如果规则转换器引发此异常，则表示该规则与当前 URL 不匹配，并将尝试下一个 URL。
    """

class BaseConverter:
    """converters的基类
    
    如果``regex``包含``/``,``part_isolating``默认为``False`` 
    """
    regex = "[^/]+"
    weight = 100
    part_isolating = True

    def __init__(self, map: Map, *args: t.Any, **kwargs: t.Any) -> None:
        self.map = map


class UnicodeConverter(BaseConverter):
    pass

class AnyConverter(BaseConverter):
    pass

class PathConverter(BaseConverter):
    """类似默认的:class:`UnicodeConverter`,但是也可以匹配``/``，对于wikis和
    相似的应用这很有用
    
        Rule('/<path:wikipage>')
        Rule('/<path:wikipage/edit>')
    
    :param map: the :class:`Map`.
    """
    part_isolating = False
    regex = "[^/].*?"
    weight = 200

class NumberConverter(BaseConverter):
    """`IntegerConverter`和`FloatConverter`的基类"""
    weight = 50


class IntegerConverter(NumberConverter):
    """仅接受整数值：：
        Rule("/page/<int:page>")
        
    默认仅接受无符号正数，``sigined``参数允许有符号负数值::
        
        Rule("/page/<int(signed=True):page>")
    
    :param map: :class:`Map`
    :param fixed_digits: URL中固定数。例如若设置为``4``，仅会匹配类似于``/0001``的
        URL，默认变量的长度
    :param min: 最小值
    :param max: 最大值
    :param signed: 是否允许有符号负数值
    """

    regex = r"\d+"

class FloatConverter(NumberConverter):
    """仅接受浮点值
    
        Rule("/probability/<float:probability>")
    
    默认仅接受无符号，正数，``signed``参数允许有符号负数值::

        Rule("/offset/<float(signed=True):offset>")
    
    :param map: :class:`Map`
    :param min: 最小值
    :param max: 最大值
    :param signed: 是否允许有符号负数值
    """

    regex = r"\d+\.\d+"

class UUIDConverter(BaseConverter):
    """仅接受UUID字符串
    
        Rule('/object/<uuid:identifier>')
    """

    regex = (
        r"[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-"
        r"[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}"
    )

#: 用于map的默认converters字典
DEFAULT_CONVERTERS: t.Mapping[str, type[BaseConverter]] = {
    "default": UnicodeConverter,
    "string": UnicodeConverter,
    "any": AnyConverter,
    "path": PathConverter,
    "int": IntegerConverter,
    "float": FloatConverter,
    "uuid": UUIDConverter,
}