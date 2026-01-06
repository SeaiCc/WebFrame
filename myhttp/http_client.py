import email.message
import email.parser

_MAXLINE = 65536
_MAXHEADERS = 100

class HTTPMessage(email.message.Message):


    def getallmatchingheaders(self, name):
        """Find all header lines matching a give header name."""
        name = name.lower() + ':'
        n = len(name)
        lst = []
        hit = 0
        for line in self.keys():
            if line[:n].lower() == name:
                hit = 1
            elif not line[:1].isspace():
                hit = 0
            if hit: 
                lst.append(line)
        return lst

def _read_headers(fp):
    """Reads potential header lines into a list from a file pointer.
    
    Length of line is limited by _MAXLINE, and number of headers is 
    limited by _MAXHEADERS.
    """
    headers = []
    while True:
        line = fp.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise LineTooLong("header line")
        headers.append(line)
        if len(headers) > _MAXHEADERS:
            raise HTTPException("got more than %d headers" % _MAXHEADERS)
        if line in (b'\r\n', b'\n', b''): break
    return headers

def parse_headers(fp, _class=HTTPMessage):
    """Parse only RFC2822 headers from a file pointer.
    
    email Parser wants to see strings rather than bytes.
    But a TextIOWrapper around self.rfile would buffer too many bytes
    from the stream, bytes which we later need to read as bytes.
    So we read the correct bytes here, as bytes, for email Parser to
    parse.
    """
    headers = _read_headers(fp)
    hstring = b''.join(headers).decode('iso-8859-1')
    return email.parser.Parser(_class=_class).parsestr(hstring)

class HTTPException(Exception):
    # Subclasses that define an __init__ must call Exception.__init__
    pass

class LineTooLong(HTTPException):
    def __init__(self, line_type):
        HTTPException.__init__(self, "got more than %d bytes when reading %s"
                                     % (_MAXLINE, line_type))
        
