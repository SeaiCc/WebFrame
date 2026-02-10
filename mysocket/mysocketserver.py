import os
import socket
import selectors
import sys
import threading
from io import BufferedIOBase

__all__ = ["TCPServer",
           "StreamRequestHandler",
           "ThreadingMixIn",]
if hasattr(os, "fork"):
    __all__.extend(["ForkingMixIn",])

# 与 epoll/kqueue 不同，poll/select 有不需要任何额外文件描述符的优点，
# 此外他们只需要一次系统调用
if hasattr(selectors, 'PollSelector'):
    _ServerSelector = selectors.PollSelector
else:
    _ServerSelector = selectors.SelectSelector


class TCPServer:

    address_family = socket.AF_INET

    socket_type = socket.SOCK_STREAM

    request_queue_size = 5

    allow_reuse_address = False

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        """Constructor. May be extented, don not override."""
        self.server_address = server_address
        self.RequestHandlerClass = RequestHandlerClass
        self.__is_shut_down = threading.Event()
        self.__shutdown_request = False

        self.socket = socket.socket(self.address_family, self.socket_type)

        if bind_and_activate:
            try:
                self.server_bind()
                self.server_activate()
            except:
                self.server_close()
                raise
    
    def server_bind(self):
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def serve_forever(self, poll_interval=0.5):
        """Handle one request at a time util shutdown.

        Polls for shutdown every poll_interval seconds. Ignores
        self.timeout. If you need to do periodic tasks, do them in
        another thread.
        """

        self.__is_shut_down.clear()
        try:
            with _ServerSelector() as selector:
                selector.register(self, selectors.EVENT_READ)

                while not self.__shutdown_request:
                    reday = selector.select(poll_interval)
                    if self.__shutdown_request:
                        break
                    if reday:
                        self._handle_request_noblock()
                    
                    self.service_actions()
        finally:
            self.__shutdown_request = False
            self.__is_shut_down

#region handle request
    def _handle_request_noblock(self):
        """Handle one request, without blocking.
        
        selector.select() has returned && socket is readable before this 
        function was called.
        """
        try:
            request, client_address = self.get_request()
        except OSError:
            return
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
                self.shutdown_request(request)
            except:
                self.shutdown_request(request)
                raise
        else:
            self.shutdown_request(request)

    def get_request(self):
        """Get the request and client address from the socket."""
        return self.socket.accept()
    
    def verify_request(self, request, client_address):
        """Verify the request. May be overridden."""
        return True
    
    def process_request(self, request, client_address):
        """Call real request handler and shut down request."""
        self.finish_request(request, client_address)
        self.shutdown_request(request)

    def finish_request(self, request, client_address):
        """Finish one request by instantiating RequestHandlerClass."""
        self.RequestHandlerClass(request, client_address, self)

#endregion handle request

    def shutdown_request(self, request):
        """Called to shutdown and close an individual request."""
        try:
            # socket.close() merely releases the socket and 
            # wait for GC to perform the actual close.
            request.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.close_request(request)

    def close_request(self, request):
        """Called to clean up an individual request."""
        request.close()

    def service_actions(self):
        """May be overridden implement any code that needs to
        be run during the loop.
        """
        pass

    def fileno(self):
        """Retrun socket file number.
        
        Interface required by selector.
        """
        return self.socket.fileno()

    def server_activate(self):
        self.socket.listen(self.request_queue_size)

    def server_close(self):
        self.socket.close()

    def handle_error(self, request, client_address):
        """Handle an error gracefully. May be overridden.
        
        The default is to print a traceback and continue
        """
        print('-'*40, file=sys.stderr)
        print('Exception happened during processing of request from',
              client_address, file=sys.stderr)
        import traceback
        traceback.print_exc()
        print('-'*40, file=sys.stderr)

    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.server_close()

if hasattr(os, "fork"):
    class ForkingMixIn:
        """在一个新线程中处理每个请求的Mix-in类"""
        timeout = 300
        active_children = None
        max_children = 40
        # 若为True，server_close()会等待所有子进程结束
        block_on_close = True

class _NoThreads:
    """_Threads的退化版本"""
    def append(self, thread):
        pass

    def join(self):
        pass

class ThreadingMixIn:
    """在一个新线程处理每个请求的Mix-in类"""

    # 决定主线程终止时线程的行为
    daemon_threads = False
    # 若为真，server_close()会等待所有非守护进程终止
    block_on_close = True
    # 线程对象
    # 用于server_close()等待所有线程完成
    _threads = _NoThreads()

class StreamRequestHandler:

    rbufsize = -1
    wbufsize = 0

    timeout = None

    disable_nagle_algorithm = False

    def __init__(self, request, client_address, server):
        self.request = request
        self.client_address = client_address
        self.server = server
        self.setup()
        try:
            self.handle()
        finally:
            self.finish()
    
    def setup(self):
        self.connection = self.request
        if self.timeout is not None:
            self.connection.settimeout(self.timeout)
        if self.disable_nagle_algorithm:
            self.connection.setsocket(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.rfile = self.connection.makefile('rb', self.rbufsize)
        if self.wbufsize == 0:
            self.wfile = _SocketWriter(self.connection)
        else:
            self.wfile = self.connection.makefile('wb', self.wbufsize)

    def handle(self):
        pass

    def finish(self):
        if not self.wfile.closed:
            try:
                self.wfile.flush()
            except socket.error:
                pass
        
        self.wfile.close()
        self.rfile.close()

class _SocketWriter(BufferedIOBase):

    def __init__(self, sock):
        self._sock = sock
    
    def writeable(self):
        return True
    
    def write(self, b):
        self._sock.sendall(b)
        with memoryview(b) as view:
            return  view.nbytes
    
    def fileno(self):
        return self._sock.fileno()
