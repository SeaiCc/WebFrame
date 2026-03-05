
import re
import typing as t
from dataclasses import dataclass
from dataclasses import field

from .converters import ValidationError
from .exceptions import NoMatch
from .exceptions import RequestAliasRedirect
from .exceptions import RequestPath
from .rules import Rule
from .rules import RulePart

class SlashRequired(Exception):
    pass

@dataclass
class State:
    """rule state 的表示
    
    包括与state相关的rules和下一步state的静态和动态转换
    """
    dynamic: list[tuple[RulePart, State]] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    static: dict[str, State] = field(default_factory=dict)

class StateMachineMatcher:
    def __init__(self, merge_slashes: bool) -> None:
        self._root = State()
        self.merge_slashes = merge_slashes

    def add(self, rule: Rule) -> None:
        state = self._root
        for part in rule._parts:
            if part.static:
                state.static.setdefault(part.content, State())
                state = state.static[part.content]
            else:
                for test_part, new_state in state.dynamic:
                    if test_part == part:
                        state = new_state
                        break
                else:
                    new_state = State()
                    state.dynamic.append((part, new_state))
                    state = new_state
        state.rules.append(rule)
    
    def update(self) -> None:
        # 对于每一个状态，动态转移需要按转移的权重排序
        state = self._root

        def _update_state(state: State) -> None:
            state.dynamic.sort(key=lambda entry: entry[0].weight)
            for new_state in state.static.values():
                _update_state(new_state)
            for _, new_state in state.dynamic:
                _update_state(new_state)
        
        _update_state(state)

    def match(
        self, domain: str, path: str, method: str, websocket: bool
    ) -> tuple[Rule, t.MutableMapping[str, t.Any]]:
        # 为了匹配一个rule，我们需要从root state开始并尝试跟随转移，直到找到一个匹配或者
        # 没有转移可以跟随

        have_match_for = set()
        websocket_mismatch = False

        def _match(
            state: State, parts: list[str], values: list[str]
        ) -> tuple[Rule, list[str]] | None:
            # 此方法会递归调用，将头部部分与状态转移匹配
            nonlocal have_match_for, websocket_mismatch

            # 基本情况是所有部分都已经被匹配。因此如果存在一条包含方法和websocket的规则，
            # 则返回该规则并提取动态值
            if parts == []:
                for rule in state.rules:
                    if rule.methods is not None and method not in rule.methods:
                        have_match_for.update(rule.methods)
                    elif rule.websocket != websocket:
                        websocket_mismatch = True
                    else:
                        return rule, values
                
                # 测试是否存在与结尾带有斜杠的路径匹配的匹配项目，若有抛出异常提示可以通过
                # 添加斜杠来匹配
                if "" in state.static:
                    for rule in state.static[""].rules:
                        if websocket == rule.websocket and (
                            rule.methods is None or method in rule.methods
                        ):
                            if rule.strict_slashes:
                                raise SlashRequired()
                            else:
                                return rule, values
                return None

            part = parts[0]
            # 为了匹配这部分，先尝试使用静态匹配
            if part in state.static:
                rv = _match(state.static[part], parts[1:], values)
                if rv is not None: return rv
            # 尝试动态匹配
            for test_part, new_state in state.dynamic:
                target = part
                remaining = parts[1:]
                # 最后一部分表示总是消耗剩余部分的转换，即转换到最后部分
                if test_part.final:
                    target = "/".join(parts)
                    remaining = []
                match = re.compile(test_part.content).match(target)
                if match is not None:
                    if test_part.suffixed:
                        # 如果part_isolationg=False部分有斜线后缀, 从匹配中移除后斜线
                        # 并检查斜线重定向
                        suffix = match.groups()[-1]
                        if suffix == "/":
                            remaining = [""]
                    
                    converter_groups = sorted(
                        match.groupdict(), key=lambda entry: entry[0]
                    )
                    groups = [
                        value
                        for key, value in converter_groups
                        if key[:11] == "__mywerkzeug_"
                    ]
                    rv = _match(new_state, remaining, values + groups)
                    if rv is not None:
                        return rv
            
            # 如果没有匹配,并且只剩下一个斜杠，考虑使用非严格斜杠规则，因为存在最后一个斜杠
            # 部分，这些规则应该可以匹配
            if parts == [""]:
                for rule in state.rules:
                    if rule.strict_slashes:
                        continue
                    if rule.methods is not None and method not in rule.methods:
                        have_match_for.update(rule.methods)
                    elif rule.websocket != websocket:
                        websocket_mismatch = True
                    else:
                        return rule, values

            return None
        
        try:
            rv = _match(self._root, [domain, *path.split("/")], [])
        except SlashRequired:
            raise RequestPath(f"{path}/") from None
        
        if self.merge_slashes and rv is None:
            # 尝试使用带斜线再次匹配
            path = re.sub("/{2,}?", "/", path)
            try:
                rv = _match(self._root, [domain, *path.split("/")], [])
            except SlashRequired:
                raise RequestPath(f"{path}/") from None
            if rv is None or rv[0].merge_slashes is False:
                raise NoMatch(have_match_for, websocket_mismatch)
            else:
                raise RequestPath(f"{path}")
        elif rv is not None:
            rule, values = rv
            
            result = {}
            for name, value in zip(rule._converters.keys(), values):
                try:
                    value = rule._converters[name].to_python(value)
                except ValidationError:
                    raise NoMatch(have_match_for, websocket_mismatch) from None
                result[str(name)] = value
            if rule.defaults:
                print(f"rule.defaults: {rule.defaults}")
                result.update(rule.defaults)
            
            if rule.alias and rule.map.redirect_defaults:
                raise RequestAliasRedirect(result, rule.endpoint)
            return rule, result

        raise NoMatch(have_match_for, websocket_mismatch)

                            
                