import email.utils
import re
import typing as t
import warnings
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from hashlib import sha1
from datetime import timezone
from time import struct_time
from time import mktime
from urllib.parse import quote
from urllib.parse import unquote
from urllib.request import parse_http_list as _parse_list_header

from ._internal import _dt_as_utc


if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

_token_chars = frozenset(
    "!#$%&'*+-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ^_`abcdefghijklmnopqrstuvwxyz|~"
)
_etag_re = re.compile(r'([Ww]/)?(?:"(.*?)"|(.*?))(?:\s*,\s*|$)')
HTTP_STATUS_CODES = {
    200: "OK",
}

def quote_header_value(value: t.Any, allow_token: bool = True) -> str:
    """Add double quotes around a header value. If the header contains only ASCII token
    characters, it will be returned unchanged. If the header contains ``"`` or ``\\``
    characters, they will be escaped with an additional ``\\`` character.

    This is the reverse of :func:`unquote_header_value`.
    :param value: The value to quote. Will be converted to a string.
    :param allow_token: Disable to quote the value even if it only has token characters.
    """
    value_str = str(value)
    if not value_str: return '""'
    if allow_token:
        token_chars = _token_chars

        if token_chars.issuperset(value_str):
            return value_str
    
    value_str = value_str.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value_str}"'

def dump_options_header(header: str | None, options: t.Mapping[str, t.Any]) -> str:
    """Produce a header value and ``key=value`` parameters separated by semicolons
    ``;``. For example, the ``Content-Type`` header.

    .. code-block:: python
        dump_options_header("text/html", {"charset": "UTF-8"})
        'text/html; charset=UTF-8'
    
    This is the reverse of :func:`parse_options_header`.
    If a value contains non-token characters, it will be quoted.
    If a value is (None), the parameter is skipped.

    In some keys for some headers, a UTF-8 value can be encoded using a special
    ``key*=UTF-8''value`` form, where ``value`` is percent encoded. This function will
    not produce that format automatically, but if a given key ends with an asterisk
    ``*``, the value is assumed to have that form and will not be quoted further.

    :param header: The primary header value.
    :param options: Parameters to encode as ``key=value`` pairs.

    .. versionchanged::
    2.3 - Keys with (None) values are skipped rather than treated as a bare key.
    2.2.3 - If a key ends with "*", its value will not be quoted.
    """
    segments = []
    if header is not None:
        segments.append(header)
    for key, value in options.items():
        if value is None: continue

        if key[-1] == "*":
            segments.append(f"{key}={value}")
        else:
            segments.append(f"{key}={quote_header_value(value)}")

    return "; ".join(segments)

def dump_header(iterable: dict[str, t.Any] | t.Iterable[t.Any]) -> str:
    """从item或者``key=value``对的list产出header value，以``,``分隔
    
    :func:`parse_list_header`,:func:`parse_dict_header`和:func:`parse_set_header`
    的逆向

    如果value包含了non-token字符，会加引号

    如果value为``None``,key会单独输出

    对于一些header的一些keys，一个UTF-8值可以使用特殊的``key*=UTF-8''value``格式编码，
    ``value``被百分比编码。此方法不会自动产出这种格式，但是如果给定的key以``*``结尾，该
    值假定有这种格式并且不会被加引号

    .. code-block:: python

        dump_header(["foo", "bar baz"])
        'foo, "bar baz"'

        dump_header({"foo": "bar baz"})
        'foo="bar baz"'

    :param iterable: 要创建header的items
    """
    if isinstance(iterable, dict):
        items = []

        for key, value in iterable.items():
            if value is None:
                items.append(key)
            elif key[-1] == "*":
                items.append(f"{key}={value}")
            else:
                items.append(f"{key}={quote_header_value(value)}")
    else:
        items = [quote_header_value(x) for x in iterable]
    
    return ", ".join(items)

def parse_list_header(value: str) -> list[str]:
    """根据`RFC 9110 <https://httpwg.org/specs/rfc9110.html#abnf.extension>`__.
    解析由逗号分隔的列表项

    这扩展了:func:`urllib.request.parse_http_list`，以从值中移除周围的引号

    .. code-block:: python

        parse_list_header('token, "quoted value"')
        ['token', 'quoted value']
    
    :func:`dump_header`的逆向

    :param value: 需要解析的值
    """
    result = []

    for item in _parse_list_header(value):
        if len(item) >= 2 and item[0] == item[-1] == '""':
            item = item[1:-1]
        
        result.append(item)
    
    return result

