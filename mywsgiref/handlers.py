import os
import sys
import time

from mywsgiref.headers import Headers
from mywsgiref.util import FileWrapper, guess_scheme, is_hop_by_hop

__all__ = ['BaseHandler', 'SimpleHandler']

_weekdayname =["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_monthname = [None,
              "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def format_date_time(timestamp):
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
    return "%s, %02d %3s %04d %02d:%02d:%02d GMT" % (
        _weekdayname[wd], day, _monthname[month], year, hh, mm, ss
    )

class BaseHandler:
    """Manage the invocation of a WSGI application."""
    wsgi_version = (1, 0)
    wsgi_multithread = True
    wsgi_multiprocess = True
    wsgi_run_once = False

    origin_server = True
    http_version = "1.0"
    server_software = None

    os_environ = dict(os.environ.items())

    # Collaborator classes
    wsgi_file_wrapper = FileWrapper
    headers_class = Headers

    # Error handling (also pre-subclass or pre-instance)
    traceback_limit = None
    error_status = "500 Dude, this is whack!"
    error_headers = [('Content-Type', 'text/plain')]
    error_body = "A server error occurred. Please contact the administrator."

    # State variables (don't mess with these)
    status = result = None
    headers_sent = False
    headers = None
    bytes_sent = 0


    def run(self, application):
        """Invoke the WSGI application."""
        try:
            self.setup_environ()
            self.result = application(self.environ, self.start_response)
            self.finish_response()
        except:
            try:
                self.handle_error()
            except:
                # If handle_error fails, just raise the exception
                raise

    def handle_error(self):
        """Log current error, and send error output to client if possible."""
        self.log_exception(sys.exc_info())
        if not self.headers_sent:
            self.result = self.error_output(self.environ, self.start_response)
            self.finish_response()

    def log_exception(self, exc_info):
        """Log the 'exc_info' tuple in the server log."""
        try:
            from traceback import print_exception
            stderr = self.get_stderr()
            print_exception(
                exc_info[0], exc_info[1], exc_info[2],
                self.traceback_limit, stderr
            )
            stderr.flush()
        finally:
            exc_info = None

    def error_output(self, environ, start_response):
        """WSGI mini-app to create error output."""
        start_response(self.error_status, self.error_headers[:], sys.exc_info())
        return [self.error_body]

#region finish_response
    def finish_response(self):
        """Send any iterable data, then close self and the iterable."""
        try:
            if not self.result_is_file() or not self.sendfile():
                for data in self.result:
                    print(f"BaseHandler:: data: {data}")
                    self.write(data)
                self.finish_content()
        finally:
            self.close()

    def result_is_file(self):
        """True if 'self.result' is an instance of 'self.wsgi_file_wrapper'"""
        wrapper = self.wsgi_file_wrapper
        return wrapper is not None and isinstance(self.result, wrapper)
    
    def sendfile(self):
        """Platform-specific file transmission."""
        return False # No platform-specific transmission by default

    def finish_content(self):
        """Ensure headers and content have both been sent."""
        if not self.headers_sent:
            self.headers['Content-Type'] = "0"
            self.send_headers()
        else:
            pass

    def send_headers(self):
        """Transmit headers to client, via self._write()"""
        self.cleanup_headers()
        self.headers_sent = True
        if not self.origin_server or self.client_is_modern():
            self.send_preamble()
            self._write(str(self.headers).encode('utf-8'))
    
    def cleanup_headers(self):
        """Make any accessary header changes to default """
        if not self.headers.has_key('Content-Type'):
            self.set_content_length()

    def set_content_length(self):
        """Compute Content-Length or switch to chunked encoding."""
        try:
            blocks = len(self.result)
        except (TypeError,AttributeError,NotImplementedError):
            pass
        else:
            if blocks == 1:
                self.headers['Content-Length'] = str(self.bytes_sent)
                return

    def client_is_modern(self):
        """True if client can accept status and headers."""
        return self.environ['SERVER_PROTOCOL'].upper() != 'HTTP/0.9'
    
    def send_preamble(self):
        """Transmit version/status/date/server, via self._write()."""
        if self.origin_server:
            if self.client_is_modern():
                self._write(f'HTTP/{self.http_version} {self.status}\r\n'.encode('utf-8'))
                if not self.headers.has_key('Date'):
                    self._write(f'Date: {format_date_time(time.time())}\r\n'.encode('utf-8'))
                if self.server_software and not self.headers.has_key('Server'):
                    self._write(f'Server: {self.server_software}\r\n'.encode('utf-8'))
        else:
            self._write(f'Status: {self.status}\r\n')

    def close(self):
        """Close the iterable (if needed) and reset all instance vars"""
        try:
            if hasattr(self.result, 'close'):
                self.result.close()
        finally:
            self.result = self.headers = self.status = self.environ = None
            self.byte_sent = 0
            self.headers_sent = False

#endregion finish_response

#region start_response
    def start_response(self, status, headers, exc_info=None):
        """'start_response()' callable as specified by PEP 333"""
        if exc_info:
            try:
                if self.headers_sent:
                    # Re-raise original exception if headers sent
                    raise exc_info[1].with_traceback(exc_info[2])
            finally:
                # Avoid dangling references
                exc_info = None
        elif self.headers is not None:
            raise AssertionError("Headers already sent")
        
        self.status = status
        self.headers = self.headers_class(headers)
        assert type(status) is str, "Status must be a string"
        assert len(status)>=4, "Status must be at least 4 characters"
        assert int(status[:3]),"Status message must begin w/3-digit code"
        assert status[3]==" ", "Status message must have a space after code"
        if __debug__:
            for name,val in headers:
                assert type(name) is str, "Header names must be a string"
                assert type(val) is str, "Header values must be a string"
                assert not is_hop_by_hop(name), "Hop-by-hop headers are not allowed"
        return self.write

    def write(self, data):
        """'write()' callable as specified by PEP 333"""

        assert type(data) is bytes, f"write() argument must be string {type(data)}"

        if not self.status:
            raise AssertionError("write() before start_response()")
        elif not self.headers_sent:
            # Before the first output, send the stored headers
            self.bytes_sent = len(data)
            self.send_headers()
        else:
            self.bytes_sent += len(data)
        
        self._write(data)
        self._flush()

    def _write(self, data):
        """Override to buffer data for send to client."""
        raise NotImplementedError
    
    def _flush(self):
        """Override to force sending of recent '_write()' calls."""
        raise NotImplementedError
#endregion start_response

#region setup environ 
    def setup_environ(self):
        """Set up base environment for request"""

        env = self.environ = self.os_environ.copy()
        self.add_cgi_vars()

        env['wsgi.input']        = self.get_stdin()
        env['wsgi.errors']       = self.get_stderr()
        env['wsgi.version']      = self.wsgi_version
        env['wsgi.run_once']     = self.wsgi_run_once
        env['wsgi.url_scheme']   = self.get_scheme()
        env['wsgi.multithread']  = self.wsgi_multithread
        env['wsgi.multiprocess'] = self.wsgi_multiprocess

        if self.wsgi_file_wrapper is None:
            env['wsgi.file_wrapper'] = self.wsgi_file_wrapper

        if self.origin_server and self.server_software:
            env.setdefault('SERVER_SOFTWARE', self.server_software)  

    def get_scheme(self):
        """Return the URL scheme being used."""
        return guess_scheme(self.environ)

    def get_stdin(self):
        """Override to return a suitable 'wsgi.input'"""
        raise NotImplementedError
    
    def get_stderr(self):
        """Override to return a suitable 'wsgi.errors'"""
        raise NotImplementedError

    def add_cgi_vars(self):
        """Override to insert CGI variables in 'self.environ'"""
        raise NotImplementedError
#endregion setup environ

class SimpleHandler(BaseHandler):
    """Handler that's just initialized with streams, environment, etc.

    For synchronous HTTP/1.0 origin servers, and handles sending the
    entire response output, given the correct intputs.
    """

    def __init__(self, stdin, stdout, stderr, environ,
        multithread=True, multiprocess=False
    ):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.base_env = environ
        self.wsgi_multithread = multithread
        self.wsgi_multiprocess = multiprocess

    def get_stdin(self):
        return self.stdin

    def get_stderr(self):
        return self.stderr
    
    def add_cgi_vars(self):
        self.environ.update(self.base_env)

    def _write(self, data):
        self.stdout.write(data)
        self._write = self.stdout.write

    def _flush(self):
        self.stdout.flush()
        self._flush = self.stdout.flush