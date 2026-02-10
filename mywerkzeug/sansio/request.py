
from mywerkzeug.datastructures import Headers

class Request:
    """Represents the non-IO parts of a HTTP request, including the
    method, URL info, and headers.

    This class is not meant for general use. It should only be used when
    implementing WSGI, ASGI, or other HTTP application spec. Werkzeug 
    provides a WSGI implementation at :cls:`werkzeug.wrappers.Request`.

    :param method: The method the request was made with, such as (GET)
    :param scheme: The URL scheme of the protocol the request used, such
        as (https) or (wss).
    :param server: The address of of the server. (host, port), (path, None)
        for unix sockets, or (None) if not known.
    :param root_path: The prefix that the application is mounted under.
        This is prepended to generated URLs, but is not part of route matching.
    :param path: The path part of the URL after (root_path)
    :param query_string: The part of the URL after the "?".
    :param headers: The headers received with the request.
    :param remote_addr: The address of the client sending the reqeust.

    (charset), (url_charset), (encoding_errors) were removed in version3.0
    """
    
    def __init__(
        self,
        method: str,
        scheme: str,
        server: tuple[str, int | None] | None,
        root_path: str,
        path: str,
        query_string: bytes,
        headers: Headers,
        remote_addr: str | None,
    ) -> None:
        # Request method, such as (GET).
        self.method = method.upper()
        # URL scheme, such as (https) or (wss)
        self.scheme = scheme
        # The address of the server. (host, port), (path, None)
        self.server = server
        # The prefix that the appliction is mounted under, without a
        # trailing slash. :attriubet (path) comes after this
        self.root_path = root_path.rstrip("/")
        # The path part of the URL after attribute (root_path). This is
        # the path used for routing within the application.
        self.path = "/" + path.lstrip("/")
        # Part after "?". Use attribute (args) for the parsed values.
        self.query_string = query_string
        # The headers received with the reqeust
        self.headers = headers
        # The address of the client sending the request.
        self.remote_addr = remote_addr
        
        
