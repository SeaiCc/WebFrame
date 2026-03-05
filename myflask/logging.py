
import logging
import sys
import typing as t

from mywerkzeug.local import LocalProxy

from .globals import request

if t.TYPE_CHECKING:
    from .sansio.app import App

@LocalProxy
def wsgi_errors_stream() -> t.TextIO:
    """找到应用的最合适的错误流，如果请求被激活，打印到``wsgi.errors``, 否则使用``sys.stderr``
    
    如果配置自己的:class:`logging.StreamHandler`, 你可能想使用这个流，如果你使用文件
    或字典配置并不能直接导入，可以作为``ext://flask.logging.wsgi_errors_stream``引用
    """
    if request:
        return request.environ["wsgi.errors"]  # type: ignore[no-any-return]
    
    return sys.stderr  


def has_level_handler(logger: logging.Logger) -> bool:
    """检查在logging链中是否有handler处理给定logger的
    :meth:`effective level <~logging.Logger.getEffectiveLevel>`
    """
    level = logger.getEffectiveLevel()
    current = logger
    
    while current:
        if any(handler.level <= level for handler in current.handlers):
            return True
        
        if not current.propagate:
            break

        current = current.parent  # type: ignore

    return False

#: 向:func:`~flask.logging.wsgi_errors_stream`输出日志，格式为
#：``[%(asctime)s] %(levelname)s in %(module)s: %(message)s``
default_handler = logging.StreamHandler(wsgi_errors_stream)  # type: ignore
default_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
)


def create_logger(app: App) -> logging.Logger:
    """如果需要获取Flask的app logger和配置
    
    logger名称为:attr:`app.import_name <flask.Flask.name>`

    当:attr:`~flask.Flask.debug`启用时，设置logger的等级为:data:`logging.DEBUG`（若
    没有设置）

    如果logger的有效级别没有handler，添加一个:class:`~logging.StreamHandler`
    用于:func:`~flask.logging.wsgi_errors_stream`，并设置基本格式。
    """
    logger = logging.getLogger(app.name)

    if app.debug and not logger.level:
        logger.setLevel(logging.DEBUG)

    if not has_level_handler(logger):
        logger.addHandler(default_handler)

    return logger
