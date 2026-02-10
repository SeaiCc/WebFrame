
import getpass
import hashlib
import os
import re
import sys
import typing as t
import uuid
from itertools import chain
from multiprocessing import Value

from .._internal import _log
from ..security import gen_salt
from .console import Console
from .tbtools import DebugFrameSummary

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication

_machine_id: str | bytes | None = None
def get_machine_id() -> str | bytes | None:
    global _machine_id
    if _machine_id is not None: return _machine_id
    
    def _generate() -> str | bytes | None:
        linux = b""

        # machine-id 每次启动保持不变，boot_id不然
        for filename in "/etc/machine-id", "/proc/sys/kernel/random/boot_id":
            try:
                with open(filename, "rb") as f:
                    value = f.readline().strip()
            except OSError:
                continue
            if value:
                linux += value
                break
        # 容器共享相同的machine id，并增加了一些cgroup信息，在容器外也可用，但是在不同的
        # boots之间应保持稳定
        try:
            with open("/proc/self/cgroup", "rb") as f:
                linux += f.readline().strip().rpartition(b"/")[2]
        except OSError:
            pass
        if linux: return linux
        # 在OS X上，使用ioreg来获取计算机的序列号
        try:
            # 子进程可能不可用，如Google App Engine
            # https://github.com/pallets/werkzeug/issues/925
            from subprocess import PIPE
            from subprocess import Popen
            dump = Popen(
                ["ioreg", "-c", "IOPlatformExpertDevice", "-d", "2"], stdout=PIPE
            ).communicate()[0]
            match = re.search(b'"serial-number" = <([^>])', dump)
            
            if match is not None: return match.group(1)
        except (OSError, ImportError):
            pass

        # 在 Windows上，使用winreg 来获取计算机的machine guid
        if sys.platform == "win32":
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    "SOFTWARE\\Microsoft\\Cryptography",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                ) as rk:
                    guid: str | bytes
                    guid_type: int
                    guid, guid_type = winreg.QueryValueEx(rk, "MachineGuid")

                    if guid_type == winreg.REG_SZ:
                        return guid.encode()
                    
                    return guid
            except OSError:
                pass

        return None    
    
    _machine_id = _generate()
    return _machine_id

class _ConsoleFrame:
    """
        一个可以在frame的namespace中执行代码的frame类
    """
    def __init__(self, namespace: dict[str, t.Any]):
        self.console = Console(namespace)
        self.id = 0

    def eval(self, code: str) -> t.Any:
        return self.console.eval(code)

def get_pin_and_cookie_name(
    app: WSGIApplication,
) -> tuple[str, str] | tuple[None, None]:
    """给定一个应用对象，返回一个semi-stable的9位数字pin码和一个随机key.
    pin码和密钥重启后应保持稳定，以免调试变的异常困难。若PIN码被强制禁用则返回`None`
    
    返回元组第二项是用于记忆的cookie名
    """
    pin = os.environ.get("MYWERKZEUG_DEBUG_PIN")
    rv = None
    num = None

    # Pin 被明确禁用
    if pin == "off": return None, None

    # Pin被显示提供
    if pin is not None and pin.replace("-", "").isdecimal():
        # 若pin中包含分隔符，则直接返回
        if "-" in pin:
            rv = pin
        else:
            num = pin
    modname = getattr(app, "__module__", t.cast(object, app).__class__.__module__)
    username: str | None
    
    try:
        # getuser在pwd模块被导入，在Google App Engine上不存在这种情况。
        # 如果UID不存在username也会引起KeyError, 如在Docker
        username = getpass.getuser()
    # Python >= 3.13 只会抛出OSError
    except (ImportError, KeyError, OSError):
        username = None
    
    mod = sys.modules.get(modname)

    # 此信息仅用于使得机器的cookie唯一，而非座位一个安全特性
    probably_public_bits = [
        username,
        modname,
        getattr(mod, "__name__", type(app).__name__),
        getattr(mod, "__file__", None),
    ]

    # 这里的信息用于是的攻击者难以猜测cookie名，它们不太可能包含在未经身份验证的调试页面中的
    # 任何位置。
    private_bits = [str(uuid.getnode()), get_machine_id()]

    h = hashlib.sha1()
    for bit in chain(probably_public_bits, private_bits):
        if not bit: continue
        if isinstance(bit, str):
            bit = bit.encode()
        h.update(bit)
    h.update(b"cookiesalt")

    cookie_name = f"__wzd{h.hexdigest()[:20]}"

    #如果我们需要生成一个pin码，我们可以稍微增加一些盐值，防止得到相同的值并生成9位数字
    if num is None:
        h.update(b"pinsalt")
        num = f"{int(h.hexdigest(), 16):09d}"[:9]
    
    #如果我们还没有获得结果，格式化pin码为数字组以方便记忆
    if rv is None:
        for group_size in 5, 4, 3:
            if len(num) % group_size == 0:
                rv = "-".join(
                    num[x : x + group_size].rjust(group_size, "0")
                    for x in range(0, len(num), group_size)
                )
                break
            else:
                rv = num
    return rv, cookie_name

