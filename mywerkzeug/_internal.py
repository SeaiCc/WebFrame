from __future__ import annotations

import logging
import sys
import typing as t
from datetime import datetime
from datetime import timezone

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment
    from .wrappers.request import Request
    
_logger: logging.Logger | None = None



def _wsgi_decoding_dance(s: str) -> str:
    return s.encode("latin1").decode(errors="replace")

def _wsgi_encoding_dance(s: str) -> str:
    return s.encode().decode("latin1")

def _get_environ(obj: WSGIEnvironment | Request) -> WSGIEnvironment:
    env = getattr(obj, "environ", obj)
    assert isinstance(env, dict), (
        f"{type(obj).__name__!r} is not a WSGI environment (has to be a dict)"
    )
    return env

def _has_level_handler(logger: logging.Logger) -> bool:
    """检查logging chain中是否有处理给定logger level的handler"""
    level = logger.getEffectiveLevel()
    current = logger
    while current:
        if any(handler.level <= level for handler in current.handlers):
            return True
        if not current.propagate: break
        current = current.parent
    return False

class _ColorStreamHandler(logging.StreamHandler): # type: ignore[type-arg]
    """在Win上，用Colorama包装stream以支持ANSI风格"""

    def __init__(self) -> None:
        try:
            import colorama
        except ImportError:
            stream = None
        else:
            stream = colorama.AnsiToWin32(sys.stderr)
        super().__init__(stream)

def _log(type: str, message: str, *args: t.Any, **kwargs: t.Any) -> None:
    """打印一条日志到'mywerkzeug' logger中
    
    logger第一次被调用时会被创建.默认使用的等级为:data:`logging.INFO`. 如果没有针对
    日志记录器有效级别的处理程序，会增加一个:class:`logging.StreamHandler`
    """
    global _logger

    if _logger is None:
        _logger = logging.getLogger("mywerkzeug")

        if _logger.level == logging.NOTSET:
            _logger.setLevel(logging.INFO)

        if not _has_level_handler(_logger):
            _logger.addHandler(_ColorStreamHandler())

    getattr(_logger, type)(message.rstrip(), *args, **kwargs)

@t.overload
def _dt_as_utc(dt: None) -> None: ...

@t.overload
def _dt_as_utc(dt: datetime) -> datetime: ...

def _dt_as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo == timezone.utc:
        return dt.astimezone(timezone.utc)
    
    return dt
