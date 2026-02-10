import code
import sys
import typing as t
from contextvars import ContextVar
from types import CodeType

from .repr import dump
from .repr import helper

_ipy: ContextVar[_InteractiveConsole] = ContextVar("mywerkzeug.debug.console.ipy")

class _ConsoleLoader:
    def __init__(self) -> None:
        self._storage: dict[int, str] = {}
    
    def register(self, code: CodeType, source: str) -> None:
        self._storage[id(code)] = source
        # 注册包装方法的code对象
        for var in code.co_consts:
            if isinstance(var, CodeType):
                self._storage[id(var)] = source
    
    def get_source_by_code(self, code: CodeType) -> str | None:
        try:
            return self._storage[id(code)]
        except KeyError:
            return None
        

class _InteractiveConsole(code.InteractiveInterpreter):
    locals: dict[str, t.Any]

    def __init__(self, globals: dict[str, t.Any], locals: dict[str, t.Any]) -> None:
        self.loader = _ConsoleLoader()
        locals = {
            **globals,
            **locals,
            "dump": dump,
            "help": helper,
            "__loader__": self.loader,
        }
        super().__init__(locals)
        original_compile = self.compile

        def compile(source: str, filename: str, symbol: str) -> CodeType:
            code = original_compile(source, filename, symbol)
            if code is not None:
                self.loader.register(code, source)
            return code

        self.compile = compile
        self.more = False
        self.more = False
        self.buffer: list[str] = []
        

class Console:
    """一个交互式控制台"""

    def __init__(
        self,
        globals: dict[str, t.Any] | None = None,
        locals: dict[str, t.Any] | None = None,
    ) -> None:
        if locals is None: locals = {}
        if globals is None: globals = {}    
        self._ipy = _InteractiveConsole(globals, locals)

    def eval(self, code: str) -> str:
        _ipy.set(self._ipy)
        old_sys_stdout = sys.stdout
        try:
            return self._ipy.runsource(code)
        finally:
            sys.stdout = old_sys_stdout


