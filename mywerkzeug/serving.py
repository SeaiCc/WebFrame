import errno
import io
import os
import selectors
import socket
import sys
import typing as t
from datetime import datetime as dt
from datetime import timedelta
from datetime import timezone
from urllib.parse import unquote
from urllib.parse import urlsplit

from ._internal import _log
from ._internal import _wsgi_encoding_dance
from .exceptions import InternalServerError
from myhttp.http_server import BaseHTTPRequestHandler
from myhttp.http_server import HTTPServer
from mysocket import mysocketserver

try:
    import ssl
    connection_dropped_errors: tuple[type[Exception], ...] = (
        ConnectionError,
        socket.timeout,
        ConnectionResetError,
    )
except ImportError:
    class _SslDummy:
        def __getattr__(self, name: str) -> t.Any:
            raise RuntimeError( #noqa: B904
                "SSL is unavailable because this Python runtime was not"    
            )

_log_add_style = True

can_fork = hasattr(os, "fork")

if can_fork:
    ForkingMixIn = mysocketserver.ForkingMixIn
else:
    class ForkingMixIn: # type: ignore
        pass

try:
    af_unix = socket.AF_UNIX
except AttributeError:
    af_unix = None

LISTEN_QUEUE = 128

_TSSLContextArg = t.Optional[
    t.Union["ssl.SSLContext", tuple[str, t.Optional[str]], t.Literal["adhoc"]]
]

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication
    from _typeshed.wsgi import WSGIEnvironment
    from cryptography.hazmat.primitives.asymmetric.rsa import (
        RSAPrivateKeyWithSerialization,
    )
    from cryptography.x509 import Certificate

class DechunkedInput(io.RawIOBase):
    """一个用于处理 Transfer-Encoding 'chunked'的stream"""
    def __init__(self, rfile: t.IO[bytes]) -> None:
        self._rfile = rfile
        self._done = False
        self._len = 0

