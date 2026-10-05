"""Paginated 'card' listings (ЧСИ, АППК e-platform, НАП): each card holds one item link."""
from __future__ import annotations

import logging
import re

from .. import fetch
from ..textutil import abs_url, base_of, clean, soup_of

log = logging.getLogger(__name__)


def _card_for(a, item_rx: re.Pattern, base: str):
    """Highest ancestor that still contains links to only this one item."""
    target = abs_url(base, a["href"])
    node = a
    while node.parent is not None and node.parent.name not in ("body", "html"):
        parent = node.parent
        ids = {abs_url(base, x["href"]) for x in parent.find_all("a", href=True)
               if item_rx.search(x["href"])}
        if len(ids) > 1 or (ids and target not in ids):
            break
        node = parent
    return node


def parse_cards(page_url: str, html: str, item_rx: re.Pattern) -> list[dict]:
    soup = soup_of(html)
    page_url = base_of(soup, page_url)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        if not item_rx.search(a["href"]):
            continue
        url = abs_url(page_url, a["href"])
        if not url or url in seen:
            continue
        seen.add(url)
        card = _card_for(a, item_rx, page_url)
        text = clean(card.get_text(" "))[:3000]
        title = clean(a.get_text(" "))
        if len(title) < 25:
            title = text[:200]
        m = re.search(r"/(\d+)(?:[/?#]|$)", url)
        out.append({"key": m.group(1) if m else url, "url": url, "title": title[:300], "context": text})
    return out


def scan(src: dict, deadline_check) -> list[dict]:
    item_rx = re.compile(src["item_link"])
    items, seen_keys = [], set()
    for base in src["urls"]:
        empty_streak = 0
        for page_no in range(1, int(src.get("max_pages", 20)) + 1):
            if deadline_check():
                log.warning("%s: time budget reached at page %s", src["id"], page_no)
                break
            params = dict(src.get("extra_params") or {})
            if page_no > 1:
                params[src.get("page_param", "page")] = page_no
            try:
                p = fetch.get(base, params=params or None)
            except fetch.FetchError as e:
                if page_no == 1:
                    raise
                log.info("%s: stop at page %s (%s)", src["id"], page_no, e)
                break
            cards = parse_cards(p.url, p.text or "", item_rx)
            new = [c for c in cards if c["key"] not in seen_keys]
            if not new:
                empty_streak += 1
                if empty_streak >= 1:
                    break
            for c in new:
                seen_keys.add(c["key"])
                items.append(c)
    return items
