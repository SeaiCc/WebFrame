import email.utils
import itertools
import socket
import sys
import time

from mysocket import mysocketserver
from myhttp import HTTPStatus
import myhttp.http_client

__version__ = "0.6"

class HTTPServer(mysocketserver.TCPServer):
    
    allow_reuse_address = 1

    def server_bind(self):
        """Override server_bind to store the server name."""
        mysocketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = socket.getfqdn(host)
        self.server_port = port

class BaseHTTPRequestHandler(mysocketserver.StreamRequestHandler):

    sys_version = "Python/" + sys.version.split()[0]

    server_version = "BaseHTTP/" + __version__

    # Response dict, code: (phrase, desc) 
    responses = {
        v: (v.phrase, v.description)
        for v in HTTPStatus.__members__.values()
    }

    monthname = [None,
                 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

#region handle

    default_request_version = "HTTP/0.9"

    protocol_version = "HTTP/1.0"

    MessageClass = myhttp.http_client.HTTPMessage

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return 
            if not self.parse_request():
                # 可发送错误码， 这里只退出
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(
                    HTTPStatus.NOT_IMPLEMENTED,
                    "Unsupported method (%r)" % self.command
                )
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush() # 若还没有发送response，立即发送
        except TimeoutError as e:
            # a read or a write timed out. Discard this connection
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return

    def handle(self):
        """如果需要处理多个请求"""
        self.close_connection = True

        self.handle_one_request()
        while not self.close_connection:
            self.handle_one_request()

    def parse_request(self):
        """Parse a request (internal).
        
        The request should be stored in self.raw_requestline; the results
        are in self.command, self.path, self.request_version and self.headers.
        
        Return True if success, onfailure, any relevant error response has 
        already been sent back.
        """
        self.command = None # set in case of error on the first line
        self.request_version = version = self.default_request_version
        self.close_connection = True
        requestline = str(self.raw_requestline, 'iso-8859-1')
        requestline = requestline.rstrip('\r\n')
        self.requestline = requestline
        words = requestline.split()
        if len(words) == 0: return False

        if len(words) >= 3: # Enough to determine protocol version
            version = words[-1]
            try:
                if not version.startswith('HTTP/'):
                    raise ValueError
                base_version_number = version.split('/', 1)[1]
                version_number = base_version_number.split(".")
                # RFC 2145 section 3.1 says just one "."
                #   - major and minor number MUST be treated as int
                #   - HTTP/12.3 > HTTP/2.13 > HTTP/2.4 
                #   - Leading zeros MUST be ignored
                if len(version_number) != 2:
                    raise ValueError
                version_number = int(version_number[0]), int(version_number[1])
            except (ValueError, IndexError):
                self.send_error(
                    HTTPStatus.BAD_REQUEST,
                    "Bad request version (%r)" % version)
                return False
            # greater than 1.1 need set connection non close 
            if version_number >= (1, 1) and self.protocol_version >= "HTTP/1.1":
                self.close_connection = False
            # not support http/2.0
            if version_number >= (2, 0):
                self.send_error(
                    HTTPStatus.HTTP_VERSION_NOT_SUPPORTED,
                    "Invalid HTTP version (%s)" % base_version_number
                )
                return False
            self.request_version = version

        if not 2 <= len(words) <= 3: # 2 or 3
            self.send_error(
                HTTPStatus.BAD_REQUEST,
                "Bad request syntax (%r)" % requestline)
            return False
        command, path = words[:2]
        if len(words) == 2: # GET path 2 words
            self.close_connection = True
            if command != 'GET':
                self.send_error(
                    HTTPStatus.BAD_REQUEST,
                    "Bad HTTP/0.9 request type (%r)" % command)
                return False
        self.command, self.path = command, path

        # Examine the headers and look for a Connection directive.
        try:
            self.headers = myhttp.http_client.parse_headers(self.rfile,
                                                     _class=self.MessageClass)
        except myhttp.http_client.LineTooLong as err:
            self.send_error(
                HTTPStatus.REQUEST_HEADER_FILEDS_TOO_LARGE,
                "Line too long",
                str(err))
            return False
        except myhttp.http_client.HTTPException as err:
            self.send_error(
                HTTPStatus.REQUEST_HEADER_FILEDS_TOO_LARGE,
                "Too many headers",
                str(err))
            return False
        
        conntype = self.headers.get('Connection', "")
        if conntype.lower() == 'close':
            self.close_connection = True
        elif (conntype.lower() == 'keep-alive' and
              self.protocol_version >= "HTTP/1.1"):
            self.close_connection = False
        # Examine the headers and look for an Except directive
        expect = self.headers.get('Excpet', "")
        if (expect.lower() == "100-continue" and
                self.protocol_version >= "HTTP/1.1" and
                self.request_version >= "HTTP/1.1"):
            if not self.handle_expect_100():
                return False
        return True

    def handle_expect_100(self):
        """Decide what to do with and "Expect: 100-continue" header.
        
        """
        self.send_response_only(HTTPStatus.CONTINUE)
        self.end_headers()
        return True
    
    def send_response(self, code, message=None):
        """将response的header添加至headers buffer 并打印response code

        也会发送两个两个标准头，分别包含软件版本和当前日期
        """
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header("Server", self.version_string())
        self.send_header("Date", self.date_time_string())

    def send_response_only(self, code, message=None):
        """Send the response header only."""
        if self.request_version != 'HTTP/0.9':
            if message is None:
                if code in self.responses:
                    message = self.responses[code][0]
                else:
                    message = ''
            if not hasattr(self, '_headers_buffer'):
                self._headers_buffer = []
            self._headers_buffer.append(("%s %d %s\r\n" %
                    (self.protocol_version, code, message)).encode(
                        'latin-1', 'strict'))

    def send_header(self, keyword, value):
        """发送一个MIME头到headers buffer"""
        if self.request_version != 'HTTP/0.9':
            if not hasattr(self, '_headers_buffer'):
                self._headers_buffer = []
            self._headers_buffer.append(
                ("%s: %s\r\n" % (keyword, value)).encode('latin-1', 'strict')
            )
        if keyword.lower() == 'connection':
            if value.lower() == 'close':
                self.close_connection = True
            elif value.lower() == 'keep-alive':
                self.close_connection = False

    def end_headers(self):
        """Send the blank line ending the MIME headers."""
        if self.request_version != 'HTTP/0.9':
            self._headers_buffer.append(b"\r\n")
            self.flush_headers()

    def flush_headers(self):
        if hasattr(self, '_headers_buffer'):
            self.wfile.write(b"".join(self._headers_buffer))
            self._headers_buffer = []

#endregion handle

    def send_error(self, code, message=None, explain=None):
        """Send and log an error reply.
        
        Arguments:
        - code:     an HTTP error code
                    3 digits
        - message:  a simple optional 1 line reason phrase.
                    *( HTAB / SP / VCHAR/ %x80-FF )
        - explain:  a detailed message defaults to the long entry
                    matching the response code.

        This sends an error response (must be called before any outputs
        has been generated), logs errors and sends a piece of HTML
        explaining the error to the user.

        """

        try:
            shortmsg, longmsg = self.responses[code]
        except KeyError:
            shortmsg, longmsg = '???', '???'
        if message is None:
            message = shortmsg
        if explain is None:
            explain = longmsg
        self.log_error("code %d, message %s", code, message)

    def log_request(self, code='-', size='-'):
        """Log an accepted request.
        
        This is called by send_response().
        """
        if isinstance(code, HTTPStatus):
            code = code.value
        self.log_message('"%s" %s %s',
                self.requestline, str(code), str(size))
        
    def log_error(self, format, *args):
        """Log an error.
        
        Just separate from log_message.
        """
        self.log_message(format, *args)
    
    # https://en.wikipedia.org/wiki/List_of_Unicode_characters#Control_codes
    _control_char_table = str.maketrans(
        {c: fr'\x{c:02x}' for c in itertools.chain(range(0x20), range(0x7f,0xa0))})
    _control_char_table[ord('\\')] = r'\\'
    
    def log_message(self, format, *args):
        """Log an arbitrary message.
        
        Arguments:
        - format:   a format string for the message to be logged.
                    if contains any %s, should be specified in args.
        - args:     uesd by format string

        Lowest level logging functions.
        Client IP and current date/time are prefixed to each message.
        Unicode control char are replaced with escaped hex before
        writing the output to stderr.

        """
        message = format % args
        sys.stderr.write("%s -- [%s] %s\n" %
                        (self.address_string(),
                         self.log_date_time_string(),
                         message.translate(self._control_char_table)))

    def version_string(self):
        """返回服务器版本字符串"""
        return self.server_version + ' ' + self.sys_version
    
    def date_time_string(self, timestamp=None):
        """返回以邮件头显示的当前日期和时间"""
        if timestamp is None:
            timestamp = time.time()
        return email.utils.formatdate(timestamp, usegmt=True)

    def address_string(self):
        """Return the clinet address."""
        return self.client_address[0]
    
    def log_date_time_string(self):
        """Return the current time formatted for logging."""
        now = time.time()
        year, month, day, hh, mm, ss, x, y, z = time.localtime(now)
        s = "%02d/%3s/%04d %02d:%02d:%02d" % (
            day, self.monthname[month], year, hh, mm, ss)
        return s

