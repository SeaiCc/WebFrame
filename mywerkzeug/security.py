import os
import posixpath
import secrets

SALT_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# 获取系统除了正斜杠（/）之外的所有路径分隔符
_os_alt_seps: list[str] = list(
    sep for sep in [os.sep, os.path.altsep] if sep is not None and sep != "/"
)
_winodws_device_files = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}

def gen_salt(length: int) -> str:
    """生成一个带有具体```length```的SALT_CHARS的随机字符串"""
    if length <= 0:
        raise ValueError("Salt length must be greater than 1.")
    return "".join(secrets.choice(SALT_CHARS) for _ in range(length))

def safe_join(directory: str, *pathnames: str) -> str | None:
    """安全地拼接零至多个未信任的路径部分到一个路径以避免转义基本目录。
    
    :param directory: 可信的基本目录。
    :param pathnames: 与基础路径相关的未信任的路径组件。
    :return: 安全的路径，或``None``。
    """
    if not directory:
        # Ensure we end up with ./path if directory="" is given,
        # otherwise the first untrusted part could become trusted.
        directory = "."

    parts = [directory]

    for filename in pathnames:
        if filename != "":
            filename = posixpath.normpath(filename)
        
        if (
            any(sep in filename for sep in _os_alt_seps)
            or (
                os.name == "nt"
                and os.path.splitext(filename)[0].upper() in _windows_device_files
            )
            or os.path.isabs(filename)
            # ntpath.isabs doesn't catch this on Python < 3.11
            or filename.startswith("/")
            or filename == ".."
            or filename.startswith("../")
        ):
            return None
        
        parts.append(filename)
    
    return posixpath.join(*parts)
    

            