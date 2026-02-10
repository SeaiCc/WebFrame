
import typing as t

from mywerkzeug.exceptions import SecurityError
from mywerkzeug.urls import uri_to_iri

def host_is_trusted(hostname: str | None, trusted_list: t.Iterable[str]) -> bool:
    """Check if a host matches a list of trusted names.
    
    :param hostname: The name to check.
    :trusted_list: A list of valid names to match. If a name
        starts with a dot it will match all subdomains.
    >>>host_is_trusted(aaa.eg, [.eg])
    True
    """
    if not hostname: return False
    try:
        hostname = hostname.partition(":")[0].encode("idna").decode("ascii")
    except UnicodeEncodeError:
        return False
    if isinstance(trusted_list, str): trusted_list = [trusted_list]

    for ref in trusted_list:
        if ref.startswith("."):
            ref = ref[1:]
            suffix_match = True
        else:
            suffix_match = False
        try:
            ref = ref.partition(":")[0].encode("idna").decode("ascii")
        except UnicodeEncodeError:
            return False
        
        if ref == hostname or (suffix_match and hostname.endswith(f".{ref}")):
            return True
    
    return False

def get_host(
    scheme: str,
    host_header: str | None,
    server: tuple[str, int | None] | None = None,
    trusted_hosts: t.Iterable[str] | None = None,
) -> str:
    """Return the host for the given parameters.
    
    This first checks the (host_header). If it's not present, then
    (server) is used. The host will only contain the port if it is
    different than the standard port for the protocol.

    Optionally, verify that the host is trusted using
    :func:`host_is_trusted` and raise a
    :exc:`~werkzeug.exceptions.SecurityError` if it is not.

    :param scheme: The protocol the request used, like (https).
    :param host_header: The (Host) header value.
    :param server: Address of the server. (host, port), or (path, None)
        for unix sockets.
    :param trusted_hosts: A list of trusted host names.

    :return: Host with port if necessary.
    :raise (mywerkzeug.exceptions.SecurityError): If the host is not trusted.

    If (SEVER_NAME) is IPv6, it is wrapped in [].
    """
    host = ""

    if host_header is not None:
        host = host_header
    elif server is not None:
        host = server[0]

        if ":" in host and host[0] != "[":
            host = f"[{host}]"
        if server[1] is not None:
            host = f"{host}:{server[1]}"
    
    if scheme in {"http", "ws"} and host.endswith(":80"):
        host = host[:-3]
    elif scheme in {"https", "wss"} and host.endswith(":443"):
        host = host[:-4]

    if trusted_hosts is not None:
        if not host_is_trusted(host, trusted_hosts):
            raise SecurityError(f"Host {host!r} is not trusted.")
        
    return host

def get_current_url(
    scheme: str,
    host: str,
    root_path: str | None = None,
    path: str | None = None,
    query_string: bytes | None = None,
) -> str:
    """Recreate the URL for a request. If an optional part isn't 
    provided, it and subsequent parts are not included in the URL.

    :param scheme: The protocol the request used, like (https).
    :param host:
    :param root_path: Prefix that the application is mounted under. This
        prepended to (path).
    :param path: The path part of the URL after (root_path).
    :param query_string: The portion of the URL after the "?".
    """
    url = [scheme, "://", host]
    if root_path is None:
        url.append("/")
        return uri_to_iri("".join(url))