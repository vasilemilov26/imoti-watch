"""Main scan: python -m scanner.run [--only id1,id2] [--max-minutes 80] [--rediscover]"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import logging
import os
import time
import traceback
from pathlib import Path

from . import fetch, geo, llm
from .discover import discover
from .extract import detect_status, extract, is_relevant, is_stale
from .generic import detail_text, listing_candidates, pagination_links
from .parsers import cards
from .sources import load_all

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
STATE = ROOT / "state"
ITEMS_FILE = DATA / "items.json"
SOURCES_FILE = DATA / "sources.json"
DISC_FILE = STATE / "discovered.json"
REDISCOVER_DAYS = 14
DETAIL_LIMIT_PER_SOURCE = 25
GONE_AFTER_MISSES = 2

log = logging.getLogger("scanner")
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
NOW_S = NOW.isoformat()


def jload(p: Path, default):
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return default


def jsave(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")
    tmp.replace(p)


class Ctx:
    def __init__(self, max_minutes: float):
        self.deadline = time.time() + max_minutes * 60

    def out_of_time(self) -> bool:
        return time.time() > self.deadline


def listing_urls(src: dict, disc: dict, force: bool) -> list[str]:
    if src.get("urls"):
        return list(src["urls"])
    d = disc.get(src["id"])
    fresh = d and (time.time() - d.get("ts", 0) < REDISCOVER_DAYS * 86400) and d.get("urls")
    if fresh and not force:
        return d["urls"]
    urls = discover(src["home"])
    disc[src["id"]] = {"urls": urls, "ts": int(time.time())}
    return urls


def scan_source(src: dict, disc: dict, ctx: Ctx, force_disc: bool) -> dict:
    """Return {'ok', 'error', 'pages', 'candidates': [...], 'complete'}"""
    res = {"ok": False, "error": None, "pages": [], "candidates": [], "complete": True}
    try:
        if src["kind"] == "cards":
            res["candidates"] = cards.scan(src, ctx.out_of_time)
            res["pages"] = src["urls"]
            res["complete"] = not ctx.out_of_time()
        else:
            urls = listing_urls(src, disc, force_disc)
            res["pages"] = urls
            if not urls:
                res["error"] = "не е намерена секция с търгове (добавете URL ръчно)"
                return res
            seen = set()
            todo = list(urls)
            visited = 0
            while todo and visited < len(urls) + 2:
                u = todo.pop(0)
                visited += 1
                p = fetch.get(u)
                if not p.text:
                    continue
                for c in listing_candidates(p.url, p.text):
                    if c["key"] not in seen:
                        seen.add(c["key"])
                        res["candidates"].append(c)
                if visited <= len(urls):  # follow page 2 of each listing once
                    todo += [x for x in pagination_links(p.url, p.text, 1) if x not in urls]
        res["ok"] = True
    except fetch.FetchError as e:
        res["error"] = str(e)
        if src["kind"] == "discover" and src["id"] in disc:
            disc[src["id"]]["ts"] = 0  # rediscover next time
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
        log.debug(traceback.format_exc())
    return res


def build_item(src: dict, cand: dict, fetch_detail: bool) -> dict:
    group = src.get("group", src["id"])
    text = cand["context"]
    docs = []
    if (fetch_detail and cand["url"] and src["kind"] != "cards") or src.get("detail"):
        dtext, docs = detail_text(cand["url"], "")
        text = (cand["context"] + " " + dtext).strip()
    fields = extract(text)
    item = {
        "id": f"{group}:{cand['key']}",
        "source_id": src["id"], "source": src["name"], "category": src["category"],
        "url": cand["url"], "title": cand["title"], "snippet": text[:700],
        "first_seen": NOW_S, "last_seen": NOW_S, "misses": 0, "status": "active",
        "oblast": src.get("oblast"), "municipality": src.get("municipality"),
        "docs": docs, "history": [{"t": NOW_S, "e": "нова обява"}],
    }
    for k, v in fields.items():
        if k == "status_hint":
            continue
        item[k] = v
    if fields.get("status_hint") and src.get("results_only"):
        item["status"] = fields["status_hint"]
    if llm.enabled() and src["kind"] != "cards":
        a = llm.analyse(text)
        if a:
            if a.get("relevant") is False:
                item["irrelevant"] = True
            for k in ("deal", "ptype", "settlement", "municipality", "oblast", "area_m2", "price_eur",
                      "auction_date", "deadline"):
                if a.get(k):
                    item[k] = a[k]
            if a.get("title"):
                item["title"] = a["title"]
            if a.get("cadastral_ids"):
                item["cadastral_ids"] = a["cadastral_ids"]
                item["ekatte"] = str(a["cadastral_ids"][0]).split(".")[0]
            if a.get("status"):
                item["status"] = a["status"]
    if is_stale(fields) and not item.get("auction_date", "") >= dt.date.today().isoformat():
        item["archived"] = True
    geo.locate(item)
    return item


def merge(items: dict, src: dict, res: dict, ctx: Ctx) -> int:
    group = src.get("group", src["id"])
    new = 0
    details_done = 0
    seen_ids = set()
    for c in res["candidates"]:
        iid = f"{group}:{c['key']}"
        seen_ids.add(iid)
        it = items.get(iid)
        if it:
            it["last_seen"] = NOW_S
            it["misses"] = 0
            if it["status"] == "gone":
                it["status"] = "active"
                it["history"].append({"t": NOW_S, "e": "отново публикувана"})
            st = detect_status(c["context"]) if src.get("results_only") else None
            if st and it["status"] != st:
                it["status"] = st
                it["history"].append({"t": NOW_S, "e": {"unsuccessful": "търгът е неуспешен",
                                                        "cancelled": "прекратен", "sold": "продаден/спечелен"}[st]})
            continue
        if ctx.out_of_time():
            break
        do_detail = details_done < DETAIL_LIMIT_PER_SOURCE
        if do_detail and src["kind"] != "cards":
            details_done += 1
        try:
            it = build_item(src, c, do_detail)
        except Exception as e:
            log.warning("%s: build failed %s: %s", src["id"], c.get("url"), e)
            continue
        if src.get("results_only"):
            it["archived"] = it.get("archived", False)
        if src["kind"] != "cards" and not is_relevant(it["snippet"] + " " + it["title"] + " " + c["context"]) and not it.get("cadastral_ids"):
            continue
        items[iid] = it
        new += 1
    # Disappeared items (only for complete, successful scans of the listing)
    if res["ok"] and res["complete"] and not src.get("results_only") and res["candidates"]:
        for it in items.values():
            if it["source_id"] == src["id"] and it["id"] not in seen_ids and it["status"] == "active":
                it["misses"] = it.get("misses", 0) + 1
                if it["misses"] >= GONE_AFTER_MISSES:
                    it["status"] = "gone"
                    it["history"].append({"t": NOW_S, "e": "обявата е премахната от сайта"})
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--max-minutes", type=float, default=float(os.environ.get("MAX_MINUTES", 80)))
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctx = Ctx(args.max_minutes)

    items = {i["id"]: i for i in jload(ITEMS_FILE, [])}
    health = {h["id"]: h for h in jload(SOURCES_FILE, [])}
    disc = jload(DISC_FILE, {})
    srcs = load_all()
    if args.only:
        wanted = set(args.only.split(","))
        srcs = [s for s in srcs if s["id"] in wanted]
    log.info("sources: %d, known items: %d, LLM: %s", len(srcs), len(items), llm.enabled())

    # cards (big registers) first so they always get time, then the rest in parallel
    srcs.sort(key=lambda s: 0 if s["kind"] == "cards" else 1)
    results = {}
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(scan_source, s, disc, ctx, args.rediscover): s for s in srcs}
        for f in cf.as_completed(futs):
            s = futs[f]
            results[s["id"]] = (s, f.result())

    total_new = 0
    order = sorted(results.values(), key=lambda x: 1 if x[0].get("results_only") else 0)
    for s, r in order:
        n = merge(items, s, r, ctx) if r["ok"] else 0
        total_new += n
        h = health.get(s["id"], {})
        h.update({"id": s["id"], "name": s["name"], "category": s["category"],
                  "oblast": s.get("oblast"), "home": s.get("home"), "pages": r["pages"],
                  "ok": r["ok"], "error": r["error"], "found": len(r["candidates"]), "new": n,
                  "last_run": NOW_S})
        if r["ok"]:
            h["last_ok"] = NOW_S
        health[s["id"]] = h
        log.info("%-28s ok=%s found=%d new=%d %s", s["id"][:28], r["ok"], len(r["candidates"]), n, r["error"] or "")

    # prune very old inactive items
    cutoff = (NOW - dt.timedelta(days=400)).isoformat()
    items = {k: v for k, v in items.items() if v["last_seen"] >= cutoff or v["status"] == "active"}
    geo.save_cache()
    jsave(ITEMS_FILE, sorted(items.values(), key=lambda x: x["first_seen"], reverse=True))
    jsave(SOURCES_FILE, sorted(health.values(), key=lambda x: (x["category"], x["name"])))
    jsave(DISC_FILE, disc)
    jsave(DATA / "meta.json", {"last_scan": NOW_S, "items": len(items), "new_this_run": total_new,
                               "sources": len(health), "sources_ok": sum(1 for h in health.values() if h.get("ok"))})
    log.info("done: %d new, %d total", total_new, len(items))


if __name__ == "__main__":
    main()
