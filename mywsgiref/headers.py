"""
Much of this module is red-handedly pilfered from email.Message in the stdlib,
so portions are Copyright (C) 2001,2002 Python Software Foundation, and were
written by Barry Warsaw.
"""

from typing import List
import re
tspecials = re.compile(r'[ \(\)<>@,;:\\"/\[\]\?=]')


def _formatparam(param, value=None, quote=1):
    """Return a key=value pair."""
    if value is not None and len(value) > 0:
        if quote or tspecials.search(value):
            value = value.replace('\\', '\\\\').replace('"', r'\"')
            return '%s="%"s' % (param, value)
        else:
            return '%s=%s' % (param, value)
    else:
        return param

class Headers:
    """Manage a collection of HTTP response headers"""
    def __init__(self, headers):
        if type(headers) is not list:
            raise TypeError("headers must be a list")
        self._headers = headers

    def __len__(self):
        """Return the total number of headers, including duplicates."""
        return len(self._headers)

    def __setitem__(self, name, val):
        del self[name]
        self._headers.append((name, val))
    
    def __delitem__(self, name):
        """Delete all occurrences of a header, if present.
        Don not raise if key not exist.
        """
        name = name.lower()
        self._headers[:] = [kv for kv in self._headers if kv[0].lower()!=name]

    def __getitem__(self, name):
        """Get first value of key 'name'."""
        return self.get(name)
    
    def has_key(self, name):
        """Return true if has key 'name'."""
        return self.get(name) is not None
    
    # ??
    __contains__ = has_key

    def get_all(self, name):
        """Return a list of all values of key 'name'.
        if not exist return empty list.

        sort by they appeared in the original header
        list or were added to this instance, and may contain duplicates
        """
        name = name.lower()
        return [kv[1] for kv in self._headers if kv[0].lower()==name]
    
    def get(self, name, default=None):
        """Get first value of key 'name' or default."""
        name = name.lower()
        for k, v in self._headers:
            if k.lower()==name: return v
        
        return default
        
    def key(self):
        """Return a list of all keys."""
        return [kv[0] for kv in self._headers]
        
    def values(self):
        """Return a list of all values."""
        return [kv[1] for kv in self._headers]
    
    def items(self):
        """Return a list of all (key, value) pairs."""
        return self._headers[:]
    
    def __repr__(self):
        return "Headers(%s)" % self._headers
    
    def __str__(self):
        """Return the formatted headers, suitable for HTTP transmission."""
        return '\r\n'.join(["%s: %s" % kv for kv in self._headers] + ['',''])
    
    def setdefault(self,name,value):
        """Return first match header value for 'name', or 'value',
        if not exist, add to self._headers."""
        result = self.get(name)
        if result is None:
            self._headers.append((name, value))
        else:
            return result
    
    def add_header(self, _name, _value, **_param):
        """Extended header setting.
        
        Examples: Content-Type: application/json; charset=utf-8
        """
        parts = []
        
        if _value is not None:
            parts.append(_value)

        for k, v in _param.items():
            if v is None:
                parts.append(k.replace('_', '-'))
            else:
                parts.append(_formatparam(k.replace('_', '-'), v))
        self._headers.append((_name, "; ".join(parts)))
