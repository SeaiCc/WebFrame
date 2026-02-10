import collections.abc as cabc

class ETags(cabc.Collection[str]):
    """可用于检查某个 etag 是否存在于 etag 集合中的集合"""

    def __init__(
        self,
        strong_etags: cabc.Iterable[str] | None = None,
        weak_etags: cabc.Iterable[str] | None = None,
        star_tag: bool = False,
    ):
        if not star_tag and strong_etags:
            self._strong = frozenset(strong_etags)
        else:
            self._strong = frozenset()
        
        self._weak = frozenset(weak_etags or ())
        self.star_tag = star_tag

    def is_weak(self, etag: str) -> bool:
        """检查etag是否为弱tag"""
        return etag in self._weak

    def is_strong(self, etag: str) -> bool:
        """检查etag是否为强etag"""
        return etag in self._strong

    def contains_weak(self, etag: str) -> bool:
        """检查etag是否为是强tag和弱tag的一部分"""
        return self.is_weak(etag) or self.contains(etag)

    def contains(self, etag: str) -> bool:
        """检查etag是否为忽略弱tags集合的一部分
        也可以使用``in``运算符。
        """
        if self.star_tag: return True
        return self.is_strong(etag)

    def __contains__(self, etag: str) -> bool:
        return self.contains(etag)