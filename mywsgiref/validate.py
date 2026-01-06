"""
Middleware to check for obedience to the WSGI specification.

Some of the things this checks:

* Signature of the application and start_response (including that
  keyword arguments are not used).

* Environment checks:

  - Environment is a dictionary (and not a subclass).

  - That all the required keys are in the environment: REQUEST_METHOD,
    SERVER_NAME, SERVER_PORT, wsgi.version, wsgi.input, wsgi.errors,
    wsgi.multithread, wsgi.multiprocess, wsgi.run_once

  - That HTTP_CONTENT_TYPE and HTTP_CONTENT_LENGTH are not in the
    environment (these headers should appear as CONTENT_LENGTH and
    CONTENT_TYPE).

  - Warns if QUERY_STRING is missing, as the cgi module acts
    unpredictably in that case.

  - That CGI-style variables (that don't contain a .) have
    (non-unicode) string values

  - That wsgi.version is a tuple

  - That wsgi.url_scheme is 'http' or 'https' (@@: is this too
    restrictive?)

  - Warns if the REQUEST_METHOD is not known (@@: probably too
    restrictive).

  - That SCRIPT_NAME and PATH_INFO are empty or start with /

  - That at least one of SCRIPT_NAME or PATH_INFO are set.

  - That CONTENT_LENGTH is a positive integer.

  - That SCRIPT_NAME is not '/' (it should be '', and PATH_INFO should
    be '/').

  - That wsgi.input has the methods read, readline, readlines, and
    __iter__

  - That wsgi.errors has the methods flush, write, writelines

* The status is a string, contains a space, starts with an integer,
  and that integer is in range (> 100).

* That the headers is a list (not a subclass, not another kind of
  sequence).

* That the items of the headers are tuples of strings.

* That there is no 'status' header (that is used in CGI, but not in
  WSGI).

* That the headers don't contain newlines or colons, end in _ or -, or
  contain characters codes below 037.

* That Content-Type is given if there is content (CGI often has a
  default content type, but WSGI does not).

* That no Content-Type is given when there is no content (@@: is this
  too restrictive?)

* That the exc_info argument to start_response is a tuple or None.

* That all calls to the writer are with strings, and no other methods
  on the writer are accessed.

* That wsgi.input is used properly:

  - .read() is called with zero or one argument

  - That it returns a string

  - That readline, readlines, and __iter__ return strings

  - That .close() is not called

  - No other methods are provided

* That wsgi.errors is used properly:

  - .write() and .writelines() is called with a string

  - That .close() is not called, and no other methods are provided.

* The response iterator:

  - That it is not a string (it should be a list of a single string; a
    string will work, but perform horribly).

  - That .next() returns a string

  - That the iterator is not iterated over until start_response has
    been called (that can signal either a server or application
    error).

  - That .close() is called (doesn't raise exception, only prints to
    sys.stderr, because we only know it isn't called when the object
    is garbage collected).
"""

__all__ = ['validator']

import re
import sys
import warnings

# start with a letter, followed by letters, digits, _, - 
header_re = re.compile(r'^[a-zA-Z][a-zA-Z0-9\-_]*$')
# \000-\037 are control characters
bad_header_value_re = re.compile(r'[\000-\037]')


def assert_(cond, *args):
    if not cond: raise AssertionError(*args)

def validator(application):
    """Check for WSGI compliancy on a number of levels."""
    def lint_app(*args, **kw):
        assert_(len(args) == 2, "Two arguments required")
        assert_(not kw, "No keyword arguments allowed")
        environ, start_response = args

        check_environ(environ)

        start_response_started = []

        def start_respone_wrapper(*args, **kw):
            assert_(len(args) == 2 or len(args) == 3, (
                f"Invalid number of arguments: {(args, )}"))
            assert_(not kw, "No keyword arguments allowed")
            status = args[0]
            headers = args[1]
            if len(args) == 3:
                exc_info = args[2]
            else:
                exc_info = None
            
            check_status(status)
            check_headers(headers)
            check_content_type(status, headers)
            check_exc_info(exc_info)

            start_response_started.append(None)
            return WriteWrapper(start_response(*args))

        environ['wsgi.input'] = InputWrapper(environ['wsgi.input'])
        environ['wsgi.errors'] = ErrorWrapper(environ['wsgi.errors'])

        iterator = application(environ, start_respone_wrapper)
        assert_(iterator is not None and iterator != False,
            "The application must return an itertor, if only an empty list")

        check_iterator(iterator)

        return IteratorWrapper(iterator, start_response_started)
    
    return lint_app


