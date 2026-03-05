
import typing as t
from threading import Lock
import warnings
from urllib.parse import urljoin

from .._internal import _get_environ
from .._internal import _wsgi_decoding_dance
from ..datastructures import ImmutableDict
from ..exceptions import BadHost
from ..exceptions import HTTPException
from ..exceptions import MethodNotAllowed
from .converters import DEFAULT_CONVERTERS
from .exceptions import RequestRedirect
from .matcher import StateMachineMatcher
from .rules import _simple_rule_re
from .rules import Rule

from ..wsgi import get_host

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

    from ..wrappers.request import Request
    from .converters import BaseConverter
    from .rules import RuleFactory

class Map:
    """存储URL规则和路由配置参数。某些配置值只存在于`Map`实例，因为他们影响了所有规则
    其他仅仅是默认的并且可以被每个规则覆盖。注意除了`rules`之外必须使用关键字参数指定所有参数

    :param rules: 用于此map的所有url 规则
    :param default_subdomain: 默认的子域名，用于没有指定子域名的规则
    :param strict_slashes: 若规则以 /结尾但是用于匹配的URL没有，重定向为以斜杠结尾的URL
    :param merge_slashes: 当匹配或者构建URLs时合并连续斜杠，匹配会重定向到正常的URL
        变量部分的斜杠不会合并
    :param redirect_defaults: 若未通过此方式访问，则会重定向到默认规则，用于创建唯一URLs
    :param converters: 转换器的字典用于向转换器列表中添加其他转换器，若重定义一个转换器
        会覆盖先前的
    :param sort_parameters: 若设置为`True`, url参数会被存储，参考`url_encode`
    :param sort_key: `url_encode`的sort key 方法
    :param host_matching: 若设置为`True`, 则会启用host matching特性而关闭subdomain
        如果启用了，规则将使用`host`参数而非`subdomain`参数
    """

    #: 默认converters字典
    default_converters = ImmutableDict(DEFAULT_CONVERTERS)

    # 当升级是lock的type
    lock_class = Lock

    def __init__(
        self,
        rules: t.Iterable[RuleFactory] | None = None,
        default_subdomain: str = "",
        strict_slashes: bool = True,
        merge_slashes: bool = True,
        redirect_defaults: bool = True,
        converters: t.Mapping[str, type[BaseConverter]] | None = None,
        sort_parameters: bool = False,
        sort_key: t.Callable[[t.Any], t.Any] | None = None,
        host_matching: bool = False,
    ) -> None:
        self._matcher = StateMachineMatcher(merge_slashes)
        self._rules_by_endpoint: dict[t.Any, list[Rule]] = {}
        self._remap = True
        self._remap_lock = self.lock_class()

        self.default_subdomain = default_subdomain
        self.strict_slashes = strict_slashes
        self.redirect_defaults = redirect_defaults
        self.host_matching = host_matching

        self.converters = self.default_converters.copy()
        if converters:
            self.converters.update(converters)
        
        self.sort_parameters = sort_parameters
        self.sort_key = sort_key

        for rulefactory in rules or ():
            self.add(rulefactory)
    
    @property
    def merge_slashes(self) -> bool:
        return self._matcher.merge_slashes

    def add(self, rulefactory: RuleFactory) -> None:
        """添加一个新规则或factory到mpa 并绑定它，要求该规则未绑定到其他map
        
        :param rulefactory: a :class:`Rule` 或者 :class:`RuleFactory`
        """
        for rule in rulefactory.get_rules(self):
            rule.bind(self)
            if not rule.build_only:
                self._matcher.add(rule)
            self._rules_by_endpoint.setdefault(rule.endpoint, []).append(rule)
        self._remap = True

    def bind(
        self,
        server_name: str,
        script_name: str | None = None,
        subdomain: str | None = None,
        url_scheme: str = "http",
        default_method: str = "GET",
        path_info: str | None = None,
        query_args: t.Mapping[str, t.Any] | str | None = None,
    ) -> MapAdapter:
        """根据调用参数返回一个新的:class:`MapAdapter`实例。`script_name`默认为``'/'``
        若未被指定或者是None时，至少需要`server_name`因为HTTP RFC需要重定向使用绝对URLs，
        因此Werkzeug引发的所有重定向异常会包含完整的规范URL。

        若没有path_info传递给:meth:`match`,会使用传递给bind的默认path info，尽管在手动
        bind调用时这没有用，但当你绑定一个map到早已包含path info到WSGI环境时，这很有用

        若没有定义，此map的`subdomain`会默认设置为`default_subdomain`，如果没有
        `default_subdomain`，不能使用subdomain特性
        """
        server_name = server_name.lower()
        if self.host_matching:
            if subdomain is not None:
                raise RuntimeError("host matching enabled and subdomain was provided")
        elif subdomain is None:
            subdomain = self.default_subdomain
        if script_name is None:
            script_name = "/"
        if path_info is None:
            path_info = "/"

        # Port不是IDNA的一部分，并且可能使用名称超过63个OCT进制字节的限制
        server_name, port_sep, port = server_name.partition(":")

        try:
            server_name = server_name.encode("idna").decode("ascii")
        except UnicodeError as e:
            raise BadHost() from e
        
        return MapAdapter(
            self,
            f"{server_name}{port_sep}{port}",
            script_name,
            subdomain,
            url_scheme,
            path_info,
            default_method,
            query_args,
        )

    def bind_to_environ(
        self,
        environ: WSGIEnvironment | Request,
        server_name: str | None = None,
        subdomain: str | None = None,
    ) -> MapAdapter:
        """类似:meth:`bind`但是可以传递WSGI环境，会从字典中获取信息。注意由于protocol中的
        限制没有办法从环境中获取当前的subdomain和真正的`server_name`.若不提供，Werkzeug
        会使用`SERVER_NAME`和`SERVER_PORT`(或者`HTTP_PORT`，如果有)作为`server_name`
        并禁用subdomain特性
        
        若`subdomain`为`None`, 但是环境和server name提供，会自动计算当前的subdomain.
        例如：`server_name`是``'example.com'``,wsgi `environ`中的`SERVER_NAME`是
        ``'staging.dev.example.com'``, 计算的subdomain是``'staging.dev'``

        如果作为environ传递的对象有一个environ属性，会使用该属性的值。这会允许你传递一个
        request对象。另外，`PATH_INFO`添加为:class:`MapAdapter`的默认值，因此不需要
        传递path info给此match方法。
        """
        env = _get_environ(environ)
        wsgi_server_name = get_host(env).lower()
        scheme = env["wsgi.url_scheme"]
        upgrade = any(
            v.strip() == "upgrade"
            for v in env.get("HTTP_CONNECTION", "").lower().split(",")
        )

        if upgrade and env.get("HTTP_UPGRADE", "").lower() == "websocket":
            scheme = "wss" if scheme == "https" else "ws"

        if server_name is None:
            server_name = wsgi_server_name
        else:
            server_name = server_name.lower()
            
            #去除标准端口以匹配get_host()
            if scheme in {"http", "ws"} and server_name.endswith(":80"):
                server_name = server_name[:-3]
            elif scheme in {"https", "wss"} and server_name.endswith(":443"):
                server_name = server_name[:-4]
        
        if subdomain is None and not self.host_matching:
            cur_server_name = wsgi_server_name.split(".")
            real_server_name = server_name.split(".")
            offset = -len(real_server_name)

            if cur_server_name[offset:] != real_server_name:
                # 某些情况下如果server直接通过IP address获取，即使配置有效也会发生。
                # 不像Werkzeug0.7 或者更早版本， 此处使用了非法的subdomain，这会
                # 导致匹配时出现一个404error
                warnings.warn(
                    f"Current server name {wsgi_server_name!r} dosen't match configured"
                    f" server name {server_name!r}",
                    stacklevel=2,
                )
                subdomain = "<invalid>"
            else:
                subdomain = ".".join(filter(None, cur_server_name[:offset]))

        def _get_wsgi_string(name: str) -> str | None:
            val = env.get(name)
            if val is not None:
                return _wsgi_decoding_dance(val)
            return None

        script_name = _get_wsgi_string("SCRIPT_NAME")
        path_info = _get_wsgi_string("PATH_INFO")
        query_args = _get_wsgi_string("QUERY_STRING")
        return Map.bind(
            self,
            server_name,
            script_name,
            subdomain,
            scheme,
            env["REQUEST_METHOD"],
            path_info,
            query_args=query_args,
        )

    def update(self) -> None:
        """在匹配和构建前调用以保持在此改变之后编译规则的正确顺序"""
        if not self._remap: return
        
        with self._remap_lock:
            if not self._remap: return

            self._matcher.update()
            for rules in self._rules_by_endpoint.values():
                rules.sort(key=lambda x: x.build_compare_key())
            self._remap = False

