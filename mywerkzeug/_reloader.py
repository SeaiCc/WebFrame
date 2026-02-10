import fnmatch
import os
import sys
import subprocess
import threading
import typing as t
from itertools import chain

from ._internal import _log

# imports找到的各种系统前缀，base value在虚拟机中会不同。所有的reloader会忽略base paths
# （通常是系统安装路径）stat reloader不会扫描虚拟环境路径，只会包括早已倒入的modules
_ignore_always = tuple({sys.base_prefix, sys.base_exec_prefix})
prefix = {*_ignore_always, sys.prefix, sys.exec_prefix}

if hasattr(sys, "real_prefix"):
    # virtualenv < 20
    prefix.add(sys.real_prefix)

_stat_ignore_scan = tuple(prefix)
del prefix
# 忽略__pycache__目录，因为每次修改都会生成新的pyc文件（或者initial pyc文件）。
# 忽略常见的版本控制内部机制。忽略常见的工具缓存。
_ignore_common_dirs = {
    "__pycache__",
    ".git",
    ".hg",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
}

def _iter_module_paths() -> t.Iterator[str]:
    """找到与导入modules相关的文件系统路径"""
    # 列表用于防止app在更新过程中修改值
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)

        if name is None or name.endswith(_ignore_always):
            continue

        while not os.path.isfile(name):
            # Zip file，找到不带模块路径的base文件。
            old = name
            name = os.path.dirname(name)

            if name == old: # 如果所有目录都以某种方式存在，则跳过
                break
        else:
            yield name

def _remove_by_pattern(paths: set[str], exclude_patterns: set[str]) -> None:
    for pattern in exclude_patterns:
        paths.difference_update(fnmatch.filter(paths, pattern))

def _find_stat_paths(
    extra_files: set[str], exclude_patterns: set[str]
) -> t.Iterator[str]:
    """找到stat reloader需要监控的路径。返回import module文件，非系统路径下的
    python文件，在extra目录下的额外的文件和python文件也会被扫描
    
    为了效率系统路径必须被排除。非系统路径，如项目根目录或者``sys.path.insert``都
    应作为用户关注的路径
    """
    paths = set()

    for path in chain(list(sys.path), extra_files):
        path = os.path.abspath(path)
        if os.path.isfile(path):
            # sys.path下的zip文件或extra文件
            paths.add(path)
            continue
        parent_has_py = {os.path.dirname(path): True}
        for root, dirs, files in os.walk(path):
            if (
                root.startswith(_stat_ignore_scan)
                or os.path.basename(root) in _ignore_common_dirs
            ):
                dirs.clear()
                continue
            
            has_py = False
            for name in files:
                if name.endswith(".py", ".pyc"):
                    has_py = True
                    paths.add(os.path.join(root, name))
            # 可选：如果目录和父级目录都不包含python文件，则停止扫描
            if not (has_py or parent_has_py[os.path.dirname(root)]):
                dirs.clear()
                continue
            parent_has_py[root] = has_py
    
    paths.update(_iter_module_paths())
    _remove_by_pattern(paths, exclude_patterns)
    return paths

def _get_args_for_reloading() -> list[str]:
    """决定脚本如何执行，并返回需要的参数使其在新进程中执行"""
    if sys.version_info >= (3, 10):
        # 3.10版本增加了sys.orig_argv, 包含了用于invoke python的精确 args
        # 为了准确 仍使用sys.executable替换argv[0]
        return [sys.executable, *sys.orig_argv[1:]]
    
    rv = [sys.executable]
    py_script = sys.argv[0]
    args = sys.argv[1:]
    # 需要看main模块来决定它如何执行
    __main__ = sys.modules["__main__"]
    
    # __package__ 展示了python如何被调用，若setuptools脚本被作为一个egg安装可能不存在
    # windows上，使用pip创建的entry points可能会被错误地设置
    if getattr(__main__, "__package__", None) is None or (
        os.name == "nt"
        and __main__.__package__ == ""
        and not os.path.exists(py_script)
        and os.path.exists(f"{py_script}.exe")
    ):
        # 直接执行脚本 如 python app.py
        py_script = os.path.abspath(py_script)
        if os.name == "nt":
            # Windows entry points 含有 ".exe" 后缀 应该被直接调用
            if not os.path.exists(py_script) and os.path.exists(f"{py_script}.exe"):
                py_script += ".exe"
            if (
                os.path.splitext(sys.executable)[1] == ".exe"
                and os.path.splitext(py_scrpt)[1] == ".exe"
            ):
                rv.pop(0)
        rv.append(py_script)
    else:
        # 作为模块执行 如 python -m mywerkzeug.serving
        if os.path.isfile(py_script):
            # 将"-m script"重写为"/path/to/script.py"
            py_module = t.cast(str, __main__.__package__)
            name = os.path.splitext(os.path.basename(py_script))[0]
            if name != "__main__":
                py_module += f".{name}"
        else:
            # pydevd debugger错误的将"-m script"重写为 "script"
            py_module = py_script
        rv.extend(("-m", py_module.lstrip(".")))

    rv.extend(args)
    return rv    

