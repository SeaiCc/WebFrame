
import collections.abc as c
import hashlib
import typing as t
from collections.abc import MutableMapping
from datetime import datetime
from datetime import timezone

from .json.tag import TaggedJSONSerializer

from itsdangerous import BadSignature
from itsdangerous import URLSafeTimedSerializer
from mywerkzeug.datastructures import CallbackDict

if t.TYPE_CHECKING: # pragma: no cover
    import typing_extensions as te

    from .app import Flask
    from .wrappers import Request
    from .wrappers import Response

class SessionMixin(MutableMapping[str, t.Any]):
    """使用session 属性扩展基础字典"""

    @property
    def permanent(self) -> bool:
        """反射了 字典中``'_permanent'`` key"""
        return self.get("_permanent", False)

    #: 一些实现可以检测session的改变，并当发生时设置这个值，mixin默认硬编码为``True``
    modified = True

    #: 某些实现方式能检测到会话数据被读写，并在发生这些操作是设置这个标志。mixin默认
    #: 硬编码为True
    accessed = True

class SecureCookieSession(CallbackDict[str, t.Any], SessionMixin):
    """基于签名cookies的会话基类

    session 后端会设置:attr:`modified`和:attr:`accessed`属性，无法可靠地跟踪会话是否
    为新会话(而非空会话)，因此:attr:`new`仍被硬编码为``False``
    """

    #: 当数据改变时，设置为``True``.仅跟踪session字典本身，若session包含可变数据，
    #: （如nested 字典),则当修改数据时必须手动设置为``True``. Session cookie
    #: 仅会写进response如果这个被设置为True
    modified = False

    #: 当数据读写时，这个会被设置为``True``。被:class:`SecureCookieSessionInterface`
    #: 来添加一个``Vary: Cookie`` header, 这允许缓存代理给不同用户缓存不同的页面
    accessed = False
    
    def __init__(
        self,
        initial: c.Mapping[str, t.Any] | c.Iterable[tuple[str, t.Any]] | None = None,
    ) -> None:
        def on_update(self: te.Self) -> None:
            self.modified = True
            self.accessed = True
        
        super().__init__(initial, on_update)

class NullSession(SecureCookieSession):
    """当sessions不可用时，生成一个好看的错误信息。仍允许对空对话进行只读访问，但是设置会失败"""
    pass

class SessionInterface:
    """替换使用werkzeug的securecookie实现的默认session interface，必须实现基础接口
    唯一需要实现的接口为:meth:`open_session`和:meth:`save_session`,其他都有有用的
    默认实现，不需要改变

    :meth:`open_session`返回的session对象必须提供类似字典的interface加属性和
    :class:`SessionMixin`的方法，建议直接继承字典并添加mixin::

        class Session(dict, SessionMixin):
            pass
    
    如果:meth:`open_session`返回``None``，Flask会调用:meth:`make_null_session`
    来创建一个session, 当此session因为某些依赖不满足不工作时作为一个代替。默认创建的
    :class:`NullSession`会报错，提示密钥未设置

    为了替代application的session interface，你需要做的是赋值
    :attr:`myflask.Flask.session_interface`::

        app = Flask(__name__)
        app.session_interface = MySessionInterface()
    
    相同session的请求可能被同时请求和处理。当实现一个新的session interface时，考虑对
    后端存储的读写操作是否需要同步。每个请求的开启和保存顺序没有保证，它将按照请求开始和结束
    处理的顺序进行
    """

    #: :meth:`make_null_session`在此处查找当空session请求时应创建的类。
    #: 同样:meth:`is_null_session`方法将作为一个类型检查检查此类
    null_session_class = NullSession

    def make_null_session(self, app: Flask) -> NullSession:
        """如果由于配置错误，真正的session支持无法加载，创建一个空session作为代替。
        这主要有助于提升用户体验，因为空session的作用是在没有complaining情况下仍然支持
        查找，但是对于修改操作，会给出有用的错误消息，说明失败的原因。

        默认创建一个:attr:`null_session_class`实例
        """
        return self.null_session_class()

    def is_null_session(self, obj: object) -> bool:
        """检查给定的object是否为null session. Null session 无需保存
         
        检查对象是否为:attr:`null_session_class`的实例
        """
        return isinstance(obj, self.null_session_class)

    def get_cookie_name(self, app: Flask) -> str:
        """session cookie 的名称，使用``app.config["SESSION_COOKIE_NAME"]``"""
        return app.config["SESSION_COOKIE_NAME"] # type: ignore[no-any-return]

    def get_cookie_domain(self, app: Flask) -> str | None:
        """session cookie的``Domain``参数值， 如果没有设置，浏览器仅会发送到其被设置
        的原始域名所在的服务器，否则，还会将其发送到给定值所对应的任意子域名上

        使用:data:`SESSION_COOKIE_DOMAIN`配置
        """
        return app.config["SESSION_COOKIE_DOMAIN"] # type: ignore[no-any-return]

    def get_cookie_path(self, app: Flask) -> str:
        """返回cookie的有效路径，默认实现使用了从``SESSON_COOKIE_PATH``变量中获取的值
        （如果设置），如果为``None``, 使用``APPLICATION_ROOT``或者``/``
        """
        return app.config["SESSION_COOKIE_PATH"] or app.config["APPLICATION_ROOT"] # type: ignore[no-any-return]

    def get_cookie_httponly(sef, app: Flask) -> bool:
        """如果session cookie应为httponly,返回True. 当前仅返回``SESSION_COOKIE_HTTPONLY``
        配置变量的值
        """
        return app.config["SESSION_COOKIE_HTTPONLY"] # type: ignore[no-any-return]

    def get_cookie_secure(self, app: Flask) -> bool:
        """如果cookie应为安全的，返回True， 当前返回``SESSION_COOKIE_SECURE``变量"""
        return app.config["SESSION_COOKIE_SECURE"]    
    
    def get_cookie_samesite(self, app: Flask) -> str | None:
        """如果cookie应该使用``SameSite``属性，返回``'Strict'``或这``'Lax'``
        当前返回:data:`SESSION_COOKIE_SAMESITE`的值
        """
        return app.config["SESSION_COOKIE_SAMESITE"] # type: ignore[no-any-return]

    def get_cookie_partitioned(self, app: Flask) -> bool:
        """如果cookie需要分区，返回True, 默认使用:data:`SESSION_COOKIE_PARTITONED`"""
        return app.config["SESSION_COOKIE_PARTITIONED"] # type: ignore[no-any-return]

    def get_expiration_time(self, app: Flask, session: SessionMixin) -> datetime | None:
        """帮助方法返回session到有效日期，如果session链接到浏览器的session，为``None``
        默认实现返回当前+应用配置中的永久会话生命周期
        """
        if session.permanent:
            return datetime.now(timezone.utc) + app.permanent_session_lifetime
        return None

    def should_set_cookie(self, app: Flask, session: SessionMixin) -> bool:
        """被session后端使用来决定是否应该设置``Set-Cookie``头给此response的session
        cookie，如果session被改变了，cookie被设置。如果session是常驻的，并且
        ``SESSION_REFRESH_EACH_REQUEST``配置是true, cookie总是被设置。

        如果session被删除检查总会被跳过
        """
        return session.modified or (
            session.permanent and app.config["SESSION_REFRESH_EACH_REQUEST"]
        )

    def open_session(self, app: Flask, request: Request) -> SessionMixin | None:
        """每个请求开始时被调用，将request context压栈之后调用，匹配URL之前。
        
        必须返回一个实现了字典的接口和:class:`SessionMixin`接口

        会返回``None``来表示加载失败，而不是直接直接发生错误，在这种情况下，请求上下文
        会会退到使用:meth:`make_null_session`
        """
        raise NotImplementedError()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        """请求最后调用，生成response之后，移除request context之前. 如果
        :meth:`is_null_session`返回``True``跳过"""
        raise NotImplementedError()

