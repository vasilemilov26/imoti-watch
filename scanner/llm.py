"""Optional: Claude API for messy notices (needs ANTHROPIC_API_KEY secret). Without it, rules only."""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger(__name__)
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
MAX_CALLS = int(os.environ.get("LLM_MAX_CALLS", "200"))
_calls = 0

PROMPT = """Ти анализираш обява от български институционален сайт. Върни САМО JSON обект с ключове:
relevant (true ако обявата е за продажба, наем, аренда, концесия или публична продан на НЕДВИЖИМ имот/земя/сграда; false за обществени поръчки, работа, МПС, движими вещи, дървесина, новини),
deal ("sale"|"lease"|"concession"), ptype ("land"|"agri"|"building"|"apartment"|"garage"|"other"),
title (кратко заглавие до 120 знака на български), settlement (напр. "гр. Козлодуй"), municipality, oblast,
cadastral_ids (списък), area_m2 (число), price_eur (начална цена в EUR без ДДС; лева→EUR по 1.95583),
auction_date (YYYY-MM-DD), deadline (YYYY-MM-DD), status (null|"unsuccessful"|"cancelled"|"sold").
Липсващо = null.

ОБЯВА:
"""


def enabled() -> bool:
    return bool(API_KEY) and _calls < MAX_CALLS


def analyse(text: str) -> dict | None:
    global _calls
    if not enabled():
        return None
    _calls += 1
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
            "x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 600,
                  "messages": [{"role": "user", "content": PROMPT + text[:7000]}]})
        r.raise_for_status()
        out = r.json()["content"][0]["text"]
        out = out[out.find("{"): out.rfind("}") + 1]
        return json.loads(out)
    except Exception as e:
        log.warning("LLM failed: %s", e)
        return None
