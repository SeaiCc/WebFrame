import sys
import traceback
import typing as t
import itertools

def _process_traceback(
    exc: BaseException,
    te: traceback.TracebackException | None = None,
    *,
    skip: int = 0,
    hide: bool = True,
) -> traceback.TracebackException:
    if te is None:
        te = traceback.TracebackException.from_exception(exc, lookup_lines=False)
    
    # 以与 StackSummary 相同的方式获取帧。提取的目的是为了将每一帧与 FrameSummary 
    # 进行匹配以进行增强。
    frame_gen = traceback.walk_tb(exc.__traceback__)
    limit = getattr(sys, "tracebacklimit", None)

    if limit is not None:
        if limit < 0: limit = 0

        frame_gen = itertools.islice(frame_gen, limit)
    
    if skip:
        frame_gen = itertools.islice(frame_gen, skip, None)
        del te.stack[:skip]

    new_stack: list[DebugFrameSummary] = []
    hidden = False

    # 使用生成的FrameSummary来匹配每一帧，使用 Paste的__traceback__ rules来隐藏
    # 帧。使用DebugFrameSummary替换所有可见的FrameSummary.
    for (f, _), fs in zip(frame_gen, te.stack):
        if hide:
            hide_value = f.f_locals.get("__traceback__", False)

            if hide_value in {"before", "before_and_this"}:
                new_stack = []
                hidden = False

                if hide_value == "before_and_this":
                    continue
            elif hide_value in {"reset", "reset_and_this"}:
                hidden = False
                if hide_value == "reset_and_this":
                    continue
            elif hide_value in {"after", "after_and_this"}:
                hidden = True
                if hide_value == "after_and_this":
                    continue
            elif hide_value or hidden:
                continue
        
        frame_args: dict[str, t.Any] = {
            "filename": fs.filename,
            "lineno": fs.lineno,
            "name": fs.name,
            "locals": f.f_locals,
            "globals": f.f_globals,
        }

        if sys.version_info >= (3, 11):
            frame_args["colno"] = fs.colno
            frame_args["end_colno"] = fs.end_colno
        
        new_stack.append(DebugFrameSummary(**frame_args))

    # codeop模块用于从可交互的debugger中编译代码，从traceback底部开始隐藏所有codeop帧
    while new_stack:
        module = new_stack[0].global_ns.get("__name__")
        if module is None:
            module = new_stack[0].local_ns.get("__name__")
        if module == "codeop":
            del new_stack[0]
        else:
            break
    
    te.stack[:] = new_stack

    if te.__context__:
        context_exc = t.cast(BaseException, exc.__context__)
        te.__context__ = _process_traceback(context_exc, te.__context__, hide=hide)
    
    if te.__cause__:
        cause_exc = t.cast(BaseException, exc.__cause__)
        te.__cause__ = _process_traceback(cause_exc, te.__cause__, hide=hide)
    return te


class DebugTraceback:
    __slots__ = ("_te", "_cache_all_tracebacks", "_cache_all_frames")

    def __init__(
        self, 
        exc: BaseException,
        te: traceback.TracebackException | None = None,
        *,
        skip: int = 0,
        hide: bool = True,
    ) -> None:
        self._te = _process_traceback(exc, te, skip=skip, hide=hide)

    def __str__(self) -> str:
        return f"<{type(self).__name__} {self._te}>"

    def render_traceback_text(self) -> str:
        return "".join(self._te.format())

class DebugFrameSummary(traceback.FrameSummary):
    """一个可以在frame的namespace中执行代码的:class:`traceback.FrameSummary`类"""

    __slots__ = (
        "local_ns",
        "global_ns",
        "_cache_info",
        "_cache_is_library",
        "_cache_console",
    )

    def __init__(
        self,
        *,
        locals: dict[str, t.Any],
        globals: dict[str, t.Any],
        **kwargs: t.Any,
    ) -> None:
        super().__init__(locals=None, **kwargs)
        self.local_ns = locals
        self.global_ns = globals