def parse_dict_header(value: str) -> dict[str, str | None]:
    """使用:func:`parse_list_header`解析list，然后解析``key=value``对解析item
    
    .. code-block:: python

        parse_dict_header('a=b, c="d, e", f')
        {"a": "b", "c": "d, e", "f": None}
    
    :func:`dump_header`的逆向

    如果有key没有value设置为``None``

    处理的字符集在`RFC 2231 <https://www.rfc-editor.org/rfc/rfc2231#section-3>`
    描述，只接受ASCII, UTF-8 和ISO-8859-1字符集，否则值保留引号

    :param value: 需要解析的header 值
    """
    result: dict[str, str | None] = {}

    for item in parse_list_header(value):
        key, has_value, value = item.partition("=")
        key = key.strip()

        if not key:
            # =value不合法
            continue

        if not has_value:
            result[key] = None
            continue

        value = value.strip()
        encoding: str | None = None

        if key[-1] == "*":
            # key*=value 变为key=value, value是根据parse_options_header改变的百分比
            # 编码，没有延续处理
            key = key[:-1]
            match = _charset_value_re.match(value)

            if match:
                # 如果value中有字符集标注，将其分割
                encoding, value = match.groups()
                encoding = encoding.lower()
            
            # 编码的安全列表, 现代客户端需要只发送ASCII或者UTF-8, 这个list后续不会扩展
            # 无效的编码会保留引号
            if encoding in {"ascii", "us-ascii", "utf-8", "iso-8859-1"}:
                # 无效字节在去引号时会被替代
                value = unquote(value, encoding=encoding)
        
        if len(value) >= 2 and value[0] == value[-1] == '""':
            value = value[1:-1]
        
        result[key] = value

    return result

_charset_value_re = re.compile(
    r"""
    ([\w!#$%&*+\-.^`|~]*)' # 字符集部分，可空
    [\w!#$%&*+\-.^`|~]*' # 无需关系语言部分，通常空
    ([\w!#$%&'*+\-.^`|~]+) # 一或多个百分比编码的token字符
    """,
    re.ASCII | re.VERBOSE
)

_TAnyCC = t.TypeVar("_TAnyCC", bound="ds.cache_control._CacheControl")

@t.overload
def parse_cache_control_header(
    value: str | None,
    on_update: t.Callable[[ds.cache_control._CacheControl], None] | None = None,
) -> ds.RequestCacheControl: ...

@t.overload
def parse_cache_control_header(
    value: str | None,
    on_update: t.Callable[[ds.cache_control._CacheControl], None] | None = None,
    cls: type[_TAnyCC] = ...,
) -> _TAnyCC: ...

def parse_cache_control_header(
    value: str | None,
    on_update: t.Callable[[ds.cache_control._CacheControl], None] | None = None,
    cls: type[_TAnyCC] | None = None,
) -> _TAnyCC:
    """解析cache control头，不区分请求和响应的RFC区别，不使用错误的控制语句是你的责任
    
    :param value: 需要被解析的控制头
    :param on_update: 可选调用对象，每次:class:`~mywerkzeug.datastructures.CacheControl`
        对象上的值改变时会调用
    :param cls: 返回对象的类。默认:class:`~mywerkzeug.datastructures.RequestCacheControl`
    :return : `cls`对象
    """
    if cls is None:
        cls = t.cast("type[_TAnyCC]", ds.RequestCacheControl)
    
    if not value:
        return cls((), on_update)
    
    return cls(parse_dict_header(value), on_update)

def generate_etag(data: bytes | None = None) -> str:
    """根据data生成一个ETag值"""
    return sha1(data).hexdigest()

def parse_set_header(
    value: str | None,
    on_update: t.Callable[[ds.HeaderSet], None] | None = None, 
) -> ds.HeaderSet:
    """解析类set头返回一个:class:`~mywerkzeug.datastructures.HeaderSet`对象
    
    >>> hs = parse_set_header('token, "quoted value"')

    返回是一个不区分item大小写的对象，并保证顺序

    >>> 'TOKEN' in hs
    True
    >>> hs.index('quoted value')
    1
    >>> hs
    HeaderSet(['token', 'quoted value'])

    使用:func:`dump_header`从:class:`HeaderSet`中创建一个header

    :param value: 需要解析的header集合
    :param on_update: 可选调用对象，当:class:`~mywerkzeug.datastructure.HeaderSet`
        对象的值改变时被调用
    :return: :class:`~mywerkzeug.datastructure.HeaderSet`类
    """
    if not value:
        return ds.HeaderSet(None, on_update)
    return ds.HeaderSet(parse_list_header(value), on_update)

