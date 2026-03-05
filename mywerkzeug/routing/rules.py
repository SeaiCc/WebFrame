import ast
import re
import typing as t
from dataclasses import dataclass
from types import CodeType
from urllib.parse import quote

if t.TYPE_CHECKING:
    from .converters import BaseConverter
    from .map import Map

class Weighting(t.NamedTuple):
    number_static_weights: int
    static_weights: list[tuple[int, int]]
    number_argument_weights: int
    argument_weights: list[int]

@dataclass
class RulePart:
    """规则的一部分

    规则可以用"/"分割的部分来表示，该类的实例代表这些部分。content可以是raw content
    （若static）， 或者regex string来配置against，weight在匹配时排序部分
    """

    content: str
    final: bool
    static: bool
    suffixed: bool
    weight: Weighting

_part_re = re.compile(
    r"""
    (?:
        (?P<slash>/)                                    # 斜线
      |
        (?P<static>[^</]+)                              # 静态规则数据
      |
        (?:
          <
            (?:
              (?P<converter>[a-zA-Z_][a-zA-Z0-9_]*)    # 转换器名称
              (?:\((?P<arguments>.*?)\))?              # 转换器参数
              :                                        # 变量分割符
            )?
            (?P<variable>[a-zA-Z_][a-zA-Z0-9_]*)      # 变量名
            >
        )
    )
    """,
    re.VERBOSE
)

_simple_rule_re = re.compile(r"<([^>]+)>")
_converter_args_re = re.compile(
    r"""
    \s*
    ((?P<name>\w+)\s*=\s*)?
    (?P<value>
        True|False|
        \d+.\d+|
        \d+.|
        \d+|
        [\w\d_.]+|
        [urUR]?(?P<stringval>"[^"]*?"|'[^']*')    
    )\s*,
    """,
    re.VERBOSE
)

_PYTHON_CONSTANTS = {"None": None, "True": True, "False": False}

def _pythonize(value: str) -> None | bool | int | float | str:
    if value in _PYTHON_CONSTANTS:
        return _PYTHON_CONSTANTS[value]
    for convert in int, float:
        try:
            return convert(value)
        except ValueError:
            pass
    if value[:1] == value[-1:] and value[0] in "\"'":
        value = value[1:-1]
    return str(value)

def parse_converter_args(argstr: str) -> tuple[tuple[t.Any, ...], dict[str, t.Any]]:
    argstr += ","
    args = []
    kwargs = {}
    position = 0

    for item in _converter_args_re.finditer(argstr):
        if item.start() != position:
            raise ValueError(
                f"Cannot parse converter argument '{argstr[position : item.start()]}"
            )

        value = item.group("stringval")
        if value is None:
            value = item.group("value")
        value = _pythonize(value)
        if not item.group("name"):
            args.append(value)
        else:
            name = item.group("name")
            kwargs[name] = value
        position = item.end()
    
    return tuple(args), kwargs

_ASTT = t.TypeVar("_ASTT", bound=ast.AST)

def _prefix_names(src: str, expected_type: type[_ASTT]) -> _ASTT:
    """带有`.`的ast parse 和 prefix name 来避免与用户变量冲突"""
    tree: ast.AST = ast.parse(src).body[0]
    if isinstance(tree, ast.Expr):
        tree = tree.value
    if not isinstance(tree, expected_type):
        raise TypeError(
            f"AST node is of type {type(tree).__name__}, not {expected_type.__name__}"
        )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            node.id = f".{node.id}"
    return tree

_CALL_CONVERTER_CODE_FMT = "self._converters[{elem!r}].to_url()"
_IF_KWARGS_URL_ENCODE = """
if kwargs:
    params = self._encode_query_vars(kwargs)
    q = "?" if params else ""
else:
    q = params = ""
"""
_IF_KWARGS_URL_ENCODE_AST = _prefix_names(_IF_KWARGS_URL_ENCODE, ast.If)
_URL_ENCODE_AST_NAMES = (
    _prefix_names("q", ast.Name),
    _prefix_names("parms", ast.Name),
)

