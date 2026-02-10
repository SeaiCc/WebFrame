from datetime import datetime

from .._internal import _dt_as_utc
from ..http import generate_etag
from ..http import parse_date
from ..http import parse_etags
from ..http import parse_if_range_header
from ..http import unquote_etag


def is_resource_modified(
    http_range: str | None = None,
    http_if_range: str | None = None,
    http_if_modified_since: str | None = None,
    http_if_none_match: str | None = None,
    http_if_match: str | None = None,
    etag: str | None = None,
    data: bytes | None = None,
    last_modified: datetime | str | None = None,
    ignore_if_range: bool = True,
) -> bool:
    """检查资源是否被修改。
    
    :param http_range: ``Range``HTTP请求头
    :param http_if_range: ``If-Range``HTTP请求头
    :param http_if_modified_since: ``If-Modified-Since``HTTP请求头
    :param http_if_none_match: ``If-None-Match``HTTP请求头
    :param http_if_match: ``If-Match``请求头的值
    :param etag: 用于比较的响应中etag
    :param data: 或者调用func:`generate_etag`用response的data自动生成etag
    :param last_modified: 最后修改时间(可选)
    :param ignore_if_range: 若为`False`，则不忽略``If-Range``请求头。
    :return: 如果资源未被修改，返回True。否则返回False。
    """
    if etag is None and data is not None:
        etag = generate_etag(data)
    elif data is not None:
        raise TypeError("both data and etag given")

    unmodified = False
    if isinstance(last_modified, str):
        last_modified = parse_date(last_modified)
    
    # HTTP 不使用微秒，请将其移除以避免误报。将原始日期时间标记为 UTC。
    if last_modified is not None:
        last_modified = _dt_as_utc(last_modified.replace(microsecond=0))

    # 从请求中解析需要比较的修改时间
    if_range = None
    if not ignore_if_range and http_range is not None:
        # https://tools.ietf.org/html/rfc7233#section-3.2
        # 请求中若不包含Range头，If-Range头也必须被忽略
        if_range = parse_if_range_header(http_if_range)

    if if_range is not None and if_range.date is not None:
        modified_since: datetime | None = if_range.date
    else:
        modified_since = parse_date(http_if_modified_since)
    
    if modified_since and last_modified and last_modified <= modified_since:
        unmodified = True
    
    if etag:
        etag, _ = unquote_etag(etag)
        if if_range is not None and if_range.etag is not None:
            unmodified = parse_etags(if_range.etag).contains(etag)
        else:
            if_none_match = parse_etags(http_if_none_match)
            if if_none_match:
                # https://tools.ietf.org/html/rfc7232#section-3.2
                # "接收方在比较 If-None-Match entity-tags时必须使用弱校验方法"
                unmodified = if_none_match.contains_weak(etag)
            
            # https://tools.ietf.org/html/rfc7232#section-3.1
            # 原服务必须使用强校验方法来比较 If-Match entity-tags
            if_match = parse_etags(http_if_match)
            if if_match:
                unmodified = if_match.is_strong(etag)
    
    return not unmodified

                
        
        



