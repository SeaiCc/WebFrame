
import importlib.util
import os
import sys
import typing as t
from functools import cache

import mywerkzeug.utils

if t.TYPE_CHECKING:
    from .wrappers import Response

def get_debug_flag() -> bool:
    """获取app是否需要启用debug mode，通过:envvar:`FLASK_DEBUG`环境变量指明
    默认为``False``
    """
    val = os.environ.get("FLASK_DEBUG")
    return bool(val and val.lower() not in {"0", "false", "no"})

def get_load_dotenv(default: bool = True) -> bool:
    """用户是否通过设置:envvar:`FLASK_DEBUG`环境变量来禁用加载默认的dotenv文件。
    默认为True，加载文件
    
    :param default: 如果没有设置环境变量应该返回什么
    """
    val = os.environ.get("FLASK_SKIP_DOTENV")

    if not val: return default

    return val.lower() in ("0", "false", "no")        

def send_from_directory(
    directory: os.PathLike[str] | str,
    path: os.PathLike[str] | str,
    **kwargs: t.Any,
) -> Response:
    """使用:func:`send_file`从目录内发送一个文件
    
    .. code-block:: python

        @app.route("/uploads/<path:name>")
        def download_file(name):
            return send_from_directory(
                app.config['UPLOAD_FOLDER'], name, as_attachment=True
            )
    
    这是从目录中提供文件的安全方式，如静态文件或者上传。使用:func:`~mywerkzeug.security.safe_join`
    来确保客户端的路径不是恶意构建的，指向目录之外

    如果最后的路径不指向存在的常规文件，抛出一个404:exec:`~mywerkzeug.exceptions.NotFound`

    :param directory: ``path``必须要定位到的目录,与当前的应用到root路径相关，必须不由客户端
        指定，否则不安全
    :param path: 发送文件的路径，与``directory``
    :param kwargs: 发送给:func:`send_file`的参数
    """
    return mywerkzeug.utils.send_from_directory( # type: ignore[return-value]
        directory, path, **_prepare_send_file_kwargs(**kwargs)
    )

def get_root_path(import_name: str) -> str:
    """找到包的根目录，或者模块的路径。如果找不到，返回当前的工作目录。
    
    切勿与:func:`find_package`返回值混淆
    """
    # 模块被导入并包含文件属性，优先使用
    mod = sys.modules.get(import_name)

    if mod is not None and hasattr(mod, "__file__") and mod.__file__ is not None:
        return os.path.dirname(os.path.abspath(mod.__file__))

    # 接下来尝试: 检查loader
    try:
        spec = importlib.util.find_spec(import_name) # pyright: ignore
        
        if spec is None:
            raise ValueError
    except (ImportError, ValueError):
        loader = None
    else:
        loader = spec.loader
    
    # Loader不存在或索引到一个未加载的主模块或者一个没有路径的主模块(交互式会话)，
    # 则返回当前目录
    if loader is None: return os.getcwd()

    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name) # pyright: ignore
    else:
        # 转而依靠imports
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, "__file__", None)

        # 若获取不到文件路径，可能它是一个命名空间包。在此情况下，选择从这个包包含的第一个
        # 模块选择root path
        if filepath is None:
            raise RuntimeError(
                "No root path can be found for the provided module"
                f" {import_name!r}. This can happen because the module"
                " came from an import hook that does not provide file"
                " name imformation or because it's a namespace package."
                " In this case the root path needs to be explicitly"
                " provided."
            )

    # 文件路径是import_name.py(模块)， 或者__init__.py (包)
    return os.path.dirname(os.path.abspath(filepath)) # type: ignore[no-any-return]
 
@cache
def  _split_blueprint_path(name: str) -> list[str]:
    out: list[str] = [name]

    if "." in name:
        out.extend(_split_blueprint_path(name.rpartition(".")[0]))
    
    return out