class WSGIRequestHandler(BaseHTTPRequestHandler):
    """一个实现请求分发的request handler类"""
    server: BaseWSGIServer

    @property
    def server_version(self) -> str: # type: ignore
        return self.server._server_version

    def make_environ(self) -> WSGIEnvironment:
        request_url = urlsplit(self.path)
        url_scheme = "http" if self.server.ssl_context is None else "https"

        if not self.client_address:
            self.client_address = ("<local>", 0)
        elif isinstance(self.client_address, str):
            self.client_address = (self.client_address, 0)
        # 若路径中没有scheme，并且路径以两个斜线开始，第一个片段可能被错误地解析为 
        # netloc，请将其重新添加到路径前面。
        if not request_url.scheme and request_url.netloc:
            path_info = f"/{request_url.netloc}{request_url.path}"
        else:
            path_info = request_url.path
        path_info = unquote(path_info)

        environ: WSGIEnvironment = {
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": url_scheme,
            "wsgi.input": self.rfile,
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": self.server.multithread,
            "wsgi.multiprocess": self.server.multiprocess,
            "wsgi.run_once": False,
            "wsgi.socket": self.connection,
            "SEVER_SOFTWARE": self.server_version,
            "REQUEST_METHOD": self.command,
            "SCRIPT_NAME": "",
            "PATH_INFO": _wsgi_encoding_dance(path_info),
            "QUERY_STRING": _wsgi_encoding_dance(request_url.query),
            # Non-standard, added by mod_wsgi, uWSGI
            "REQUEST_URI": _wsgi_encoding_dance(self.path),
            # Non-standard, added by gunicorn
            "RAW_URI": _wsgi_encoding_dance(self.path),
            "REMOTE_ADDR": self.address_string(),
            "REMOTE_PORT": self.port_integer(),
            "SERVER_NAME": self.server.server_address[0],
            "SERVER_PORT": str(self.server.server_address[1]),
            "SERVER_PROTOCOL": self.request_version,
        }

        for key, value in self.headers.items():
            if "_" in key: continue

            key = key.upper().replace("-", "_")
            value = value.replace("\r\n", "")
            if key not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
                key = f"HTTP_{key}"
                if key in environ:
                    value = f"{environ[key]},{value}"
            environ[key] = value
        
        if environ.get("HTTP_TRANSFER_ENCODING", "").strip().lower() == "chunked":
            environ["wsgi.input_terminated"] = True
            environ["wsgi.input"] = DechunkedInput(environ["wsgi.input"])
        # 根据 RFC 2616，如果 URL 是绝对路径，则使用该路径作为主机名。
        # 使用“has a scheme”来表示绝对 URL。
        if request_url.scheme and request_url.netloc:
            environ["HTTP_HOST"] = request_url.netloc

        try:
            # binary_form=False给出了更友好的信息，但是和Nginx和Apache的返回可能不兼容
            peer_cert = self.connection.getpeercert(binary_form=True)
            if peer_cert is not None:
                # Nginx 和 Apache使用PEM格式
                environ["SSL_CLIENT_CERT"] = ssl.DER_cert_to_PEM_cert(peer_cert)
        except AttributeError:
            # 不使用TLS， socket 没有 getpeercert 方法
            pass

        return environ

    def run_wsgi(self) -> None:
        if self.headers.get("Expect", "").lower().strip() == "100-continue":
            self.wfile.write(b" HTTP/1.1 100 Continue\r\n\r\n")

        self.environ = environ = self.make_environ()
        status_set: str | None = None
        headers_set: list[tuple[str, str]] | None = None
        status_sent: str | None = None
        headers_sent: list[tuple[str, str]] | None = None
        chunk_response: bool = False

        def write(data: bytes) -> None:
            nonlocal status_sent, headers_sent, chunk_response
            assert status_set is not None, "write() before start_response"
            assert headers_set is not None, "write() before start_response"
            if status_sent is None:
                status_sent = status_set
                headers_sent = headers_set
                try:
                    code_str, msg = status_sent.split(None, 1)
                except ValueError:
                    code_str, msg = status_sent, ""
                code = int(code_str)
                self.send_response(code, msg)
                header_keys = set()
                for key, value in headers_sent:
                    self.send_header(key, value)
                    header_keys.add(key.lower())

                # 如果没有内容长度，使用块传输编码。不要使用1xx和204响应。
                # 304 响应和 HEAD 请求也被排除在外，这是一种更保守的行为，
                # 与其他代码部分保持一致。
                # https://httpwg.org/specs/rfc7230.html#rfc.section.3.3.1
                if (
                    not (
                        "content-length" in header_keys
                        or environ["REQUEST_METHOD"] == "HEAD"
                        or (100 <= code < 200)
                        or code in {204, 304}
                    )
                    and self.protocal_version >= "HTTP/1.1"
                ): 
                    chunk_response = True
                    self.send_header("Transfer-Encoding", "chunked")
                
                # 总是关闭连接。禁用HTTP/1.1的keep-alive连接，Python 的 http.server 
                # 无法很好地处理它们，因为它不知道如何在下一个请求行之前清空流。
                self.send_header("Connection", "close")
                self.end_headers()
            assert isinstance(data, bytes), "applications must write bytes"

            if data:
                if chunk_response:
                    self.wfile.write(hex(len(data))[2:].encode())
                    self.wfile.write(b"\r\n")
                self.wfile.write(data)
                if chunk_response:
                    self.wfile.write(b"\r\n")
            self.wfile.flush()
        
        def start_response(status, headers, exc_info=None): # type: ignore
            nonlocal status_set, headers_set
            if exc_info:
                try:
                    if headers_sent:
                        raise exc_info[1].with_traceback(exc_info[2])
                finally:
                    exc_info = None
            elif headers_set:
                raise AssertionError("headers already sent")
            status_set = status
            headers_set = headers
            return write
        
        def execute(app: WSGIApplication) -> None:
            application_iter = app(environ, start_response)
            try:
                for data in application_iter:
                    write(data)
                if not headers_sent:
                    write(b"")
                if chunk_response:
                    self.wfile.write(b"0\r\n\r\n")
            finally:
                # 检查read socket中是否还有剩余数据，并将其丢弃。这将读取超过 
                # request.max_content_length 的数据，但可以让客户端看到 413 响应，
                # 而不是连接重置失败。如果我们支持 keep-alive 连接，这种简单的方法会
                # 在读取下一行请求时出错。由于我们知道 write 操作（如上所示）会关闭所有连接，
                # 因此我们可以读取所有内容。
                selector = selectors.DefaultSelector()
                selector.register(self.connection, selectors.EVENT_READ)
                total_size = 0
                total_reads = 0

                # timeout设置为0会失败，应为客户端需要很少的时间来继续发送数据
                while selector.select(timeout=0.01):
                    # 一次只读10MB 到内存
                    data = self.rfile.read(10_000_000)
                    total_size += len(data)
                    total_reads += 1
                    # 当没有数据，>=10GB或1000次读取会停止读取，如果客户端发送超过。
                    # 他们会得到reset failure
                    if not data or total_size >= 10_000_000_000 or total_reads >= 1000:
                        break
                selector.close()

                if hasattr(application_iter, "close"):
                    application_iter.close()
        
        try:
            execute(self.server.app)
        except connection_dropped_errors as e:
            self.connection_dropped(e)
        except Exception as e:
            if self.server.passthrough_errors:
                raise
            if status_sent is not None and chunk_response:
                self.close_connection = True
            
            try:
                # 若headers被设置但还没有发送，回滚来再次发送他们
                if status_sent is None:
                    status_set = None
                    headers_set = None
                execute(InternalServerError())
            except Exception:
                pass
            from .debug.tbtools import DebugTraceback

            msg = DebugTraceback(e).render_traceback_text()
            self.server.log("error", f"Error on request:\n{msg}")

    def handle(self) -> None:
        """处理请求时忽略断开的连接"""
        try:
            super().handle()
        except (ConnectionError, socket.timeout) as e:
            self.connection_dropped(e)
        except Exception as e:
            if self.server.ssl_context is not None and is_ssl_error(e):
                self.log_error("SSL error occurred: %s", e)
            else:
                raise
            
    def connection_dropped(
        self, error: BaseException, environ: WSGIEnvironment | None = None
    ) -> None:
        """若连接被客户端断开则被调用。默认什么也不做"""
        pass

    def __getattr__(self, name: str) -> t.Any:
        # 所有HTTP方法被run_wsgi处理
        if name.startswith("do_"):
            return self.run_wsgi
        
        # 所有其他属性都传递给基类。
        return getattr(super(), name)

    def address_string(self) -> str:
        if getattr(self, "environ", None):
            return self.environ["REMOTE_ADDR"] # type: ignore

        if not self.client_address:
            return "<local>"
        return self.client_address[0]

    def port_integer(self) -> int:
        return self.client_address[1]        