class MapAdapter:
    """由:meth:`Map.bind`或者:meth:`Map.bind_to_environ`返回，并基于运行时信息做
    URL匹配和构建
    """

    def __init__(
        self,
        map: Map,
        server_name: str,
        script_name: str,
        subdomain: str | None,
        url_scheme: str,
        path_info: str,
        default_method: str,
        query_args: t.Mapping[str, t.Any] | str | None = None,
    ):
        self.map = map
        self.server_name = server_name

        if not script_name.endswith("/"):
            script_name += "/"
        
        self.script_name = script_name
        self.subdomain = subdomain
        self.url_scheme = url_scheme
        self.path_info = path_info
        self.default_method = default_method
        self.query_args = query_args
        self.websocket = self.url_scheme in {"ws", "wss"}

    @t.overload
    def match(
        self,
        path_info: str | None = None,
        method: str | None = None,
        return_rule: t.Literal[False] = False,
        query_args: t.Mapping[str, t.Any] | str | None = None,
        websocket: bool | None = None,
    ) -> tuple[t.Any, t.Mapping[str, t.Any]]: ...

    @t.overload
    def match(
        self,
        path_info: str | None = None,
        method: str | None = None,
        return_rule: t.Literal[True] = True,
        query_args: t.Mapping[str, t.Any] | str | None = None,
        websocket: bool | None = None,
    ) -> tuple[Rule, t.Mapping[str, t.Any]]: ...

    def match(
        self,
        path_info: str | None = None,
        method: str | None = None,
        return_rule: bool = False,
        query_args: t.Mapping[str, t.Any] | str | None = None,
        websocket: bool | None = None,
    ) -> tuple[t.Any | Rule, t.Mapping[str, t.Any]]:
        """使用方法很简单，传递匹配当前path info和方法(默认`GET`), 之后：
        
        - 接收到 `NotFound` 异常表示没有URL匹配，`NotFound`异常也是一个WSGI引用，可以
          调用来获取一个page not found页面（恰好与`mywerkzeug.exception.NotFound
          是同一个对象`）

        - 接收一个`MethodNotAllowed`异常表示有与URL匹配但不是当前请求的方法。这对于
         RESTful 应用很有用

        - 接收一个带`new_url`属性的`RequestRedirect`异常. 此异常用于提示你要从你的
         WSGI应用请求Werkzeug requests。 例如你请求了``/foo``而正确的URL是``/foo/``
         可以使用`RequestRedirect`实例作为类response对象与其他`HTTPException`子类相同
        
        - 接收一个``WebsocketMismatch``异常 如果仅匹配到websocket规则但是绑定了一个
         HTTP request, 或者匹配到了一个HTTP rule但是绑定了一个websocket请求

        - 接收到了一个``(endpoint, arguments)``tuple 如果匹配成功(除非`return_rule`
         为 True, 这种情况下会得到一个``(rule, arguments)``形式的tuple)
        
        如果未将路径信息传递给匹配到的方法，默认的map的默认路径信息会使用（如果没有确切定义，
        则默认为root URL）

        所有抛出的异常为`HTTPException`的子类，所以都可以作为WSGIresponse，它们会渲染一个
        通用错误或重定向页面

        使用案例：

        >>> m = Map([
        ...    Rule('/', endpoint='index'),
        ...    Rule('/downloads/', endpoint='downloads/index'),
        ...    Rule('/downloads/<int:id>', endpoint='downloads/show'),
        ... ])
        >>> urls = m.bind("example.com", "/")
        >>> urls.match("/", "GET")
        ('index', {})
        >>> urls.match("/downloads/42")
        ('downloads/show', {'id': 42})

        下面是重定向和未匹配到的情况：

        >>> urls.match("downloads")
        Traceback (most recent call last):
         ...
        RequestRedirect: http://example.com/downloads/
        >>> urls.match("missing")
        Traceback (most recent call last):
         ...
        NotFound: 404 Not Found

        :param path_info: 用于匹配的path info，覆盖绑定时指定的路径信息
        :param method: 用于匹配的HTTP方法，覆盖绑定时指定的路径信息
        :param return_rule: 返回匹配到的rule而不仅是endpoint（默认False）
        :param query_args: 可选查询参数，用于自动重定向，可以是string或者字典，目前不可能
            使用query 参数用于URL匹配
        :param websocket: 匹配Websocket而不是HTTP request。 websocket请求需要``ws``
            或者``wss``的:attr:`url_scheme`.这将覆盖检测结果
        """
        self.map.update()
        if path_info is None:
            path_info = self.path_info
        if query_args is None:
            query_args = self.query_args or {}
        method = (method or self.default_method).upper()

        if websocket is None:
            websocket = self.websocket
        
        domain_part = self.server_name

        if not self.map.host_matching and self.subdomain is not None:
            domain_part = self.subdomain
        
        path_part = f"/{path_info.lstrip('/')}" if path_info else ""

        try: # "" "/" "GET" False
            result = self.map._matcher.match(domain_part, path_part, method, websocket)
        except Exception as e:
            print(f"MapAdapter::match: {str(e)} {type(e)}")
        else:
            rule, rv = result

        if self.map.redirect_defaults:
            redirect_url = self.get_default_redirect(rule, method, rv, query_args)
            if redirect_url is not None:
                raise RequestRedirect(redirect_url)
        
        if rule.redirect_to is not None:
            if isinstance(rule.redirect_to, str):

                def _handle_match(match: t.Match[str]) -> str:
                    value = rv[match.group(1)]
                    return rule._converters[match.group(1)].to_url(value)

                redirect_url = _simple_rule_re.sub(_handle_match, rule.redirect_to)
            else:
                redirect_url = rule.redirect_to(self, **rv)
            
            if self.subdomain:
                netloc = f"{self.subdomain}.{self.server_name}"
            else:
                netloc = self.server_name

            raise RequestRedirect(
                urljoin(
                    f"{self.url_scheme or 'http'}://{netloc}{self.script_name}",
                    redirect_url,
                )
            )

        if return_rule:
            return rule, rv
        else:
            return rule.endpoint, rv

    def allowed_methods(self, path_info: str | None = None) -> t.Iterable[str]:
        """返回匹配给定路径的有效方法"""
        try:
            self.match(path_info, method="--")
        except MethodNotAllowed as e:
            return e.valid_methods # type: ignore
        except HTTPException:
            pass
        return []

    def get_default_redirect(
        self,
        rule: Rule,
        method: str,
        values: t.MutableMapping[str, t.Any],
        query_args: t.Mapping[str, t.Any] | str,
    ) -> str | None:
        """帮助方法如果找到了一个重定向URL则返回，仅用于默认的重定向"""

        assert self.map.redirect_defaults
        for r in self.map._rules_by_endpoint[rule.endpoint]:
            # 从这条规则之后的所有规则（包括我们自己设定的规则）在默认设置中优先级都
            # 较低，将优先级最高的哪些规则排在前面进行构建
            if r is rule: break
            if r.provides_defaults_for(rule) and r.suitable_for(values, method):
                values.update(r.defaults) # type: ignore
                domain_part, path = r.build(values) # type: ignore
                return self.make_redirect_url(path, query_args, domain_part=domain_part)
        return None

                
