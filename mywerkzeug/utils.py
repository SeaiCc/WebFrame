
_charset_mimetypes = {
    "application/ecamascript",
    "application/javascript",
    "application/sql",
    "application/xml",
    "application/xml-dtd",
    "application/xml-external-parsed-entity",
}

def get_content_type(mimetype: str, charset: str) -> str:
    """返回一个完整的content type字符串，包含charset。
    
    如果mimetype代表文本，charset参数会被添加，否则mimetype会被原样返回。

    :param mimetype: 要作为content type的mimetype。
    :param charset: 文本mimetype要添加的charset。
    :return: content type

    .. versionchanged:: 0.15
        任何以```+xml```结尾的mimetype都将被添加charset，而不仅仅是
        以```application/```开头的mimetype。已知的文本类型，如
        ```application/javascript```也会被添加charset。
    """
    if (
        mimetype.startswith("text/")
        or mimetype in _charset_mimetypes
        or mimetype.endswith("+xml")
    ):
        mimetype += f"; charset={charset}"
    