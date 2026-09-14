"""Discord credentials encrypted for this Windows user, outside the project."""
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


CREDENTIAL_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'FH6Auto'
SECRET = CREDENTIAL_DIR/'discord_webhook.dpapi'
CONFIG = CREDENTIAL_DIR/'discord_reports.json'


def validate_url(value):
    value = value.strip()
    url = urlsplit(value)
    if url.scheme != 'https' or url.netloc != 'discord.com' or url.query or url.fragment or not re.fullmatch(
            r'/api(?:/v\d+)?/webhooks/\d{15,22}/[A-Za-z0-9_-]{30,200}', url.path):
        raise ValueError('Enter a valid HTTPS Discord webhook URL')
    return value


class Blob(ctypes.Structure):
    _fields_ = [('size', wt.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(Blob)]
    function.restype = wt.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError('Windows could not access the encrypted Discord credential')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def settings():
    values = {'enabled': False, 'interval_seconds': 60, 'milestone': 10, 'mode': 'periodic'}
    if CONFIG.exists():
        values.update(json.loads(CONFIG.read_text(encoding='utf-8')))
    return values


def enabled():
    try:
        return bool(settings().get('enabled', False))
    except (OSError, ValueError):
        return False


def configure(url=None, *, enabled=True, interval_seconds=60):
    if type(interval_seconds) is not int or not 60 <= interval_seconds <= 3600:
        raise ValueError('Report interval must be between 1 and 60 minutes')
    if url:
        encrypted = protect(validate_url(url).encode('utf-8'))
        CREDENTIAL_DIR.mkdir(parents=True, exist_ok=True)
        temp = SECRET.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        temp.replace(SECRET)
    if enabled and not SECRET.exists():
        raise ValueError('Save a Discord webhook first')
    CREDENTIAL_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(enabled=bool(enabled), interval_seconds=interval_seconds,
                                    milestone=10, mode='periodic')), encoding='utf-8')
    temp.replace(CONFIG)


def webhook():
    try:
        return validate_url(protect(SECRET.read_bytes(), decrypt=True).decode('utf-8'))
    except Exception:
        raise RuntimeError('The saved Discord webhook is unavailable for this Windows account') from None
