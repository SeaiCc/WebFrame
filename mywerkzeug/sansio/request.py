
from ..datastructures import Headers
from ..datastructures import ImmutableMultiDict
from ..datastructures import MultiDict
from ..utils import cached_property
from .http import parse_cookie
from .utils import get_host

class Request:
    """表示HTTP请求到非IO部分，包括method, URL info 和headers

    该类不适用于一般用途。仅在实现WSGI，ASGI或者其他HTTP应用使用。Werkzeug提供了一个
    WSGI实现在:cls:`mywerkzeug.wrappers.Request`

    :param method: 请求的方法，如(GET)
    :param scheme: 请求使用的协议URL scheme，如(https) or (wss).
    :param server: 请求的服务器地址。(host, port), 对于 unix sockets (path, None)
         (None) 表示未知.
    :param root_path: 应用挂载的路径，会添加到生成的URL前面，但不属于路由匹配的一部分
    :param path: 请求URL路径部分，在(root_path)后面
    :param query_string: 请求URL中"?"后面的部分
    :param headers: 请求中包含的headers
    :param remote_addr: 发送请求的客户端地址

    (charset), (url_charset), (encoding_errors) 在版本3.0中移除
    """

    #: 用于来自WSGI环境的字典值的类型，（如:attr:`cookies`）默认使用
    #: :class:`~mywerkzeug.datastructures.ImmutableMultiDict`
    dict_storage_class: type[MultiDict[str, t.Any]] = ImmutableMultiDict

    #: 处理请求时有效的host 名，默认所有hosts被信任，会接受所有客户端的请求
    #: 因为``Host``和``X-Forwarded-Host``头可以被恶意客户端设置为任何值，推荐设置这个属性
    #: 或者在proxy中设置一个相同的校验器（如果application运行在proxy后面）
    trusted_hosts: list[str] | None = None
    
    def __init__(
        self,
        method: str,
        scheme: str,
        server: tuple[str, int | None] | None,
        root_path: str,
        path: str,
        query_string: bytes,
        headers: Headers,
        remote_addr: str | None,
    ) -> None:
        # 请求方法，如(GET)
        self.method = method.upper()
        # 请求使用的协议URL scheme，如(https) or (wss)
        self.scheme = scheme
        # 请求的服务器地址。(host, port), 对于 unix sockets (path, None)
        # (None) 表示未知.
        self.server = server
        # 应用挂载的路径，会添加到生成的URL前面，但不属于路由匹配的一部分
        self.root_path = root_path.rstrip("/")
        # 请求URL路径部分，在(root_path)后面。用于路由匹配应用内部的路径。
        self.path = "/" + path.lstrip("/")
        #  "?"后的一部分. 使用 (args) 解析查询参数.
        self.query_string = query_string
        # 请求中包含的headers
        self.headers = headers
        # 发送请求的客户端地址
        self.remote_addr = remote_addr
        
    
    @cached_property
    def host(self) -> str:
        """请求的主机域名，如果非标准端口则包含端口。使用:attr:`trusted_hosts`校验"""
        return get_host(
            self.scheme, self.headers.get("host"), self.server, self.trusted_hosts
        )
    
    @property
    def cookies(self) -> ImmutableMultiDict[str, str]:
        """一个包含请求中所有cookie内容的:class:`dict`"""
        wsgi_combined_cookie = ";".join(self.headers.getlist("cookie"))
        return parse_cookie( # type: ignore
            wsgi_combined_cookie, cls=self.dict_storage_class
        )
