
from datetime import datetime

class IfRange:
    """表示解析格式的`If-Range`头的简单对象，要么既不包含 etag 也不包含日期，
    要么只包含其中之一，但绝不会同时包含两者。
    """

    def __init__(self, etag: str | None = None, date: datetime | None = None):
        # 已解析且未加引号的 etag. Ranges总是操作强etags 因此不需要若信息
        self.etag = etag
        # 解析格式的date或者`None`
        self.date = date