session_json_serializer = TaggedJSONSerializer()

def _lazy_sha1(string: bytes = b"") -> t.Any:
    """直到运行不要访问``hashlib.sha1``。FIPS构建可能不包含SHA-1,这种情况，在开发者
    能配置其他东西前作为默认import 和使用会失败
    """
    return hashlib.sha1(string)

class SecureCookieSessionInterface(SessionInterface):
    """默认session interface通过:mod:`itsdangerous`模块将session存储在签名cookies中"""

    #: 用于对基于session的cookie进行签名的密钥上应添加的salt
    salt = "cookie-session"
    #: 用于签名的hash函数，默认为sha1
    digest_method = staticmethod(_lazy_sha1)
    #: itsdangerous支持的key派生名称,默认是hmac
    key_derivation = "hmac"

    #: 用于pyload的python序列化器，默认情况下，是一个紧凑的JSON派生serializer，支持一些
    #: 额外的python类型，如datetime对象或者元组
    serializer = session_json_serializer
    session_class = SecureCookieSession

    def get_signing_serializer(self, app: Flask) -> URLSafeTimedSerializer | None:
        if not app.secret_key: return None

        keys: list[str | bytes] = []

        if fallbacks := app.config["SECRET_KEY_FALLBACKS"]:
            keys.extend(fallbacks)

        keys.append(app.secret_key) # itsdangerous 期待当前key位于顶部
        return URLSafeTimedSerializer(
            keys, # type: ignore[arg-type]
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs={
                "key_derivation": self.key_derivation,
                "digest_method": self.digest_method,
            },
        )

    def open_session(self, app: Flask, request: Request) -> SecureCookieSession | None:
        s = self.get_signing_serializer(app)
        if s is None: return None
        val = request.cookies.get(self.get_cookie_name(app))
        if not val: return self.session_class()
        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            return self.session_class()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        secure = self.get_cookie_secure(app)
        partitioned = self.get_cookie_partitioned(app)
        samesite = self.get_cookie_samesite(app)
        httponly = self.get_cookie_httponly(app)

        # 添加一个"Vary: Cookie" header如果session 可用
        if session.accessed:
            response.vary.add("Cookie")

        # 如果被设置为空，直接移除
        # 如果session是空，不设置cookie 返回
        if not session:
            if session.modified:
                response.delete_cookie(
                    name,
                    domain=domain,
                    path=path,
                    secure=secure,
                    partitioned=partitioned,
                    samesite=samesite,
                    httponly=httponly,
                )
                response.vary.add("Cookie")
            
            return
        
        if not self.should_set_cookie(app, session): return

        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session)) # type: ignore[union-attr]
        response.set_cookie(
            name,
            val,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            partitioned=partitioned,
            samesite=samesite,
        )
        response.vary.add("Cookie")

