"""Load the full source list: central + oblasti + 265 municipalities (from Wikidata, cached weekly)."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests
import yaml

from .fetch import UA

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources"
AUTO = SRC / "municipalities.auto.json"
WEEK = 7 * 24 * 3600

Q_MUNI = """SELECT ?m ?mLabel ?site ?oblLabel WHERE {
  ?m wdt:P31 wd:Q1906268 .
  OPTIONAL { ?m wdt:P856 ?site }
  OPTIONAL { ?m wdt:P131 ?obl }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "bg,en". }
}"""
# Fallback if the class id ever changes: anything in Bulgaria labelled "Община …"
Q_MUNI_FALLBACK = """SELECT ?m ?mLabel ?site ?oblLabel WHERE {
  ?m wdt:P17 wd:Q219 ; rdfs:label ?l . FILTER(lang(?l)="bg" && STRSTARTS(?l, "Община "))
  OPTIONAL { ?m wdt:P856 ?site }
  OPTIONAL { ?m wdt:P131 ?obl }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "bg,en". }
}"""


def _slug(s: str) -> str:
    tr = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюя",
                  ["a","b","v","g","d","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u",
                   "f","h","ts","ch","sh","sht","a","","yu","ya"]))
    s = "".join(tr.get(c, c) for c in s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def refresh_municipalities(force: bool = False) -> list[dict]:
    cached = json.loads(AUTO.read_text("utf-8")) if AUTO.exists() else None
    if cached and not force and time.time() - cached.get("ts", 0) < WEEK:
        return cached["items"]
    rows = []
    for q in (Q_MUNI, Q_MUNI_FALLBACK):
        try:
            r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"},
                             headers={"User-Agent": UA}, timeout=120)
            r.raise_for_status()
            rows = r.json()["results"]["bindings"]
        except Exception as e:
            log.warning("Wikidata municipalities query failed: %s", e)
            rows = []
        if len(rows) > 200:
            break
    by_name: dict[str, dict] = {}
    for r in rows:
        name = r["mLabel"]["value"]
        if not (name.startswith("Община") or name == "Столична община"):
            name = "Община " + name
        rec = by_name.setdefault(name, {"name": name, "home": None, "oblast": None})
        site = r.get("site", {}).get("value")
        if site and not rec["home"]:
            rec["home"] = site
        obl = r.get("oblLabel", {}).get("value", "")
        if obl and not rec["oblast"]:
            rec["oblast"] = re.sub(r"^(?:Област|област)\s+", "", obl)
    data = sorted(by_name.values(), key=lambda x: x["name"])
    if len(data) > 200:
        AUTO.write_text(json.dumps({"ts": int(time.time()), "items": data}, ensure_ascii=False, indent=1), "utf-8")
    elif cached:
        return cached["items"]
    return data


def load_all() -> list[dict]:
    out: list[dict] = []
    for f in ("central.yaml", "oblasti.yaml"):
        out += yaml.safe_load((SRC / f).read_text("utf-8")).get("sources", [])
    overrides = {o["name"]: o for o in
                 (yaml.safe_load((SRC / "municipalities_overrides.yaml").read_text("utf-8")) or {}).get("overrides", [])}
    munis = refresh_municipalities()
    names = {m["name"] for m in munis}
    for name, o in overrides.items():
        if name not in names:
            munis.append({"name": name, "home": o.get("home"), "oblast": o.get("oblast")})
    for m in munis:
        o = overrides.get(m["name"], {})
        if o.get("enabled") is False:
            continue
        home = o.get("home") or m.get("home")
        urls = o.get("urls")
        if not home and not urls:
            continue
        out.append({
            "id": "ob-" + _slug(m["name"].replace("Община ", "")),
            "name": m["name"],
            "municipality": m["name"],
            "oblast": o.get("oblast") or m.get("oblast"),
            "category": "obshtina",
            "kind": "generic" if urls else "discover",
            "urls": urls or [],
            "home": home,
        })
    return [s for s in out if s.get("enabled", True) is not False]
