"""Generic listing-page scanner: works on any 'Търгове/Обяви' page without a site-specific parser."""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

from . import fetch
from .extract import is_relevant
from .textutil import abs_url, block_for_link, clean, is_doc, soup_of, strip_noise

log = logging.getLogger(__name__)
NEG_ANCHOR = re.compile(r"обществен\w*\s+поръчк|профил на купувача|доставка на|длъжност|конкурс за работа", re.I)
PAGER_RE = re.compile(r"^(?:\d{1,3}|›|»|>|следващ\w*|next|напред)$", re.I)


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def listing_candidates(page_url: str, html: str) -> list[dict]:
    """Return candidate notices on a listing page: [{key,url,title,context}]"""
    soup = strip_noise(soup_of(html))
    root = soup.find("main") or soup.find("article") or soup.body or soup
    out, seen = [], set()
    for a in root.find_all("a", href=True):
        url = abs_url(page_url, a["href"])
        if not url or url in seen:
            continue
        atext = clean(a.get_text(" ") or a.get("title") or "")
        if PAGER_RE.match(atext):
            continue
        block = block_for_link(a)
        ctx = clean(block.get_text(" "))[:1500]
        if NEG_ANCHOR.search(atext) or not is_relevant(ctx + " " + atext):
            continue
        seen.add(url)
        title = atext if len(atext) > 25 else ctx[:220]
        out.append({"key": _key(url), "url": url, "title": title[:300], "context": ctx})
    # Notices published inline without links (paragraphs / table rows)
    if not out:
        for blk in root.find_all(["p", "tr", "li", "div"]):
            if blk.find(["p", "tr", "li", "div"]):
                continue
            t = clean(blk.get_text(" "))
            if 80 <= len(t) <= 3000 and is_relevant(t):
                k = _key(page_url, t[:200])
                if k in seen:
                    continue
                seen.add(k)
                out.append({"key": k, "url": page_url, "title": t[:220], "context": t})
    return out


def pagination_links(page_url: str, html: str, limit: int = 2) -> list[str]:
    soup = soup_of(html)
    host = urlparse(page_url).netloc
    out = []
    for a in soup.find_all("a", href=True):
        t = clean(a.get_text(" "))
        if t in ("2", "3") or re.match(r"^(следващ\w*|›|»|next)$", t, re.I):
            u = abs_url(page_url, a["href"])
            if u and urlparse(u).netloc == host and u != page_url and u not in out:
                out.append(u)
        if len(out) >= limit:
            break
    return out


def detail_text(url: str, fallback: str) -> tuple[str, list[str]]:
    """Fetch the notice (HTML or document). Returns (text, attached_doc_urls)."""
    from .textutil import doc_text, main_text
    try:
        p = fetch.get(url)
    except fetch.FetchError:
        return fallback, []
    if is_doc(p.url) or (p.ctype and not p.is_html and "text" not in p.ctype):
        t = doc_text(p.content, p.url, p.ctype)
        return (fallback + " " + t).strip(), [p.url]
    if not p.text:
        return fallback, []
    txt = main_text(p.text)
    docs = []
    soup = soup_of(p.text)
    for a in soup.find_all("a", href=True):
        u = abs_url(p.url, a["href"])
        if u and is_doc(u) and u not in docs:
            docs.append(u)
    # If the HTML page is thin, read the first attached document (обявата обикновено е PDF)
    if len(txt) < 400 and docs:
        try:
            d = fetch.get(docs[0])
            txt += " " + doc_text(d.content, d.url, d.ctype)
        except fetch.FetchError:
            pass
    return txt[:30000], docs[:10]