def _ansi_style(value: str, *styles: str) -> str:
    """为终端输出添加ANSI样式"""
    if not _log_add_style: return value
    codes = {
        "bold": "1",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "megenta": "35",
        "cyan": "36",
    }
    for style in styles:
        value = f"\x1b[{codes[style]}m{value}"
    return f"{value}\x1b[0m"

def generate_adhoc_ssl_pair(
    cn: str | None = None,
) -> tuple[Certificate, RSAPrivateKeyWithSerialization]:
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise TypeError(
            "Using ad-hoc certificates requires the cryptography library."
        ) from None
    backend = default_backend()
    pkey = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=backend
    )
    # pretty damn sure that this is not actually accepted by anyone
    if cn is None: cn = "*"

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Dummy Certificate"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )
    backend = default_backend()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(pkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.now(timezone.utc))
        .not_valid_after(dt.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(cn), x509.DNSName(f"*.{cn}")]),
            critical=False,
        )
        .sign(pkey, hashes.SHA256(), backend)
    )
    return cert, pkey

def generate_adhoc_ssl_context() -> ssl.SSLContext:
    """生成一个用于开发服务的adhoc SSL上下文"""
    import atexit
    import tempfile

    cert, pkey = generate_adhoc_ssl_pair()

    from cryptography.hazmat.primitives import serialization

    cert_handle, cert_file = tempfile.mkstemp()
    pkey_handle, pkey_file = tempfile.mkstemp()
    atexit.register(os.remove, pkey_file)
    atexit.register(os.remove, cert_file)

    os.write(cert_handle, cert.public_bytes(serialization.Encoding.PEM))
    os.write(
        pkey_handle,
        pkey.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    os.close(cert_handle)
    os.close(pkey_handle)
    ctx = load_ssl_context(cert_file, pkey_file)
    return ctx

def load_ssl_context(
    certfile: str, pkey_file: str | None = None, protocol: int | None = None
) -> ssl.SSLContext:
    """从cert/private key文件和可选的协议中加载SSL上下文
    许多参数直接从:py:class:`ssl.SSLContext`中取得

    :param cert_file: certificate文件路径
    :param pkey_file: private key文件路径. 若没有给，key会从certfile中提取
    :praam protocol: 一个从:mod:`ssl`模块中读取的``PROTOCOL``constant
        默认使用``ssl.PROTOCOL_TLS_SERVER``
    """
    if protocol is None:
        protocol = ssl.PROTOCOL_TLS_SERVER

    ctx = ssl.SSLContext(protocol)
    ctx.load_cert_chain(certfile, pkey_file)
    return ctx

def is_ssl_error(error: Exception | None = None) -> bool:
    """检查给到的error(或当前的)是否为SSL error"""
    if error is None:
        error = t.cast(Exception, sys.exc_info()[1])
    return isinstance(error, ssl.SSLError)

def select_address_family(host: str, port: int) -> socket.AddressFamily:
    """返回``AF_INET4``或``AF_INET6``或``AF_UNIX``"""
    if host.startswith("unix://"):
        return socket.AF_UNIX
    elif ":" in host and hasattr(socket, "AF_INET6"):
        return socket.AF_INET6
    return socket.AF_INET

def get_sockaddr(
    host: str, port: int, family: socket.AddressFamily
) -> tuple[str, int] | str:
    """返回一个可以传递给:func:`socket.bind`的完全合规socket地址"""
    if family == af_unix:
        # 绝对路径以避免 开始是.时的IDNA encoding问题
        return os.path.abspath(host.partition("://")[2])
    try:
        res = socket.getaddrinfo(
            host, port, family, socket.SOCK_STREAM, socket.IPPROTO_TCP
        )
    except socket.gaierror:
        return host, port
    return res[0][4] # type: ignore

def get_interface_ip(family: socket.AddressFamily) -> str:
    """获取外部接口的IP地址，当绑定到0.0.0.0或者::1时展示更有用的URL"""
    # 任意私有地址
    host = "fd31:f903:5ab5:1::1" if family == socket.AF_INET6 else "10.253.155.219"
    with socket.socket(family, socket.SOCK_DGRAM) as s:
        try:
            s.connect((host, 58162))
        except OSError:
            return "::1" if family == socket.AF_INET6 else "127.0.0.1"
        return s.getsockname()[0]

class BaseWSGIServer(HTTPServer):
    """单次处理一个请求的WSGI服务器"""
    multithread = False
    multiprocess = False
    request_queue_size = LISTEN_QUEUE # 128
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        app: WSGIApplication,
        handler: type[WSGIRequestHandler] | None = None,
        passthrough_errors: bool = False,
        ssl_context: _TSSLContextArg | None = None,
        fd: int | None = None,
    ) -> None:
        if handler is None: handler = WSGIRequestHandler

        # 若handler不直接设置协议版本，并且线程或者进程worker被使用，
        # 那么允许chunked responses和keep-alive连接使用HTTP/1.1
        if "protocol_version" not in vars(handler) and (
            self.multithread or self.multiprocess
        ):
            handler.protocol_version = "HTTP/1.1"
        
        self.host = host
        self.port = port
        self.app = app
        self.passthrough_errors = passthrough_errors

        self.address_family = address_family = select_address_family(host, port)
        server_address = get_sockaddr(host, int(port), address_family)

        # 删除上次运行遗留的UNIX socket文件，不要移除被run_simple设置的文件
        if address_family == af_unix and fd is None:
            server_address = t.cast(str, server_address)
            if os.path.exists(server_address):
                os.unlink(server_address)

        # 仅当我们没有使用一个早已被设置的socket时，绑定和激活会被手动处理
        super().__init__(
            server_address, 
            handler,
            bind_and_activate=False
        )
        if fd is None:
            # 没有存在的socket描述符，使用bind_and_activate=True
            try:
                self.server_bind()
                self.server_activate()
            except OSError as e:
                # 捕获连接错误并打印他们，并且不需要提供traceback信息。
                # 显示未找到地址时的额外说明，以及适用于 macOS 的说明。
                self.server_close()
                print(e.strerror, file=sys.stderr)
            
                if e.errno == errno.EADDRINUSE:
                    print(
                        f"Port {port} is in use by another program. Either identify and"
                        " stop that program, or start the server with a different port.",
                        file=sys.stderr,
                    )
                    if sys.platform == "darwin" and port == 5000:
                        print(
                            "On macOS, try searching for and disabling"
                            " 'AirPlay Receiver' in System Settings.",
                            file=sys.stderr,
                        )
                sys.exit(1)
            except BaseException:
                self.server_close()
                raise
        else:
            # 即使bind_and_activate设置为False,TCPServer也会自动开启一个socket
            # 关闭他以消除ResourceWarning
            self.server_close()

            # 直接使用传入的socket
            self.socket = socket.fromfd(fd, address_family, socket.SOCK_STREAM)
            self.server_address = self.socket.getsockname()

        if address_family != af_unix:
            # port为0，将记录绑定的端口
            self.port = self.server_address[1]
        if ssl_context is not None:
            if isinstance(ssl_context, tuple):
                ssl_context = load_ssl_context(*ssl_context)
            elif ssl_context == "adhoc":
                ssl_context = generate_adhoc_ssl_context()

            self.socket = ssl_context.wrap_socket(self.socket, server_side=True)
            self.ssl_context: ssl.SSLContext = ssl_context
        else:
            self.ssl_context = None
        # from importlib.metadata import version
        from mywerkzeug import __version__
        self._server_version = f"Mywerkzeug/{__version__}"

    def log(self, type: str, message: str, *args: t.Any) -> None:
        _log(type, message, *args)

    def log_startup(self) -> None:
        """启动服务时展示address信息"""
        dev_warning = (
            "WARNING: This is a development server. Do not use it in a production"
            " deployment. Use a production WSGI server instead."
        )
        dev_warning = _ansi_style(dev_warning, "bold", "red")
        message = [dev_warning]

        if self.address_family == af_unix:
            message.append(f" * Running on {self.host}")
        else:
            scheme = "http" if self.ssl_context is None else "https"
            display_hostname = self.host

            if self.host in {"0.0.0.0", "::"}:
                message.append(f" * Running on all addresses ({self.host})")
                if self.host == "0.0.0.0":
                    localhost = "127.0.0.1"
                    display_hostname = get_interface_ip(socket.AF_INET)
                else:
                    localhost = "[::1]"
                    display_hostname = get_interface_ip(socket.AF_INET6)
                message.append(f" * Running on {scheme}://{localhost}:{self.port}")
            
            if ":" in display_hostname:
                display_hostname = f"[{display_hostname}]"
            message.append(f" * Running on {scheme}://{display_hostname}:{self.port}")
        _log("info", "\n".join(message))