#region check_environ

def check_environ(environ):
    assert_(type(environ) is dict,
        f"Environment is not of the right type: {type(environ)} \
        (envrionment: {environ})")
    
    for key in ['REQUEST_METHOD', 'SERVER_NAME', 'SERVER_PORT',
                'wsgi.version', 'wsgi.input', 'wsgi.errors',
                'wsgi.multithread', 'wsgi.multiprocess', 
                'wsgi.run_once']:
        assert_(key in environ, 
            f"Environment missing required key: {key}")
    
    for key in ['HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH']:
        assert_(key not in environ,
            f"Environment should not have the key: {key} \
            (use {key[5:]} instead)")

    if 'QUERY_STRING' not in environ:
        warnings.warn(
            'QUERY_STRING is missing, will use sys.argv, '
            'so application errors are more likely')
        
    for key in environ.keys():
        for '.' in key:
            # Extension, we don't care about its type
            continue
        assert_(type(environ[key]) is str,
            f"Environmental variable {key} is not a string: "
            f"{type(environ[key])} (value: {environ[key]})")

    assert_(type(environ['wsgi.version']) is tuple,
        f"wsgi.version should be a tuple {environ['wsgi.version']}")
    assert_(environ['wsgi.url_scheme'] in ('http', 'https'),
        f"wsgi.url_scheme unknown: {environ['wsgi.url_scheme']}")
    
    check_input(environ['wsgi.input'])
    check_errors(environ['wsgi.errors'])

    # @@@: this need filling out
    if environ['REQUEST_METHOD'] not in (
        'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'TRACE'):
        warnings.warn(
            f"REQUEST_METHOD unknown: {environ['REQUEST_METHOD']}")

    assert_(not environ.get("SCRIPT_NAME") 
        or environ["SCRIPT_NAME"].startswith("/"),
        f"SCRIPT_NAME should start with /: {environ['SCRIPT_NAME']}")
    assert_(not environ.get("PATH_INFO") 
        or environ["PATH_INFO"].startswith("/"),
        f"PATH_INFO should start with /: {environ['PATH_INFO']}")

    if environ.get('CONTENT_LENGTH'):
        assert_(int(environ['CONTENT_LENGTH']) >= 0,
            f"Invalid CONTENT_LENGTH: {environ['CONTENT_LENGTH']}")
    
    if not environ.get('SCRIPT_NAME'):
        assert_(environ.has_key('PATH_INFO'),
            "One of SCRIPT_NAME or PATH_INFO must be set, (PATH_INFO "
            "should at least be '/' if SCRIPT_NAME is empty)")
    assert_(environ.get('SCRIPT_NAME') != '/',
        "SCRIPT_NAME cannot be '/', it should instead be '', and "
        "PATH_INFO should be '/'")

def check_input(wsgi_input):
    """Prove that wsgi_input has four attributes."""
    for attr in ['read', 'readline', 'readlines', '__iter__']:
        assert_(hasattr(wsgi_input, attr),
            f"wsgi.input ({wsgi_input}) is missing attribute: {attr}")
    
def check_errors(wsgi_errors):
    """Prove that wsgi_errors has three attributes."""
    for attr in ['flush', 'write', 'writelines']:
        assert_(hasattr(wsgi_errors, attr),
            f"wsgi.errors ({wsgi_errors}) is missing attribute: {attr}")

#endregion check_environ

def check_status(status: str):
    # Examples:"200 OK"
    assert_(type(status) is str,
        f"Status must be a string (not {status})")
    status_code = status.split(None, 1)[0]
    assert_(len(status_code) == 3,
        f"Status codes must be three characters: {status_code}")
    status_int = int(status_code)
    assert_(status_int >= 100, f"Status code is invalid: {status_int}")
    if len(status) < 4 or status[3] != ' ':
        warnings.warn(
            "The status string {status} should be a three-digit integer "
            "followed by a single space and status message.")

def check_headers(headers):
    assert_(type(headers) is list,
        f"Headers {headers} must be of type list: {type(headers)}")
    header_names = {}
    for item in headers:
        assert_(type(item) is tuple,
            f"Individual headers {headers} must be of type tuple: \
            {type(item)}")
    
        assert_(len(item) == 2)
        name, value = item
        assert_(name.lower() != 'status',
            f"Header name {name} cannot be 'Status'; confilit with CGI "
            "script, and HTTP status is not given through headers "
            f"(value: {value})")
        header_names[name.lower()] = None
        assert_('\n' not in name and ":" not in name,
            f"Header names may not contain ':' or '\\n': {name}")
        assert_(header_re.search(name), 
            f"Bad header name: {name}")
        assert_(not name.endswith('-') and not name.endswith('_'), 
            f"Name not end with '_' or '-': {name}")
        if bad_header_value_re.search(value):
            assert_(0, f"Bad header {value}: (bad char: \
                {bad_header_value_re.search(value).group(0)})")

def check_content_type(status, headers):
    code = int(status.split(None, 1)[0])
    NO_MESSAGE_BODY = (204, 304)
    for name, value in headers:
        if name.lower() == 'content-type':
            if code not in NO_MESSAGE_BODY: return
            assert_(0, 
                (f"Content-Type header found in a {code} response, "
                "which must not have a body."))
    if code not in NO_MESSAGE_BODY:
        assert_(0, f"No Content-Type header found in headers {headers}")
    
def check_exc_info(exc_info):
    assert_(exc_info is None or type(exc_info) is type(()),
        f"exc_info {exc_info} must be None or a tuple: {type(exc_info)}")

class InputWrapper:
    def __init__(self, wsgi_input):
        self.input = wsgi_input
    
    def read(self, *args):
        assert_(len(args) <= 1)
        v = self.input.read(*args)
        assert_(type(v) is bytes)
        return v
    
    def readline(self, *args):
        assert_(len(args) <= 1)
        lines = self.input.readline(*args)
        assert_(type(lines) is type([]))
        for line in lines:
            assert_(type(line) is bytes)
        return lines
    
    def __iter__(self):
        while 1:
            line = self.input.readline()
            if not line: return
            yield line
    
    def close(self):
        assert_(0, "input.close() must not be called")
            
class ErrorWrapper:
    def __init__(self, wsgi_errors):
        self.errors = wsgi_errors

    def write(self, s):
        assert_(type(s) is type(""))
        self.errors.write(s)
    
    def flush(self):
        self.errors.flush()

    def writeline(self, seq):
        for line in seq:
            self.write(line)
    
    def close(self):
        assert_(0, "errors.close() must not be called")

class WriteWrapper:
    def __init__(self, wsgi_write):
        self.writer = wsgi_write

    def __call__(self, s):
        assert_(type(s) is bytes)
        self.writer(s)

class IteratorWrapper:
    def __init__(self, wsgi_iterator, check_start_response):
        self.original_iterator = wsgi_iterator
        self.iterator = iter(wsgi_iterator)
        self.closed = False
        self.check_start_response = check_start_response

    def __iter__(self):
        return self
    
    def next(self):
        # check if closed
        assert_(not self.closed, "Iterator read after closed")
        v = next(self.iterator)
        if type(v) is not bytes:
            assert_(False, f"Iterator yield non-bytestring ({(v,)})")
        if self.check_start_response is not None:
            assert_(self.check_start_response, 
                "The application returns and we started iterating over its body, " \
                "but start_response() has not been called yet.")
            self.check_start_response = None
        return v
    
    def close(self):
        self.closed = True

    def __del__(self):
        if not self.closed:
            sys.stderr.write("Iterator garbage collected without being closed.")
        assert_(self.closed, "Iterator garbage collected without being closed." )
    
    

def check_iterator(iterator):
    assert_(not isinstance(iterator, (bytes, str)),
        "You should return a string as your application iterator, " \
        "instead return a single-item list containing that string.")
