
class JSONTag:
    """用于:class:`TaggedJSONSerializer`定义type tag的基类别"""

    #: 用于标记序列化对象的标签。若为空，这个tag在tag时仅用作一个中间步骤
    key: str = ""

    def __init__(self, serializer: TaggedJSONSerializer) -> None:
        """给serializer创建一个tagger"""
        self.serializer = serializer

class TagDict(JSONTag):
    pass

class PassDict(JSONTag):
    pass

class TagTuple(JSONTag):
    pass

class PassList(JSONTag):
    pass

class TagBytes(JSONTag):
    pass

class TagMarkup(JSONTag):
    pass

class TagUUID(JSONTag):
    pass

class TagDateTime(JSONTag):
    pass

class TaggedJSONSerializer:
    """使用tag系统来紧凑地表示非JSON类型的序列化器，传递给:class:`itsdangerous.Serializer`
    作为中间序列化器

    下面额外的类型受支持

    * :class:`dict`
    * :class:`tuple`
    * :class:`bytes`
    * :class:`~markupsafe.Markup`
    * :class:`~uuid.UUID`
    * :class:`~datetime.datetime`
    """

    # 创建serializer时绑定的Tag classes，其他tag可以后续使用:meth:`~register`绑定
    default_tags = [
        TagDict,
        PassDict,
        TagTuple,
        PassList,
        TagBytes,
        TagMarkup,
        TagUUID,
        TagDateTime,
    ]

    def __init__(self) -> None:
        self.tags: dict[str, JSONTag] = {}
        self.order: list[JSONTag] = []

        for cls in self.default_tags:
            self.register(cls)
    
    def register(
        self,
        tag_class: type[JSONTag],
        force: bool = False,
        index: int | None = None,
    ) -> None:
        """使用该serializer注册一个新tag
        
        :param tag_class: 要注册的tag class, 将使用此序列化器实例实例化
        :param force: 重写一个已存在的tag class，如果为false（默认），会抛出:class:`KeyError`
        :param index: 将tag插入标签顺序的索引。当新tag是已存在tag的特殊情况时，会很有用
            如果为``None``（默认），则将tag追加到顺序的末尾。
        
        :raise KeyError: 如果tag key已注册并且``force``为false
        """
        tag = tag_class(self)
        key = tag.key

        if key:
            if not force and key in self.tags:
                raise KeyError(f"Tag key {key} already registered")
            
            self.tags[key] = tag

        if index is None:
            self.order.append(tag)
        else:
            self.order.insert(index, tag)
            