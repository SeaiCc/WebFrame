
from blinker import Namespace

# 此命名空间仅用于Flask本身提供的信号
_signals = Namespace()

appcontext_pushed = _signals.signal("appcontext-pushed")
request_started = _signals.signal("request-started")
request_finished = _signals.signal("request-finished")
request_tearing_down = _signals.signal("request-tearing-down")
got_request_exception = _signals.signal("got-request-exception")
appcontext_tearing_down = _signals.signal("appcontext-tearing-down")