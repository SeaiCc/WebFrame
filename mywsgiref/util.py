"""WSGI-related Utilities"""

import posixpath

__all__ = [
    'guess_scheme', 'request_uri', 'application_uri', 'shift_path_info',
    'setup_testing_defaults', 'is_hop_by_hop', 'FileWrapper'
]

class FileWrapper:
    """Wrapper for file objects to make them iterable."""
    def __init__(self, filelike, blksize: int = 8192):
        self.filelike = filelike
        self.blksize = blksize
        if hasattr(filelike, 'close'):
            self.close = filelike.close

    def __getitem__(self, key):
        data = self.filelike.read(self.blksize)
        if data:
            return data
        raise IndexError

    def __iter__(self):
        return self
    
    def next(self):
        data = self.filelike.read(self.blksize)
        if data:
            return data
        raise StopIteration

def guess_scheme(environ: dict) -> str:
    """Guess the 'wsgi.url_scheme' is 'http' or 'https'."""
    if environ.get('HTTPS') in ('yes', 'on', '1'):
        return 'https'
    else:
        return 'http'
    

def application_uri(environ: dict) -> str:
    """Return base URI, no PATH_INFO or QUERY_STRING."""
    url = environ['wsgi.url_scheme'] + '://'
    from urllib import quote

    if environ.get('HTTP_HOST'):
        url += environ['HTTP_HOST']
    else:
        url += environ['SERVER_NAME']
        
        if environ['wsgi.url_scheme'] == 'https':
            if environ['SERVER_PORT'] != '443':
                url += ':' + environ['SERVER_PORT']
        else:
            if environ['SERVER_PORT'] != '80':
                url += ':' + environ['SERVER_PORT']
    
    # quote - example: SCRIPT_NAME = '/my%20app'
    url += quote(environ.get('SCRIPT_NAME') or '/')
    return url

def request_uri(environ: dict, include_query:int = 1) -> str:
    """Return the full rquest URI, optionally including the query string."""
    url = application_uri(environ)
    from urllib import quote
    path_info = quote(environ.get('PATH_INFO', ''))
    if not environ.get('SCRIPT_NAME'):
        # url = "http://localhost:8000/" + path_info[1:]
        url += path_info[1:]
    else:
        # url = "http://localhost:8000/my%20app" + path_info
        url += path_info
    if include_query and environ.get('QUERY_STRING'):
        url += '?' + environ['QUERY_STRING']
    return url

def shift_path_info(environ: dict) -> str:
    """Shift a name from PATH_INFO to SCRIPT_NAME, returning name."""
    path_info = environ.get('PATH_INFO', '')
    if not path_info: return None

    path_parts = path_info.split('/')
    path_parts[1:-1] = [p for p in path_parts[1:-1] if p and p!='.']
    name = path_parts[1]
    del path_parts[1]

    script_name = environ.get('SCRIPT_NAME', '')
    # process and concatenate path parts, deal with  '.', '..' 
    script_name = posixpath.normpath(script_name+'/'+name)
    if script_name.endswith('/'):
        script_name = script_name[:-1]
    # if path_info is empty, script_name should end with '/'
    if not name and not script_name.endswith('/'):
        script_name += '/'
    
    environ['SCRIPT_NAME'] = script_name
    environ['PATH_INFO'] = '/'.join(path_parts)

    # special case: '/.'
    if name=='.': name=None
    return name

def setup_testing_defaults(environ: dict) -> None:
    """Update 'environ' with trivial default values for test"""
    environ.setdefault('SERVER_NAME', '127.0.0.1')
    environ.setdefault('SERVER_PROTOCOL', 'HTTP/1.0')

    # 1. diff between HTTP_HOST and SERVER_NAME:
    environ.setdefault('HTTP_HOST', environ['SERVER_NAME'])
    environ.setdefault('REQUEST_METHOD', 'GET')

    if 'SCRIPT_NAME' not in environ and 'PATH_INFO' not in environ:
        environ.setdefault('SCRIPT_NAME', '')
        environ.setdefault('PATH_INFO', '/')

    environ.setdefault('wsgi.version', (1, 0))
    environ.setdefault('wsgi.run_once', 0)
    environ.setdefault('wsgi.multithread', 0)
    environ.setdefault('wsgi.multiprocess', 0)

    from io import StringIO
    environ.setdefault('wsgi.input', StringIO(""))
    environ.setdefault('wsgi.errors', StringIO())
    environ.setdefault('wsgi.url_scheme', guess_scheme(environ))
    
    if environ['wsgi.url_scheme'] == 'http':
        environ.setdefault('SERVER_PORT', '80')
    elif environ['wsgi.url_scheme'] == 'https':
        environ.setdefault('SERVER_PORT', '443')

_hoppish = {
    'connection': 1, 'keep-alive': 1, 'proxy-authenticate': 1,
    'proxy-authorization': 1, 'te': 1, 'trailers': 1, 'transfer-encoding': 1,
    'upgrade': 1
}.__contains__

def is_hop_by_hop(header_name: str) -> bool:
    """Return True if 'header_name' is a hop-by-hop header."""
    return _hoppish(header_name.lower())


