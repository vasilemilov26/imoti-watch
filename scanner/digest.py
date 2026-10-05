"""Daily e-mail digest of new notices. python -m scanner.digest [--dry-run]

Secrets (GitHub → Settings → Secrets → Actions):
  SMTP_USER  – Gmail адрес, от който се праща
  SMTP_PASS  – Gmail „App password“ (16 знака)
  MAIL_TO    – получател(и), разделени със запетая
  DASHBOARD_URL – (по избор) линк към таблото
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "docs" / "data" / "items.json"
STATE = ROOT / "state" / "digest.json"
OUTDIR = ROOT / "docs" / "digests"

CAT = {"apk": "АППК", "chsi": "ЧСИ", "nap": "НАП", "darzhava": "Министерства/агенции", "oblast": "Области",
       "obshtina": "Общини", "dp": "Държавни дружества", "koncesii": "Концесии", "zemya": "Земеделска земя (ДПФ)",
       "agregator": "Агрегатор"}
DEAL = {"sale": "Продажба", "lease": "Наем/аренда", "concession": "Концесия"}
PTYPE = {"land": "Парцел/УПИ", "agri": "Земеделска", "building": "Сграда", "apartment": "Жилище",
         "garage": "Гараж", "other": "Друго"}


def highlighted(it: dict, f: dict) -> bool:
    h = f.get("highlight", {})
    text = (it.get("title", "") + " " + it.get("snippet", "")).lower()
    if any(k.lower() in text for k in h.get("keywords") or []):
        return True
    if h.get("oblasti") and (it.get("oblast") or "") not in h["oblasti"] and \
            not any(o.lower() in text for o in h["oblasti"]):
        return False
    if h.get("deals") and it.get("deal") not in h["deals"]:
        return False
    if h.get("types") and it.get("ptype") not in h["types"]:
        return False
    if h.get("max_price_eur") and (it.get("price_eur") or 0) > h["max_price_eur"]:
        return False
    if h.get("min_area_m2") and (it.get("area_m2") or 0) < h["min_area_m2"]:
        return False
    return True


def fmt_money(v):
    return f"{v:,.0f} €".replace(",", " ") if v else "—"


def fmt_area(v):
    if not v:
        return "—"
    return f"{v/1000:,.1f} дка".replace(",", " ") if v >= 10000 else f"{v:,.0f} м²".replace(",", " ")


def row(it: dict, star: bool) -> str:
    e = html.escape
    loc = ", ".join(x for x in [it.get("settlement"), it.get("municipality"), it.get("oblast")] if x)
    meta = " · ".join(x for x in [DEAL.get(it.get("deal"), ""), PTYPE.get(it.get("ptype"), ""), fmt_area(it.get("area_m2")),
                                   fmt_money(it.get("price_eur")),
                                   ("търг " + it["auction_date"]) if it.get("auction_date") else ""] if x and x != "—")
    cad = (" · " + ", ".join(it["cadastral_ids"][:3])) if it.get("cadastral_ids") else ""
    return (f'<tr><td style="padding:8px 6px;border-bottom:1px solid #e5e5e5;vertical-align:top">{"⭐" if star else ""}</td>'
            f'<td style="padding:8px 6px;border-bottom:1px solid #e5e5e5">'
            f'<a href="{e(it["url"])}" style="color:#0b57d0;font-weight:600;text-decoration:none">{e(it["title"][:160])}</a><br>'
            f'<span style="color:#444;font-size:13px">{e(meta)}{e(cad)}</span><br>'
            f'<span style="color:#777;font-size:12px">{e(loc)} — {e(it["source"])}</span></td></tr>')


def build(items: list[dict], since: str, f: dict) -> tuple[str, int, int, list]:
    new = [i for i in items if i["first_seen"] > since and not i.get("archived") and not i.get("irrelevant")]
    changed = [i for i in items if i["first_seen"] <= since and any(h["t"] > since and h["e"] != "нова обява"
                                                                    for h in i.get("history", []))]
    stars = {i["id"] for i in new if highlighted(i, f)}
    if f.get("digest", {}).get("only_highlighted"):
        new = [i for i in new if i["id"] in stars]
    new.sort(key=lambda i: (i["id"] not in stars, i["category"], i.get("oblast") or ""))
    new = new[: f.get("digest", {}).get("max_items", 300)]
    groups: dict[str, list] = {}
    for i in new:
        groups.setdefault(CAT.get(i["category"], i["category"]), []).append(i)
    dash = os.environ.get("DASHBOARD_URL", "")
    parts = [f'<div style="font-family:Arial,sans-serif;max-width:760px">'
             f'<h2 style="margin:0 0 4px">Нови търгове и продажби на имоти</h2>'
             f'<p style="color:#555;margin:0 0 12px">{len(new)} нови обяви ({len(stars)} ⭐ по вашите филтри)'
             + (f' · <a href="{html.escape(dash)}">отвори таблото и картата</a>' if dash else "") + "</p>"]
    for g, lst in groups.items():
        parts.append(f'<h3 style="margin:18px 0 4px;border-bottom:2px solid #222">{html.escape(g)} ({len(lst)})</h3><table style="border-collapse:collapse;width:100%">')
        parts += [row(i, i["id"] in stars) for i in lst]
        parts.append("</table>")
    if changed:
        parts.append('<h3 style="margin:18px 0 4px;border-bottom:2px solid #222">Промени по следени обяви</h3><ul>')
        for i in changed[:100]:
            ev = [h["e"] for h in i["history"] if h["t"] > since][-1]
            parts.append(f'<li><a href="{html.escape(i["url"])}">{html.escape(i["title"][:120])}</a> — <b>{html.escape(ev)}</b></li>')
        parts.append("</ul>")
    parts.append("</div>")
    return "".join(parts), len(new), len(stars), changed


def send(subject: str, body: str):
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("MAIL_TO")
    if not (user and pw and to):
        print("SMTP secrets missing – digest saved only to docs/digests/")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", 465)),
                          context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    items = json.loads(ITEMS.read_text("utf-8")) if ITEMS.exists() else []
    st = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {}
    first = "since" not in st
    since = st.get("since") or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    f = yaml.safe_load((ROOT / "filters.yaml").read_text("utf-8"))
    body, n, nstar, changed = build(items, since, f)
    today = dt.date.today().isoformat()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / f"{today}.html").write_text(body, "utf-8")
    if first:
        body = ('<p style="font-family:Arial;color:#a00">Първи бюлетин: показани са всички намерени при първото '
                'сканиране обяви. От утре – само новите.</p>') + body
    if not args.dry_run and (n or changed):
        send(f"Имоти на търг: {n} нови ({nstar} ⭐) – {today}", body)
    if not args.dry_run:
        st["since"] = max([i["first_seen"] for i in items] + [since])
        STATE.write_text(json.dumps(st), "utf-8")
    print(f"digest: {n} new, {nstar} highlighted, {len(changed)} changed")


if __name__ == "__main__":
    main()