class ThreadedWSGIServer(mysocketserver.ThreadingMixIn, BaseWSGIServer):
    """在分离线程中处理并发请求的WSGI服务器，使用:func:`make_server` 创建服务实例"""
    multi_thread = True
    daemon_threads = True

class ForkingWSGIServer(ForkingMixIn, BaseWSGIServer):
    """在分离的fork线程中处理并发请求的WSGI服务器，使用:func:`make_server` 创建服务实例"""
    multi_process = True

    def __init__(
        self,
        host: str,
        port: int,
        app: WSGIApplication,
        processes: int = 40,
        handler: type[WSGIRequestHandler] | None = None,
        passthrough_errors: bool = False,
        ssl_context: _TSSLContextArg | None = None,
        fd: int | None = None,
    ) -> None:
        if not can_fork:
            raise ValueError("Your platform does not support forking.")
        
        super().__init__(host, port, app, handler, passthrough_errors, ssl_context, fd)
        self.max_children = processes

def make_server(
    host: str,
    port: int,
    app: WSGIApplication,
    threaded: bool = False,
    processes: int = 1,
    request_handler: type[WSGIRequestHandler] | None = None,
    passthrough_errors: bool = False,
    ssl_context: _TSSLContextArg | None = None,
    fd: int | None = None,
) -> BaseWSGIServer:
    """根据``threaded``和``processes``参数创建一个合适的WSGI服务器实例。
    
    被:func:`run_simple`调用, 也可以分离使用来获取服务器对象的权限，比如
    在一个分离的线程中运行。
    
    参数信息参考:func:`run_simple`
    """
    if threaded and processes > 1:
        raise ValueError("Cannot have a multi-thread and multi-process server.")
    if threaded:
        return ThreadedWSGIServer(
            host, port, app, request_handler, passthrough_errors, ssl_context, fd=fd
        )
    
    if processes > 1:
        return ForkingWSGIServer(
            host,
            port, 
            app, 
            processes, 
            request_handler, 
            passthrough_errors, 
            ssl_context, 
            fd=fd
        )
    return BaseWSGIServer(
        host, port, app, request_handler, passthrough_errors, ssl_context, fd=fd
    )

