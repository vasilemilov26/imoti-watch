"""Rule-based field extraction from Bulgarian auction/tender notices."""
from __future__ import annotations

import datetime as dt
import re

BGN_PER_EUR = 1.95583

ACTION_RE = re.compile(
    r"търг|публичн\w*\s+(?:продан|продажб|оповест)|продажба|продава|наем|аренд|концеси|"
    r"разпореждане|приватизац|конкурс за (?:продажба|отдаване|наем)|публично оповестен конкурс|"
    r"явен търг|тайно наддаване|електронен търг", re.I)
PROPERTY_RE = re.compile(
    r"имот|упи\b|урегулиран|поземлен|сград|апартамент|помещени|земеделск|земя|земи|терен|парцел|"
    r"идентификатор|кв\.?\s?м|м2|дка|декар|магазин|офис|гараж|склад|хале|пасищ|ливад|нив[аи]|"
    r"площ|къща|жилищ|ателие|павилион|база\b|почивна станция|казарм|обект", re.I)
NEGATIVE_RE = re.compile(
    r"обществен\w*\s+поръчк|\bЗОП\b|длъжност|служител|кандидат\w* за работа|свободн\w* работн|"
    r"конкурс за (?:директор|длъжност|назначаване)|доставка на|строително-?монтажн|"
    r"дървесина|дърва за огрев|прогнозни количества|"
    r"моторно превозно|\bМПС\b|автомобил|движими вещи|лекарств|"
    r"избори|бюджет\b|детск\w* градин", re.I)
# Things that clearly are about vehicles etc. only → negative, unless property words are strong.
STRONG_PROPERTY_RE = re.compile(r"идентификатор|поземлен|упи\b|апартамент|сград|земеделск|кв\.?\s?м|дка", re.I)

CAD_RE = re.compile(r"(?<![\d.])(\d{5})\.(\d{1,5})\.(\d{1,5})(?:\.(\d{1,4}))?(?:\.(\d{1,4}))?(?![\d])")
UPI_RE = re.compile(r"УПИ\s+([IVXLCDM]+[\-–,\s\d]*|[\d\-–,\s]+)[^.;]{0,40}?кв(?:\.|артал)\s*(\d+[а-яА-Я]?)", re.I)
NUM = r"\d{1,3}(?:[  .,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
AREA_RE = re.compile(rf"({NUM})\s*(кв\.?\s?м\.?|кв\.\s?метра|квадратни метра|м2|m2|м²|дка\.?|декара)", re.I)
PRICE_CTX_RE = re.compile(
    rf"(?:начална|първоначална|продажна|минимална|наемна|тръжна)?\s*(?:тръжна\s+)?(?:цена|наем|стойност)[^0-9]{{0,80}}?({NUM})\s*(лв\.?|лева|евро|eur\b|€|bgn)", re.I)
PRICE_ANY_RE = re.compile(rf"({NUM})\s*(лв\.?|лева|евро|EUR\b|€|BGN)", re.I)
STEP_RE = re.compile(rf"стъпка[^0-9]{{0,40}}({NUM})\s*(лв\.?|лева|евро|eur|€)", re.I)
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](20\d{2}|\d{2})(?!\d)")
DATE_WORD_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)\s+(20\d{2})", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    "януари февруари март април май юни юли август септември октомври ноември декември".split())}
AUCTION_DATE_CTX = re.compile(r"(?:търг\w*|наддаване\w*)\s+(?:ще\s+се\s+проведе|се\s+провежда|на\s+дата|насрочен)|дата\s+на\s+(?:търга|провеждане)|насрочен\w*\s+за|провеждане\s+на\s+търга", re.I)
DEADLINE_CTX = re.compile(r"срок\w*\s+(?:за\s+)?(?:подаване|закупуване|депозиране)|до\s+\d{1,2}[.:]\d{2}\s*ч", re.I)
SETTLEMENT_RE = re.compile(r"\b(гр\.|с\.|град|село|к\.к\.)\s?([А-Я][а-я]+(?:[\s-][А-Я][а-я]+){0,2})")
STATUS_PATTERNS = [
    ("unsuccessful", re.compile(r"неуспешен|не\s*е\s*бил\s*успешен|не\s*се\s*е\s*явил|непроведен|не\s+се\s+проведе|няма\s+(?:подадени|постъпили)\s+(?:заявления|оферти)", re.I)),
    ("cancelled", re.compile(r"прекрат\w+|отмен\w+|оттеглен", re.I)),
    ("sold", re.compile(r"успешен|спечел\w*|обявен\s+за\s+купувач|продаден|определен\s+за\s+купувач|възложен", re.I)),
]


def parse_number(s: str) -> float | None:
    s = s.replace(" ", " ").strip()
    if not s:
        return None
    # decide decimal separator: last [.,] followed by 1-2 digits at end
    m = re.match(r"^(.*?)([.,])(\d{1,2})$", s)
    if m and not re.search(r"[.,]\d{3}$", s):
        intpart, frac = m.group(1), m.group(3)
    else:
        intpart, frac = s, "0"
    intpart = re.sub(r"[ .,]", "", intpart)
    if not intpart.isdigit():
        return None
    try:
        return float(f"{int(intpart)}.{frac}")
    except ValueError:
        return None


