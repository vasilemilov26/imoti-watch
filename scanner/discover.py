"""Find the 'auctions / tenders / property sales' section(s) of an arbitrary institutional website."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from . import fetch
from .extract import is_relevant
from .textutil import abs_url, base_of, clean, soup_of

log = logging.getLogger(__name__)

POSITIVE = [
    (re.compile(r"търг", re.I), 6),
    (re.compile(r"продажб|продава|разпореждане|приватизац", re.I), 5),
    (re.compile(r"имот|собственост", re.I), 3),
    (re.compile(r"наем|аренд|концеси", re.I), 3),
    (re.compile(r"обяв|обявлени|съобщени", re.I), 2),
    (re.compile(r"конкурс", re.I), 1),
]
HREF_POS = re.compile(r"t[yaъ]?rg|torg|targ|auction|tender|prodaj|prodazh|imot|property|naem|obiav|obyav|koncesi", re.I)
NEGATIVE = re.compile(r"обществен\w* поръчк|профил на купувача|кариер|работа|длъжност|вакан|"
                      r"процедури по зоп|public procurement|buyer profile|jobs|career|новини$|news$", re.I)


def _score(text: str, href: str) -> int:
    if NEGATIVE.search(text) or NEGATIVE.search(href):
        return 0
    s = sum(w for rx, w in POSITIVE if rx.search(text))
    if HREF_POS.search(href):
        s += 3
    return s


def candidate_links(page_url: str, html: str, same_site: bool = True) -> list[tuple[int, str, str]]:
    soup = soup_of(html)
    base = base_of(soup, page_url)
    host = urlparse(page_url).netloc.replace("www.", "")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        url = abs_url(base, a["href"])
        if not url or url in seen:
            continue
        seen.add(url)
        if same_site and urlparse(url).netloc.replace("www.", "") != host:
            # allow the APPK platform and gov subdomains
            if "estate-sales.uslugi.io" not in url:
                continue
        text = clean(a.get_text(" ") or a.get("title") or "")
        sc = _score(text, url)
        if sc >= 5:
            out.append((sc, url, text[:120]))
    out.sort(key=lambda x: -x[0])
    return out


def count_relevant_blocks(html: str) -> int:
    soup = soup_of(html)
    n = 0
    for a in soup.find_all("a"):
        t = clean((a.parent.get_text(" ") if a.parent else "") + " " + a.get_text(" "))
        if is_relevant(t):
            n += 1
    return n


def discover(home: str, max_pages: int = 4) -> list[str]:
    """Return up to `max_pages` URLs that look like auction listing pages."""
    try:
        page = fetch.get(home)
    except fetch.FetchError as e:
        raise
    if not page.text:
        return []
    cands = candidate_links(page.url, page.text)
    level2: list[tuple[int, str, str]] = []
    checked: list[tuple[int, str]] = []
    for sc, url, _ in cands[:8]:
        try:
            p = fetch.get(url)
        except fetch.FetchError:
            continue
        if not p.text or not p.is_html:
            continue
        rel = count_relevant_blocks(p.text)
        checked.append((sc + rel * 2, p.url))
        for sc2, url2, t2 in candidate_links(p.url, p.text)[:6]:
            if url2 not in {c[1] for c in cands}:
                level2.append((sc2, url2, t2))
    level2.sort(key=lambda x: -x[0])
    for sc, url, _ in level2[:6]:
        try:
            p = fetch.get(url)
        except fetch.FetchError:
            continue
        if p.text and p.is_html:
            checked.append((sc + count_relevant_blocks(p.text) * 2, p.url))
    checked.sort(key=lambda x: -x[0])
    out = []
    for sc, url in checked:
        if sc >= 8 and url not in out:
            out.append(url)
        if len(out) >= max_pages:
            break
    return out
