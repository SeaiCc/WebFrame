
import typing as t

from mywerkzeug.exceptions import HTTPException
from mywerkzeug.wrappers import Request as RequestBase
from mywerkzeug.wrappers import Response as ResponseBase

from . import json
from .helpers import _split_blueprint_path

if t.TYPE_CHECKING:
    from mywerkzeug.routing import Rule

class Request(RequestBase):
    """Flask中默认使用的request，记住匹配的endpoint和view参数

    最终得到的是:class:`~myflask.request`,如果想替换使用的request对象
    可以继承本类并设置子类的attr:`~myflask.Flask.request_class`

    request对象是一个:class:`~mywerkzeug.wrappers.Request`的子类并且提供了
    Werkzeug定义的所有的以及Flask特定的一些属性
    """

    #: 匹配请求的内部URL规则，这对于检查哪些方法允许从before/after处理程序
    #: (``request.url_rule.methods``)等对URL进行处理很有用，尽管对于URL rule请求的方法
    #: 无效， 有效的列表可以在 ``routing_exception.valid_methods`` 中找到
    #: （Werkzeug 异常 :exc:`~werkzeug.exceptions.MethodNotAllowed` 的一个属性），
    #: 因为请求从未在内部绑定。
    url_rule: Rule | None = None

    #: 匹配请求的视图参数字典，如果匹配时发生异常，为``None``
    view_args: dict[str, t.Any] | None = None
    
    json_module: t.Any = json

    #: 若匹配URL失败，这个异常会作为request handling的一部分抛出
    #: 通常为:exec:`~mywerkzeug.exceptions.NotFound`或其他相似的
    routing_exception: HTTPException | None = None

    @property
    def endpoint(self) -> str | None:
        """请求URL匹配的endpoint

        如果匹配失败或者没有执行， 为``None``

        与:attr:`view_args`结合可以用来重构相同的URL或者修改的URL
        """
        if self.url_rule is not None:
            return self.url_rule.endpoint # type: ignore[no-any-return]

        return None

    @property
    def blueprint(self) -> str | None:
        """当前蓝图的注册名称
        
        如果endpoint非蓝图一部分,或者URL匹配失败或者没有提供，为``None``

        并不一定与蓝图创建时的名称一致，可能会被嵌套或者注册为不同的名字
        """
        endpoint = self.endpoint

        if endpoint is not None and "." in endpoint:
            return endpoint.rpartition(".")[0]
        
        return None

    @property
    def blueprints(self) -> list[str]:
        """当前蓝图及父蓝图的注册名称
        
        如果没有当前拦路或者URL匹配失败会是一个空list
        """
        name = self.blueprint

        if name is None: return []

        return _split_blueprint_path(name)


class Response(ResponseBase):
    pass