def to_eur(value: float, cur: str) -> float:
    cur = cur.lower()
    if cur.startswith(("лв", "лева", "bgn")):
        return round(value / BGN_PER_EUR, 2)
    return value


def parse_dates(text: str) -> list[dt.date]:
    out = []
    for d, m, y in DATE_RE.findall(text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            out.append(dt.date(y, int(m), int(d)))
        except ValueError:
            pass
    for y, m, d in re.findall(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)", text):
        try:
            out.append(dt.date(int(y), int(m), int(d)))
        except ValueError:
            pass
    for d, mon, y in DATE_WORD_RE.findall(text):
        try:
            out.append(dt.date(int(y), MONTHS[mon.lower()], int(d)))
        except (ValueError, KeyError):
            pass
    return out


def _date_after(ctx_re: re.Pattern, text: str) -> dt.date | None:
    for m in ctx_re.finditer(text):
        ds = parse_dates(text[m.end(): m.end() + 120]) or parse_dates(text[max(0, m.start() - 60): m.start()])
        if ds:
            return ds[0]
    return None


def classify_deal(text: str) -> str:
    t = text.lower()
    if "концеси" in t:
        return "concession"
    sale = re.search(r"продажб|продава|публичн\w* продан|приватизац|разпореждане чрез продажба", t)
    lease = re.search(r"\bнаем|аренд|отдаване под", t)
    if sale and lease:
        return "sale" if sale.start() < lease.start() else "lease"
    if lease:
        return "lease"
    return "sale"


def classify_type(text: str) -> str:
    t = text.lower()
    if re.search(r"апартамент|жилище|ателие|мезонет", t):
        return "apartment"
    if re.search(r"земеделск|нива|ниви|ливад|пасищ|мери|лозе|овощн|трайни насаждения|дпф|държавния поземлен фонд|аренд", t):
        return "agri"
    if re.search(r"гараж|паркомяст", t):
        return "garage"
    if re.search(r"сград|къща|хале|склад|магазин|офис|помещени|павилион|база|почивна|казарм|цех|котелн|училище", t):
        return "building"
    if re.search(r"упи\b|урегулиран|поземлен|парцел|терен|празен|дворно място", t):
        return "land"
    return "other"


def detect_status(text: str) -> str | None:
    for name, rx in STATUS_PATTERNS:
        if rx.search(text):
            return name
    return None


def is_relevant(text: str) -> bool:
    if not ACTION_RE.search(text) or not PROPERTY_RE.search(text):
        return False
    if NEGATIVE_RE.search(text) and not STRONG_PROPERTY_RE.search(text):
        return False
    return True


def extract(text: str) -> dict:
    """Return dict of fields found in text (missing ones omitted)."""
    f: dict = {}
    cads = []
    for m in CAD_RE.finditer(text):
        cid = ".".join(g for g in m.groups() if g)
        if cid not in cads:
            cads.append(cid)
    if cads:
        f["cadastral_ids"] = cads[:20]
        f["ekatte"] = cads[0].split(".")[0]
    upis = [f"УПИ {a.strip(' ,')} кв. {b}" for a, b in UPI_RE.findall(text)]
    if upis:
        f["upi"] = upis[:10]

    areas = []
    for num, unit in AREA_RE.findall(text):
        v = parse_number(num)
        if v is None or v == 0:
            continue
        if unit.lower().startswith(("дка", "декар")):
            v *= 1000
        areas.append(v)
    if areas:
        f["area_m2"] = round(max(areas), 2)

    pm = PRICE_CTX_RE.search(text) or PRICE_ANY_RE.search(text)
    if pm:
        v = parse_number(pm.group(1))
        if v and v >= 1:
            f["price_eur"] = to_eur(v, pm.group(2))
            f["price_raw"] = pm.group(0)[-80:].strip()
    sm = STEP_RE.search(text)
    if sm and (v := parse_number(sm.group(1))):
        f["step_eur"] = to_eur(v, sm.group(2))

    ad = _date_after(AUCTION_DATE_CTX, text)
    dl = _date_after(DEADLINE_CTX, text)
    dates = parse_dates(text)
    if ad:
        f["auction_date"] = ad.isoformat()
    if dl:
        f["deadline"] = dl.isoformat()
    if dates:
        f["max_date"] = max(dates).isoformat()
        if "auction_date" not in f:
            today = dt.date.today()
            fut = [d for d in dates if d >= today]
            if fut:
                f["auction_date"] = max(fut).isoformat()

    sm = SETTLEMENT_RE.search(text)
    if sm:
        kind = sm.group(1).lower()
        f["settlement"] = ("гр. " if kind in ("гр.", "град") else "с. " if kind in ("с.", "село") else "к.к. ") + sm.group(2)
    f["deal"] = classify_deal(text)
    f["ptype"] = classify_type(text)
    st = detect_status(text)
    if st:
        f["status_hint"] = st
    return f


def is_stale(fields: dict, days: int = 150) -> bool:
    """Old archive entries: all dates in the text are long past."""
    md = fields.get("max_date")
    if not md:
        return False
    return dt.date.fromisoformat(md) < dt.date.today() - dt.timedelta(days=days)