class RuleFactory:
    """只要你有更复杂的URL设置，使用rule factories来避免重复任务是一个好主意。它们中一些
    是内置的，一些可以被`RuleFactory`子类和`get_rules`重写添加
    """

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        """`RuleFactory`必须重写这个方法并返回一个可以迭代的规则"""
        raise NotImplementedError()

class Rule(RuleFactory):
    """一条规则对应一个URL模式。有一些`Rule`的选项能够改变他的行为，并传递给`Rule`构造器
    注意除了rule-string,所有参数必须是关键字参数，为了在Werkzeug升级时不破坏application

    `string`
        Rule string 基本上就是普通的URL路径，格式为``<converter(arguments):name>``
        converter和arguments是可选的。如果converter没有定义，`default`converter 会
        被使用，意味着标准配置中的`string`

        以斜杠结尾的URL规则是分支URLs，其余则是叶子URL。如果`strict_slashes`启用（默认）
        所有没有尾斜杠的匹配到的分支URLs会触发相同的重定向到相同的URL，并在URL末尾添加
        缺失的斜杠

        converters被定义在`Map`
    
    `endpoint`
        规则的endpoint，可以是任何东西，方法的引用，字符串，数字等。推荐使用字符串，因为
        endpoint用于生成URL
    
    `defaults`
        一个可选字典，其中包含具有相同endpoint的其他规则的默认值。如果想要一个唯一的URLs
        有一个tricky::
            
            url_map = Map([
                Rule('/all/', defaults={'page': 1}, endpoint='all_entries'),
                Rule('/all/page/<int:page>', endpoint='all_entries')
            ])
    
    现在访问``http://examples.com/all/page/1``,会重定向到``http://examples.com/all/``
    如果`redirect_defaults`在 `Map`实例上关闭，仅会影响URL生成

    `subdomain`
        用于此规则的subdomain的规则字符串。如果没有指定，规则仅匹配map的`default_subdomain`
        如果map没有绑定subdomain，此特性会被忽略

        如果你想在不同subdomain上拥有用户配置并将所有subdomain转发到你的应用上，这将很有用

            url_map = Map([
                Rule('/', subdomain='<usrname>', endpoint='user/homepage'),
                Rule('/stats', subdomain='<username>', endpoint='user/stats')
            ])
    
    `methods`
        规则应用到http方法序列，如果没有指定，所有方法都是允许的。比如你想给`POST`和`GET`
        不同的endpoint这会很有用，如果定义了方法并且路径匹配，但匹配的方法不在此列表中或
        该路径的另一个规则的列表中，则引发的错误类型为“MethodNotAllowed”，
        而不是“NotFound”。如果`GET`在列表中，`HEAD`不在，`HEAD`会自动添加
    
    `strict_slashes`
        仅针对此规则覆盖 `map` 中 `strict_slashes` 的设置。如果没有指定，使用`Map`设置
    
    `merge_slashes`
        覆盖此规则的:attr:`Map.merge_slashes`

    `build_only`
        若设置为True，规则永远不会匹配但会创建一个被构建URL，如果你在subdomain或者folder
        上有资源不被WSGI application处理（像静态数据）这将很有用
    
    `redirect_to`
        若给到，必须为字符串或者callable。在callable情况下，调用时传入触发匹配的URL
        适配器和作为关键字参数的URL值，并必须返回重定向的目标，否则必须为在规则格式的
        placeholders的字符串::
            def foo_with_slug(adapter, id):
                # 向数据库查询就ID的slug，对于werkzeug没有什么用
                return f'foo/{Foo.get_slug_for_id(id)}'
            
                url_map = Map([
                    Rule('/foo/<slug>', endpoint='foo'),
                    Rule('/some/old/url/<slug>', redirect_to='foo/<slug>'),
                    Rule('/other/old/url/<int:id>', redirect_to=foo_with_slug)
                ])
            
            当规则匹配，路由系统会抛出带有targe和redirect的`RequestRedirect`异常

            记住，URL会和脚本的URL root join，因此不要用头部斜杠在target URL，除非
            你确实指该域的根。
    
    `alias`
        如果启用，此规则将作为另一个有相同endpoint和参数的规则的别名。

    `host`
        如果提供，并且URL map有host matching启用，这可以被使用以给全局host提供匹配规则，
        也意味着subdomain 特性关闭

    `websocket`
        若为True，规则仅匹配Websocket (`ws://`, `wss://`)请求，默认规则仅匹配HTTP
    """

    def __init__(
        self, 
        string: str,
        defaults: t.Mapping[str, t.Any] | None = None,
        subdomain: str | None = None,
        methods: t.Iterable[str] | None = None,
        build_only: bool = False,
        endpoint: t.Any | None = None,
        strict_slashes: bool | None = None,
        merge_slashes: bool | None = None,
        redirect_to: str | t.Callable[..., str] | None = None,
        alias: bool = False,
        host: str | None = None,
        websocket: bool = False,
    ) -> None:
        if not string.startswith("/"):
            raise ValueError(f"URL rule '{string}' must start with a slash.")

        self.rule = string
        self.is_leaf = not string.endswith("/")
        self.is_branch = string.endswith("/")

        self.map: Map = None # type:ignore
        self.strict_slashes = strict_slashes
        self.merge_slashes = merge_slashes
        self.subdomain = subdomain
        self.host = host
        self.defaults = defaults
        self.build_only = build_only
        self.alias = alias
        self.websocket = websocket

        if methods is not None:
            if isinstance(methods, str):
                raise TypeError("'method' should be a list of strings.")

            methods = {x.upper() for x in methods}

            if "HEAD" not in methods and "GET" in methods:
                methods.add("HEAD")
            
            if websocket and methods - {"GET", "HEAD", "OPTIONS"}:
                raise ValueError(
                    "Websocket rules can only use GET, HEAD, and OPTIONS methods."
                )
        
        self.methods = methods
        self.endpoint: t.Any = endpoint
        self.redirect_to = redirect_to

        if defaults:
            self.arguments = set(map(str, defaults))
        else:
            self.arguments = set()
        
        self._converters: dict[str, BaseConverter] = {}
        self._trace: list[tuple[bool, str]] = []
        self._parts: list[RulePart] = []

    def get_rules(self, map: Map) -> t.Iterator[Rule]:
        yield self

    def bind(self, map: Map, rebind: bool = False) -> None:
        """将url绑定到map并基于从rule自身获取的信息和从map的默认值来创建一个常规表达式"""

        if self.map is not None and not rebind:
            raise RuntimeError(f"url rule {self!r} already bound to map {self.map!r}")
        self.map = map
        if self.strict_slashes is None:
            self.strict_slashes = map.strict_slashes
        if self.merge_slashes is None:
            self.merge_slashes = map.merge_slashes
        if self.subdomain is None:
            self.subdomain = map.default_subdomain
        self.compile()

    def get_converter(
        self,
        variable_name: str,
        converter_name: str,
        args: tuple[t.Any, ...],
        kwargs: t.Mapping[str, t.Any],
    ) -> BaseConverter:
        """从给到的参数中找converter"""
        if converter_name not in self.map.converters:
            raise LookupError(f"the converter {converter_name!r} does not exist")
        return self.map.converters[converter_name](self.map, *args, **kwargs)

    def _parse_rule(self, rule: str) -> t.Iterable[RulePart]:
        content = ""
        static = True
        arguments_weight = []
        static_weight: list[tuple[int, int]] = []
        final = False
        convertor_number = 0

        pos = 0
        while pos < len(rule):
            match = _part_re.match(rule, pos)
            if match is None:
                raise ValueError(f"malformed url rule: {rule!r}")

            data = match.groupdict()
            if data["static"] is not None:
                static_weight.append((len(static_weight), -len(data["static"])))
                self._trace.append((False, data["static"]))
                content += data["static"] if static else re.escape(data["static"])

            if data["variable"] is not None:
                if static:
                    # 将内容转换为 regex, 因此需要escape
                    content = re.escape(content)
                static = False
                c_args, c_kwargs = parse_converter_args(data["arguments"] or "")
                convobj = self.get_converter(
                    data["variable"], data["converter"] or "default", c_args, c_kwargs
                )
                self._converters[data["variable"]] = convobj
                self.arguments.add(data["variable"])
                if not convobj.part_isolating:
                    final = True
                content += f"(?P<__mywerkzeug_{convertor_number}>{convobj.regex})"
                convertor_number += 1
                arguments_weight.append(convobj.weight)
                self._trace.append((True, data["variable"]))
            
            if data["slash"] is not None:
                self._trace.append((False, "/"))
                if final:
                    content += "/"
                else:
                    if not static:
                        content += r"\Z"
                    weight = Weighting(
                        -len(static_weight),
                        static_weight,
                        -len(arguments_weight),
                        arguments_weight,
                    )
                    yield RulePart(
                        content=content,
                        final=final,
                        static=static,
                        suffixed=False,
                        weight=weight,
                    )
                    content = ""
                    static = True
                    arguments_weight = []
                    static_weight = []
                    final = False
                    convertor_number = 0
            
            pos = match.end()
        
        suffixed = False
        if final and content[-1] == "/":
            # 如果converter是part_isolating=False (匹配斜线) 并且结尾为"/"，
            # 扩展正则表达式以支持斜杠重定向。
            suffixed = True
            content = content[:-1] + "(?<!/)(/?)"
        
        if not static:
            content += r"\Z"
        weight = Weighting(
            -len(static_weight),
            static_weight,
            -len(arguments_weight),
            arguments_weight,
        )
        yield RulePart(
            content=content,
            final=final,
            static=static,
            suffixed=suffixed,
            weight=weight,
        )
        if suffixed:
            yield RulePart(
                content="", final=False, static=True, suffixed=False, weight=weight
            )

    @staticmethod
    def _get_func_code(code: CodeType, name: str) -> t.Callable[..., tuple[str, str]]:
        globs: dict[str, t.Any] = {}
        locs: dict[str, t.Any] = {}
        exec(code, globs, locs)
        return locs[name] # type: ignore

    def provides_default_for(self, rule: Rule) -> bool:
        """对于给定的rule检查是否存在默认值"""

        return bool(
            not self.build_only
            and self.defaults
            and self.endpoint == rule.endpoint
            and self != rule
            and self.arguments == rule.arguments
        )

    def compile(self) -> None:
        """编译规则，并保存"""
        assert self.map is not None, "rule not bound"

        if self.map.host_matching:
            domain_rule = self.host or ""
        else:
            domain_rule = self.subdomain or ""
        self._parts = []
        self._trace = []
        self._converters = {}
        if domain_rule == "":
            self._parts = [
                RulePart(
                    content="",
                    final=False,
                    static=True,
                    suffixed=False,
                    weight=Weighting(0, [], 0, []),
                )
            ]
        else:
            self._parts.extend(self._parse_rule(domain_rule))
        self._trace.append((False, "|"))
        rule = self.rule
        if self.merge_slashes:
            rule = re.sub("/{2,}?", "/", self.rule)
        self._parts.extend(self._parse_rule(rule))

        self._build: t.Callable[..., tuple[str, str]]
        self._build = self._compile_builder(False).__get__(self, None)
        self._build_unknown: t.Callable[..., tuple[str, str]]
        self._build_unknown = self._compile_builder(True).__get__(self, None)

    def _compile_builder(
        self, append_unknown: bool = True
    ) -> t.Callable[..., tuple[str, str]]:
        self.defaults = self.defaults or {}
        dom_ops: list[tuple[bool, str]] = []
        url_ops: list[tuple[bool, str]] = []

        opl = dom_ops 
        for is_dynamic, data in self._trace:
            if data == "|" and opl is dom_ops:
                opl = url_ops
                continue
            
            # 这看起来是一个很荒谬的案例，但是：
            # 如果规则中某个值有默认值，预先将其解析为常量
            if is_dynamic and data in self.defaults:
                data = self._converters[data].to_url(self.defaults[data])
                opl.append((False, data))
            elif not is_dynamic:
                # safe = https://url.spec.whatwg.org/#url-path-segment-string
                opl.append((False, quote(data, safe="!$&'()*+,/:;=@")))
            else:
                opl.append((True, data))
        
        def _convert(elem: str) -> ast.Call:
            ret = _prefix_names(_CALL_CONVERTER_CODE_FMT.format(elem=elem), ast.Call)
            ret.args = [ast.Name(elem, ast.Load())]
            return ret

        def _parts(ops: list[tuple[bool, str]]) -> list[ast.expr]:
            parts: list[ast.expr] = [
                _convert(elem) if is_dynamic else ast.Constant(elem)
                for is_dynamic, elem in ops
            ]
            parts = parts or [ast.Constant("")]
            # 常量折叠
            ret = [parts[0]]
            for p in parts[1:]:
                if isinstance(p, ast.Constant) and isinstance(ret[-1], ast.Constant):
                    ret[-1] = ast.Constant(ret[-1].value + p.value) # type: ignore[operator]
                else:
                    ret.append(p)
            return ret
        
        dom_parts = _parts(dom_ops)
        url_parts = _parts(url_ops)
        body: list[ast.stmt]
        if not append_unknown:
            body = []
        else:
            body = [_IF_KWARGS_URL_ENCODE_AST]
            url_parts.extend(_URL_ENCODE_AST_NAMES)
        
        def _join(parts: list[ast.expr]) -> ast.expr:
            if len(parts) == 1: # shortcut
                return parts[0]
            return ast.JoinedStr(parts)
        
        body.append(
            ast.Return(ast.Tuple([_join(dom_parts), _join(url_parts)], ast.Load()))
        )

        pargs = [
            elem
            for is_dynamic, elem in dom_ops + url_ops
            if is_dynamic and elem not in self.defaults
        ]
        kargs = [str(k) for k in self.defaults]

        func_ast = _prefix_names("def _(): pass", ast.FunctionDef)
        func_ast.name = f"<builder:{self.rule!r}>"
        func_ast.args.args.append(ast.arg(".self", None))
        for arg in pargs + kargs:
            func_ast.args.args.append(ast.arg(arg, None))
        func_ast.args.kwarg = ast.arg(".kwargs", None)
        for _ in kargs:
            func_ast.args.defaults.append(ast.Constant(""))
        func_ast.body = body

        # 为了更好的便利性，使用`ast.parse`而不是`ast.Module`,因为`ast.Module`的重要性
        # 可以改变
        module = ast.parse("")
        module.body = [func_ast]

        # 在line 0， offset 0标记所有东西
        # 比`ast.fix_missing_locations`更少的error-prone
        # 调试构建bad 行号会造成assert失败
        for node in ast.walk(module):
            if "lineno" in node._attributes:
                node.lineno = 1 # type: ignore[attr-defined]
            if "end_lineno" in node._attributes:
                node.end_lineno = node.lineno # type: ignore[attr-defined]
            if "col_offset" in node._attributes:
                node.col_offset = 0 # type: ignore[attr-defined]
            if "end_col_offset" in node._attributes:
                node.end_col_offset = node.col_offset # type: ignore[attr-defined]
            
        code = compile(module, "<mywerkzeug routiong>" , "exec")
        return self._get_func_code(code, func_ast.name)

    def build_compare_key(self) -> tuple[int, int, int]:
        """用于比较大构建比较key"""
        return (1 if self.alias else 0, -len(self.arguments), -len(self.defaults or ()))