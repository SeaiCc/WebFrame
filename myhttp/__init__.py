from enum import IntEnum

class HTTPStatus(IntEnum):

    def __new__(cls, value, phrase, description=''):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.phrase = phrase
        obj.description = description
        return obj
    
    # informational
    CONTINUE = 100, 'Continue', 'Request received, please continue'
    

    # client error
    BAD_REQUEST = (400, 'Bad Request',
        'Bad request syntax or unsupported method')
    REQUEST_URI_TOO_LONG = (414, 'Request-URI Too Long',
        'URI is too Long')
    
    REQUEST_HEADER_FILEDS_TOO_LARGE = (431,
        'Request Header Fields Too Large',
        'The server is unwilling to process the request because its header '
        'fields are too large')
    
    # server errors
    HTTP_VERSION_NOT_SUPPORTED = (505, 'HTTP Version Not Supported',
        'Cannot fulfill request')
    

