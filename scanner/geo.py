"""Approximate coordinates: EKATTE (first 5 digits of the cadastral id) → settlement, else Nominatim."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from .fetch import UA

log = logging.getLogger(__name__)
STATE = Path(__file__).resolve().parent.parent / "state"
STATE.mkdir(exist_ok=True)
EKATTE_FILE = STATE / "ekatte.json"
CACHE_FILE = STATE / "geocache.json"
WDQS = "https://query.wikidata.org/sparql"

_ekatte: dict | None = None
_cache: dict | None = None
_nominatim_calls = 0
NOMINATIM_LIMIT = 80


def _sparql(q: str) -> list[dict]:
    r = requests.get(WDQS, params={"query": q, "format": "json"},
                     headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def load_ekatte(refresh: bool = False) -> dict:
    global _ekatte
    if _ekatte is not None and not refresh:
        return _ekatte
    if EKATTE_FILE.exists() and not refresh:
        _ekatte = json.loads(EKATTE_FILE.read_text("utf-8"))
        if _ekatte:
            return _ekatte
    data = {}
    try:
        rows = _sparql("""SELECT ?code ?coord ?l WHERE { ?s wdt:P3990 ?code ; wdt:P625 ?coord .
                          OPTIONAL { ?s rdfs:label ?l FILTER(lang(?l)="bg") } }""")
        for r in rows:
            c = r["coord"]["value"]  # Point(lon lat)
            lon, lat = c[c.find("(") + 1:c.find(")")].split()
            data[r["code"]["value"].zfill(5)] = [round(float(lat), 5), round(float(lon), 5),
                                                 r.get("l", {}).get("value", "")]
        log.info("EKATTE: %d settlements from Wikidata", len(data))
    except Exception as e:
        log.warning("EKATTE load failed: %s", e)
    if data:
        EKATTE_FILE.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    _ekatte = data
    return data


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE_FILE.read_text("utf-8")) if CACHE_FILE.exists() else {}
    return _cache


def save_cache():
    if _cache is not None:
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=0), "utf-8")


def nominatim(query: str):
    global _nominatim_calls
    cache = _load_cache()
    if query in cache:
        return cache[query]
    if _nominatim_calls >= NOMINATIM_LIMIT:
        return None
    _nominatim_calls += 1
    time.sleep(1.1)
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": query, "format": "json", "limit": 1, "countrycodes": "bg"},
                         headers={"User-Agent": UA}, timeout=30)
        res = r.json()
        val = [round(float(res[0]["lat"]), 5), round(float(res[0]["lon"]), 5)] if res else None
    except Exception:
        val = None
    cache[query] = val
    return val


def locate(item: dict) -> None:
    """Fill item['lat'], item['lon'], item['settlement'] (if missing), item['geo_precision']."""
    if item.get("lat"):
        return
    ek = item.get("ekatte")
    if ek:
        rec = load_ekatte().get(ek)
        if rec:
            item["lat"], item["lon"] = rec[0], rec[1]
            item.setdefault("settlement", rec[2])
            item["geo_precision"] = "settlement"
            return
    parts = []
    if item.get("settlement"):
        parts.append(item["settlement"].replace("гр. ", "").replace("с. ", ""))
    if item.get("municipality"):
        parts.append(item["municipality"].replace("Община ", ""))
    if item.get("oblast"):
        parts.append("област " + item["oblast"])
    if not parts:
        return
    ll = nominatim(", ".join(parts) + ", България")
    if ll:
        item["lat"], item["lon"] = ll
        item["geo_precision"] = "settlement" if item.get("settlement") else "municipality"