def is_running_from_reloader() -> bool:
    """检查服务是否以Werkzeug reloader的子线程运行"""
    return os.environ.get("MYWERKZEUG_RUN_MAIN") == "true"

def run_simple(
    hostname: str,
    port: int,
    application: WSGIApplication,
    use_reloader: bool = False,
    use_debugger: bool = False,
    use_evalex: bool = True,
    extra_files: t.Iterable[str] | None = None,
    exclude_patterns: t.Iterable[str] | None = None,
    reloader_interval: int = 1,
    reloader_type: str = "auto",
    threaded: bool = False,
    processes: int = 1,
    request_handler: type[WSGIRequestHandler] | None = None,
    static_files: dict[str, str | tuple[str, str]] | None = None,
    passthrough_errors: bool = False,
    ssl_context: _TSSLContextArg | None = None,
) -> None:
    """启动一个用于WSGI应用的开发服务器。可启用各种特性选项, 如自动重载、调试模式等。

    .. warning::
        仅用于开发和调试，非设计用于高效稳定安全的生产环境服务器。

    :param hostname: 
        服务器监听的主机名，默认值为"127.0.0.1",可以为域名/
        IPV4/IPV6地址或以``unix://``开头的UNIX域套接字路径。
    :param port: 服务器监听的端口号, ``0``表示随机选择可用端口。
    :param application: 要运行的WSGI应用程序对象。
    :param use_reloader: 是否启用问价变动时自动重载功能, 默认值为False。
    :param use_debugger: 
        使用 Werkzeug 调试器, 当应用程序抛出未处理异常时,
        会显示格式化的跟踪信息。默认值为False。
    :param use_evalex: 
        启动可交互debugger。可以为traceback的任何frame开启一
        个python终端。要求输入PIN码可以提供一定的保护，但这绝不应该在公开可见的
        服务器上启用。
    :param extra_files: 除python模块，重载器会监视这些文件的更改，如配置文件。
    :param exclude_patterns: 重载器会忽略满足这些模式的文件。
    :param reloader_interval: 自动重载检查间隔时间（秒），默认值为1。
    :param reloader_type: 
        重载器类型，```stat```为内置，可能需要大量CPU资源
        来监视文件。```watchdog```更高效，但需要先安装```watchdog```库。
    :param threaded: 使用线程处理处理并发请求，不能和```processes```同时使用。
    :param processes: 
        传入整数N，启动N个进程处理并发请求，不能和```threaded```同时使用。
    :param request_handler: 
        使用`~BaseHTTPServer.BaseHTTPRequestHandler`子类来处理请求
    :param static_files: 
        使用 `~werkzeug.middleware.SharedDataMiddleware` 来为应用添加静态文件服务。
        将URL前缀映射为目录
    :param passthrough_errors:
        不在server层级捕获异常，直接crash。如果使用```use_debugger```，
        调试器依然会捕获这些错误。
    :param ssl_context: 
        用于HTTPS加密的SSL上下文对象。可以是`ssl.SSLContext`实例、
        一个元组```(certfile, keyfile)```用于创建 typical context，或者一个
        字符串```adhoc```用于创建自签名证书。
    """
    if not isinstance(port, int):
        raise TypeError(f"port must be an integer.")
    
    if static_files:
        from .middleware.shared_data import SharedDataMiddleware

        application = SharedDataMiddleware(application, static_files)

    if use_debugger:
        from .debug import DebuggedApplication

        application = DebuggedApplication(application, evalex=use_evalex)
        # 除了localhost域名，允许特殊的hostname使用debugger
        application.trusted_host.append(hostname)

    if not is_running_from_reloader():
        fd = None
    else:
        fd = int(os.environ["MYWERKZEUG_SERVER_ID"])

    srv = make_server(
        hostname,
        port,
        application,
        threaded,
        processes,
        request_handler,
        passthrough_errors,
        ssl_context,
        fd=fd,
    )
    srv.socket.set_inheritable(True)
    os.environ["MYWERKZEUG_SERVER_ID"] = str(srv.fileno())

    if not is_running_from_reloader():
        srv.log_startup()
        _log("info", _ansi_style("Press CTRL+C to quit", "yellow"))

    if use_reloader:
        from ._reloader import run_with_reloader

        try:
            run_with_reloader(
                srv.serve_forever,
                extra_files=extra_files,
                exclude_patterns=exclude_patterns,
                interval=reloader_interval,
                reloader_type=reloader_type,
            )
        finally:
            srv.server_close()
    else:
        srv.serve_forever()