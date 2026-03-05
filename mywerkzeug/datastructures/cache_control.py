
import typing as t

from .mixins import ImmutableDictMixin
from .structures import CallbackDict

class _CacheControl(CallbackDict[str, t.Optional[str]]):
    pass

class RequestCacheControl(ImmutableDictMixin[str, t.Optional[str]], _CacheControl): # type: ignore[misc]
    pass

class ResponseCacheControl(_CacheControl):
    pass