class ReloaderLoop:
    name = ""

    def __init__(
        self,
        extra_files: t.Iterable[str] | None = None,
        exclude_patterns: t.Iterable[str] | None = None,
        interval: int | float = 1,
    ) -> None:
        self.extra_files: set[str] = {os.path.abspath(x) for x in extra_files or ()}
        self.exclude_patterns: set[str] = set(exclude_patterns or ())
        self.interval = interval

    def __enter__(self) -> ReloaderLoop:
        """进行任何设置，然后运行监视的一个步骤来填充初始文件系统状态。"""
        self.run_step()
        return self
    
    def __exit__(self, exc_type, exc_vla, exc_tb): #type: ignore
        """清理与reloader相关的任意资源"""
        pass

    def restart_with_reloader(self) -> int:
        """生成一个与当前参数相同的新的python解释器， 但运行在reloader线程"""
        while True:
            _log("info", f" * Restarting with {self.name} ")
            args = _get_args_for_reloading()
            new_environ = os.environ.copy()
            new_environ["MYWERKZEUG_RUN_MAIN"] = "true"
            exit_code = subprocess.call(args, env=new_environ, close_fds=False)

            if exit_code != 3: return exit_code

    def trigger_reload(self, filename: str) -> None:
        self.log_reload(filename)
        sys.exit(3)

    def log_reload(self, filename: str | bytes) -> None:
        filename = os.path.abspath(filename)
        _log("info", f" * Detected change in {filename!r}, reloading...")

class StatReloaderLoop(ReloaderLoop):
    name = "stat"

    def __enter__(self) -> ReloaderLoop:
        self.mitimes: dict[str, float] = {}
        return super().__enter__()

    def run_step(self) -> None:
        for name in _find_stat_paths(self.extra_files, self.exclude_patterns):
            try:
                mtime = os.stat(name).st_mtime
            except OSError:
                continue
            old_time = self.mitimes.get(name)
            if old_time is None:
                self.mitimes[name] = mtime
                continue
            if mtime > old_time:
                self.trigger_reload(name)

class WatchdogReloaderLoop(ReloaderLoop):
    """暂时不考虑引入额外的依赖包"""
    # def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
    #     from watchdog.events import EVENT_TYPE_CLOSED
    #     from watchdog.events import EVENT_TYPE_CREATED
    #     from watchdog.events import EVENT_TYPE_DELETED
    #     from watchdog.events import EVENT_TYPE_MODIFIED
    #     from watchdog.events import EVENT_TYPE_MOVED
    #     from watchdog.events import FileModifiedEvent
    #     from watchdog.events import PatternMatchingEventHandler
    #     from watchdog.observers import Observer
    pass


reloader_loops: dict[str, type[ReloaderLoop]] = {
    "stat": StatReloaderLoop,
    "watchdog": WatchdogReloaderLoop,
}

try:
    __import__("watchdog.observers")
except ImportError:
    reloader_loops["auto"] = reloader_loops["stat"]
else:
    reloader_loops["auto"] = reloader_loops["watchdog"]

def ensure_echo_on() -> None:
    """确保echo mode启用。像PDB等一些工具会关闭它，可能会导致重载之后等可用性问题"""
    if sys.stdin is None or not sys.stdin.isatty(): return
    try:
        import termios
    except ImportError:
        return
    attributes = termios.tcgetattr(sys.stdin)
    if not attributes[3] & termios.ECHO:
        attributes[3] |= termios.ECHO
        termios.tcsetattr(sys.stdin, termios.TCSANOW, attributes)

def run_with_reloader(
    main_func: t.Callable[[], None],
    extra_files: t.Iterable[str] | None = None,
    exclude_patterns: t.Iterable[str] | None = None,
    interval: int | float = 1,
    reloader_type: str = "auto",
) -> None:
    """在独立的python解释器中运行给定的方法"""
    import signal

    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
    reloader = reloader_loops[reloader_type](
        extra_files=extra_files, exclude_patterns=exclude_patterns, interval=interval
    )
    try:
        if os.environ.get("MYWERKZEUG_RUN_MAIN") == "true":
            ensure_echo_on()
            t = threading.Thread(target=main_func, args=())
            t.daemon = True
            # 在reloader enter时设置初始化状态，然后启动app线程和reloader的loop
            with reloader:
                t.start()
                reloader.run()
        else:
            sys.exit(reloader.restart_with_reloader())
    except KeyboardInterrupt:
        pass