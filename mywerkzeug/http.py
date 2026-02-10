import email.utils
import re
import typing as t
from datetime import date
from datetime import datetime
from hashlib import sha1
import time
from datetime import timezone
from time import struct_time
from time import mktime

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

def generate_etag(data: bytes | None = None) -> str:
    """根据data生成一个ETag值"""
    return sha1(data).hexdigest()

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

# 循环依赖
from . import datastructures as ds
from .sansio import http as _sansio_http  # noqa: E402