class DebuggedApplication:
    """确保调试器支持给到的应用::

        from werkzeug.debug import DebuggedApplication
        from myapp import app
        app = DebuggedApplication(app, evalex=True)

    ``evalex``参数允许在traceback的任意frame中对表达式求值。主要工作是保存每一帧
    及其局部状态。某些状态，如全局上下文，默认不能被frame保存。当``evalex``启用时，
    ``environ["mywerkzeug.debug.preserve_context"]``会作为一个可调用对象，接收
    一个上下文管理器，并且可以被多次调用。每个上下文管理器都会在执行frame中的代码之前
    entered，然后再次exited，以便它们可以为每个调用执行设置和清理工作。

    :param app: 需要被调试的WSGI应用。
    :param evalex: 启用异常评估功能（交互式调试）。这需要一台non-forking服务器
    :param request_key: 环境中key指向的请求对象。当前版本中忽略此参数
    :param console_path: 通用控制台的URL
    :param console_init_func: 在启动通用控制台之前需要被执行的方法,返回值被作为
                              初始化命名空间
    :param show_hidden_frames: 默认隐藏的traceback frame被忽略，通过设置此参数
                               为`True`来显示他们
    :param pin_security: 用于禁用基于密码的安全系统
    :param pin_logging: 允许pin系统的日志
    """

    _pin: str
    _pin_cookit: str

    def __init__(
        self, 
        app: WSGIApplication,
        evalex: bool = False,
        request_key: str = "mywerkzeug.request",
        console_path: str = "/console",
        console_init_func: t.Callable[[], dict[str, t.Any]] | None = None,
        show_hidden_frames: bool = False,
        pin_security: bool = True,
        pin_logging: bool = False,
    ) -> None:
        if not console_init_func: 
            console_init_func = None
        self.app = app
        self.evalex = evalex
        self.frame: dict[int, DebugFrameSummary | _ConsoleFrame] = {}
        self.frame_contexts: dict[int, list[t.ContextManager[None]]] = {}
        self.request_key = request_key
        self.console_path = console_path
        self.console_init_func = console_init_func
        self.show_hidden_frames = show_hidden_frames
        self.secret = gen_salt(20)
        self._failed_pin_auth = Value("B")

        self.pin_logging = pin_logging
        if pin_security:
            # 在标准输出端打印出调试器的pin
            if os.environ.get("MYWERKZEUG_RUN_MAIN") == "true" and pin_logging:
                _log("warning", " * Debugger is active!")
                if self.pin is None:
                    _log("warning", " * Debugger PIN disabled. DEBUGGER UNSECURED!")
                else:
                    _log("info", " * Debugger PIN: %s", self.pin)
        else:
            self.pin = None

        self.trusted_host: list[str] = [".localhost", "127.0.0.1"]
        """允许向调试器发出请求的域名列表, 头部的.允许所有子域名。默认只允许``".localhost"``
        """

    @property
    def pin(self) -> str | None:
        if not hasattr(self, "_pin"):
            pin_cookie = get_pin_and_cookie_name(self.app)
            self._pin, self._pin_cookie = pin_cookie # type: ignore
        return self._pin