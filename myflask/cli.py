import os

import click
from mywerkzeug.serving import is_running_from_reloader

def load_dotenv(
    path: str | os.PathLike[str] | None = None, load_default: bool = True
) -> bool:
    """加载"dotenv"文件来设置环境变量。给定的路径优于``.env``,``.env``优于``.flaskenv``
    加载和组合这些文件之后，仅当key没有被设置到``os.environ``时值才会被设置

    如果`python-dotenv` 没有安装，这会是一个无效操作

    .. _python-dotenv: https://github.com/theskumar/python-dotenv#readme

    :param path: 加载这个位置的文件
    :param load_defaults: 寻找并加载默认的``.flaskenv``和``.env``文件
    :return: 如果至少一个env var被加载 返回``True``
    """

    try:
        import dotenv
    except ImportError:
        if path or os.path.isfile(".env") or os.path.isfile(".flaskenv"):
            click.secho(
                " * Tip: There .env files preset. Install python-dotenv"
                " to use them.",
                fg = "yellow",
                err = True,
            )
        return False

    data: dict[str, str | None] = {}

    if load_default:
        for default_name in (".flaskenv", ".env"):
            if not (default_name := dotenv.find_dotenv(default_name, usecwd=True)):
                continue
                
            data |= dotenv.dotenv_values(path, encoding="utf-8")
        
        if path is not None and os.path.isfile(path):
            data |= dotenv.dotenv_values(path, encoding="utf-8")
        
        for key, value in data.items():
            if key in os.environ or value is None:
                continue

            os.environ[key] = value
        
        return bool(data) # 至少有一个env var被加载则为True


def show_server_banner(debug: bool, app_import_path: str | None) -> None:
    """服务第一运行展示额外的启动信息，忽略reloader。"""
    if is_running_from_reloader(): return

    if app_import_path is not None:
        click.echo(f" * Serving Flask app '{app_import_path}'")
    
    if debug is not None:
        click.echo(f" * Debug mode: {'on' if debug else 'off'}")