def parse_if_range_header(value: str | None) -> ds.IfRange:
    """解析if-range头（可以为etag或date）返回
    :class:`~werkzeug.datastructures.IfRange`对象
    """
    if not value: return ds.IfRange()
    date = parse_date(value)
    if date is not None:
        return ds.IfRange(date=date)
    # 移除弱校验信息
    return ds.IfRange(unquote_etag(value)[0])

@t.overload
def unquote_etag(etag: str) -> tuple[str, bool]: ...

@t.overload
def unquote_etag(etag: None) -> tuple[None, None]: ...

def unquote_etag(
    etag: str | None, 
) -> tuple[str, bool] | tuple[None, None]:
    """移除etag的引号
    
    >>> unquote_etag('W/"bar"')
    ('bar', True)
    >>> unquote_etag('"bar"')
    ('bar', False)
    
    :param etag: 待取消引用的etag标识符.
    :return: (etag, weak)元组
    """
    if not etag: return None, None
    etag = etag.strip()
    weak = False
    if etag.startswith(("W/", "w/")):
        weak = True
        etag = etag[2:]
    if etag[:1] == etag[-1:] == '"':
        etag = etag[1:-1]
    return etag, weak

def parse_etags(value: str | None) -> ds.ETags:
    """解析etag头
    
    :param value: 需要解析的tag头
    :return: :class:`~werkzeug.datastructures.ETags`对象
    """
    if not value: return ds.ETags()
    strong = []
    weak = []
    end = len(value)
    pos = 0
    while pos < end:
        match = _etag_re.match(value, pos)
        if match is None: break
        is_weak, quoted, raw = match.groups()
        if raw == "*":
            return ds.ETags(star_tag=True)
        elif quoted:
            raw = quoted
        if is_weak:
            weak.append(raw)
        else:
            strong.append(raw)
        pos = match.end()
    return ds.ETags(strong, weak)

def parse_date(value: str | None) -> datetime | None:
    """将rfc:`2822`日期解析为一个timezone已知的```datetime.datetime```对象, 解析
    失败则返回None
    
    :func:`email.utils.parsedate_to_datetime`的包装器.解析失败会返回```None```，
    而不是抛出异常，并且总会返回一个timezone已知的datetime对象.若字串不包含timezone
    信息，会默认添加UTC时区。
    """
    if value is None: return None
    
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt

def http_date(
    timestamp: datetime | date | int | float | struct_time | None = None,
) -> str:
    """将日期或时间戳格式化为 rfc:`2822`日期字符串，如
    ``Sun, 06 Nov 1994 08:49:37 GMT``。
    
    这是一个func:`email.utils.format_datetime`的包装器。默认情况下，
    它假设原生的datetime对象是UTC时间，否则会引发异常。

    :param timestamp: 需格式化的日期或时间戳。默认使用当前时间。
    """
    if isinstance(timestamp, date):
        if not isinstance(timestamp, datetime):
            # 假设 plain date 为UTC午夜时刻.
            timestamp = datetime.combine(timestamp, time(), tzinfo=timezone.utc)
        else:
            # 确保 datetime 为timezone 可识别.
            timestamp = _dt_as_utc(timestamp)
        
        return email.utils.format_datetime(timestamp, usegmt=True)
    
    if isinstance(timestamp, struct_time):
        timestamp = mktime(timestamp)
    
    return email.utils.formatdate(timestamp, usegmt=True)

def is_resource_modified(
    environ: WSGIEnvironment,
    etag: str | None = None,
    data: bytes | None = None,
    last_modified: datetime | str | None = None,
    ignore_if_range: bool = True,
) -> bool:
    """条件请求的便捷方法
    
    :param environ: 需要检查的请求中的WSGI环境
    :param etag: 用于比较的响应的 etag
    :param data: 或者，也可以使用响应数据通过 :func:`generate_etag` 自动生成 etag
    :param last_modified: 最后修改时间（可选）。
    :param ignore_if_range: 若为`False`，则会考虑`If-Range`请求头。
    :return: 如果资源被修改，返回True。否则返回False。
    """
    return _sansio_http.is_resource_modified(
        http_range=environ.get("HTTP_RANGE"),

    )

_cookie_no_quote_re = re.compile(r"[\w!#$%&'()*+\-./:<=>?@\[\]^`{|}~]*", re.A)
_cookie_slash_re = re.compile(rb"[\x00-\x19\",;\\\x7f-\xff]", re.A)
_cookie_slash_map = {b'"': b'\\"', b"\\": b"\\\\"}
_cookie_slash_map.update(
    (v.to_bytes(1, "big"), b"\\%03o" % v)
    for v in [*range(0x20), *b",;", *range(0x7F, 256)]
)

