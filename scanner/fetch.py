"""HTTP fetching: polite, tolerant to broken Bulgarian gov TLS setups and cp1251 pages."""
from __future__ import annotations

import io
import logging
import threading
import time
from urllib.parse import urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; ImotiWatch/1.0; public auction notices monitor)"
TIMEOUT = 25
MAX_BYTES = 12 * 1024 * 1024
PER_HOST_DELAY = 1.0  # seconds between requests to the same host

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "bg,en;q=0.7"})
_adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64,
                                         max_retries=urllib3.Retry(total=2, backoff_factor=1.5,
                                                                   status_forcelist=[502, 503, 504]))
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

_host_locks: dict[str, threading.Lock] = {}
_host_last: dict[str, float] = {}
_glock = threading.Lock()


class FetchError(Exception):
    pass


class Page:
    def __init__(self, url: str, status: int, content: bytes, ctype: str, text: str | None):
        self.url, self.status, self.content, self.ctype, self.text = url, status, content, ctype, text

    @property
    def is_html(self) -> bool:
        return "html" in self.ctype or (self.text is not None and "<html" in self.text[:2000].lower())


def _throttle(host: str):
    with _glock:
        lock = _host_locks.setdefault(host, threading.Lock())
    lock.acquire()
    try:
        wait = PER_HOST_DELAY - (time.time() - _host_last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.time()
    finally:
        lock.release()


def _decode(content: bytes, resp: requests.Response) -> str:
    enc = None
    ct = resp.headers.get("Content-Type", "")
    if "charset=" in ct.lower():
        enc = ct.lower().split("charset=")[-1].split(";")[0].strip()
    if not enc:
        head = content[:4000].decode("ascii", "ignore").lower()
        for marker in ("charset=", "encoding="):
            i = head.find(marker)
            if i >= 0:
                enc = head[i + len(marker):].strip("\"' ").split("\"")[0].split("'")[0].split(";")[0].split(">")[0].strip()
                break
    for e in filter(None, [enc, "utf-8", "cp1251"]):
        try:
            return content.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def get(url: str, params: dict | None = None) -> Page:
    host = urlparse(url).netloc
    _throttle(host)
    verify = True
    for attempt in range(2):
        try:
            r = _session.get(url, params=params, timeout=TIMEOUT, verify=verify, stream=True,
                             allow_redirects=True)
            buf = io.BytesIO()
            for chunk in r.iter_content(65536):
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    break
            content = buf.getvalue()
            ctype = r.headers.get("Content-Type", "").lower()
            text = None
            if "html" in ctype or "text" in ctype or "xml" in ctype or "json" in ctype or not ctype:
                text = _decode(content, r)
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} {url}")
            return Page(r.url, r.status_code, content, ctype, text)
        except requests.exceptions.SSLError:
            if verify:
                verify = False  # many .government.bg sites ship incomplete chains
                continue
            raise FetchError(f"SSL error {url}")
        except requests.exceptions.RequestException as e:
            raise FetchError(f"{type(e).__name__}: {url}") from e
    raise FetchError(f"failed {url}")