def dump_cookie(
    key: str,
    value: str = "",
    max_age: timedelta | int | None = None,
    expires: str | datetime | int | float | None = None,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    httponly: bool = False,
    sync_expires: bool = True,
    max_size: int = 4093,
    samesite: str | None = None,
    partitioned: bool = False,
) -> str:
    """创建一个不带``Set-Cookie``前缀的Set-Cookie header

    返回值通常仅限于ASCII码，因为绝大多数值经过了适当的转义，但是不保证。根据:pep:`3333`
    它会经过latin1进行转换

    如果key包含unicode字符，返回值不是ASCII安全的，这在技术上违反了规范，但实际常有发生，
    强烈建议不使用非ASCII值作为key

    :param max_age: 应为秒数，或者如果cookie应持续到客户端的浏览器session，为`None`
        另外，`timedelta`对象也能被接受
    :param expires: `datetime`对象或者unix时间戳
    :param path: 将cookie限制在给定的路径，默认情况下，它会覆盖整个域
    :param domain: 如果你想设置跨域cookie，例如，``domain="example.com``会设置一个
            ``www.example.com``，``foo.example.com``等域名可读的cookie，否则，cookie
            会只被设置的域名可读
    :param secure: 若为``True``, cookie只对HTTPS可用
    :param httponly: 禁用JavaScript获取cookie，这是cookie标准的扩展，可能不被所有的
        浏览器支持
    :param charset: 字符值的编码
    :param sync_expires: 如果定义了max_age但没有设置expires,自动设置expires
    :param max_size: 最后header超过了这个值会警告，默认4093,应该安全地被大多数浏览器
        <cookie_>支持，设置为0禁用检查
    :param samesite: 限制cookie的scope仅为带有"same-site"的请求
    :param partitioned: 选择将 cookie 存储到分区存储中。这也会将安全设置设为 True。

    .. _`cookie`: http://browsercookielimits.squawky.net/
    """
    if path is not None:
        # safe = https://url.spec.whatwg.org/#url-path-segment-string
        # 此外，对于已经用引号括起来的内容，也需要加上百分比，但不包括分号，
        # 因为它是header语法的一部分。
        path = quote(path, safe="%!$&'()*+,/:=@")
    
    if domain:
        domain = domain.partition(":")[0].lstrip(".").encode("idna").decode("ascii")
    
    if isinstance(max_age, timedelta):
        max_age = int(max_age.total_seconds())

    if expires is not None:
        if not isinstance(expires, str):
            expires = http_date(expires)
    elif max_age is not None and sync_expires:
        expires = http_date(datetime.now(tz=timezone.utc).timestamp() + max_age)

    if samesite is not None: 
        samesite = samesite.title()

        if samesite not in {"Strict", "Lax", "None"}:
            raise ValueError("SameSite must be 'Strict', 'Lax', or 'None'.")
    
    if partitioned:
        secure = True
    
    # 如果有RFC 6265不允许的字符，用引号括起来。使用三个八进制进行转义，与http.cookies匹配
    # 尽管RFC 建议base64
    if not _cookie_no_quote_re.fullmatch(value):
        # 这里使用bytes，因为一个UTF-8字符可以是多个bytes
        value = _cookie_slash_re.sub(
            lambda m: _cookie_slash_map[m.group()], value.encode()
        ).decode("ascii")
        value = f'"{value}"'

    # 将非ASCII key作为乱码发送，其他任何都应为ASCII
    # TODO: 移除编码dance，看起来clients接受UTF-8 keys
    buf = [f"{key.encode().decode('latin1')}={value}"]

    for k, v in (
        ("Domain", domain),
        ("Expires", expires),
        ("Max-Age", max_age),
        ("Secure", secure),
        ("HttpOnly", httponly),
        ("Path", path),
        ("SameSite", samesite),
        ("Partitioned", partitioned),
    ):
        if v is None or v is False: continue

        if v is True:
            buf.append(k)
            continue

        buf.append(f"{k}={v}")
    
    rv = ", ".join(buf)

    # 如果最后cookie大小超出限制警告，如果cookie过大，会被浏览器静默忽略，增加调试难度
    cookie_size = len(rv)

    if max_size and cookie_size > max_size:
        value_size = len(value)
        warnings.warn(
            f"The '{key}' cookie is too large: the value was {value_size} bytes but the"
            f" header required {cookie_size - value_size} extra bytes. The final size"
            f" was {cookie_size} bytes but the limit is {max_size} bytes. Browsers may"
            " silently ignore cookies larger than this.",
            stacklevel=2,
        )
    
    return rv


            
        
        





# 循环依赖
from . import datastructures as ds
from .sansio import http as _sansio_http  # noqa: E402
