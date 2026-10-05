"""Offline end-to-end test with a fake web. Run: python -m pytest -q tests  (or python tests/test_offline.py)"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import fetch, geo, run  # noqa: E402

BCPEA_P1 = """<html><body><div class="list">
<div class="item"><a href="/properties/92810"><img></a><div>Парцел</div><div>1 000.00 EUR</div><div>650.00 кв.м</div>
<div>с. Страхилово</div><div>Окръжен съд Велико Търново</div><div>ЧСИ Виктор Георгиев</div><div>от 06.10.2026 до 06.11.2026</div>
<a href="/properties/92810">Виж</a></div>
<div class="item"><a href="/properties/92811">Къща</a><div>76 000.00 EUR</div><div>85.00 кв.м</div><div>гр. Брацигово</div>
<div>от 18.10.2026 до 18.11.2026</div></div>
</div><a href="/properties?perpage=48&p=2">2</a></body></html>"""
BCPEA_EMPTY = "<html><body><div class='list'></div></body></html>"

APPK_UP = """<html><body><table>
<tr><td><a href="/upcoming-public/view/1148">1148</a></td><td>Областен управител, Областна администрация - Пазарджик</td><td>Пазарджик</td>
<td>ПИ с идентификатор 55155.12.241 по КККР на гр. Пазарджик с площ 1375 кв.м.</td><td>44565.00 EUR без ДДС</td><td>21.10.2026</td></tr>
<tr><td><a href="/upcoming-public/view/1142">1142</a></td><td>АППК</td><td>с. Ресен</td><td>Поземлен имот с идентификатор 62517.502.109, заедно с построените в имота сгради</td><td>405000.00 EUR без ДДС</td><td>Площ: 8018.00 кв. м</td></tr>
</table></body></html>"""
APPK_DETAIL = "<html><body><main>Търг за продажба на поземлен имот с идентификатор 55155.12.241, площ 1375 кв.м. Начална цена 44565.00 EUR без ДДС, стъпка 2000.00 EUR. Търгът ще се проведе на 21.10.2026 г.</main></body></html>"
APPK_PAST = """<html><body><table><tr><td><a href="/past-public/view/1142">1142</a></td><td>с. Ресен</td><td>Търгът не е бил успешен</td></tr></table></body></html>"""

MUNI_HOME = """<html><body><nav><a href="/news">Новини</a></nav><div id="content">
<a href="/obshtestveni-porachki">Обществени поръчки</a>
<a href="/targove">Търгове и конкурси</a>
<a href="/imoti/prodazhba">Продажба на общински имоти</a>
<a href="/kariera">Кариери</a></div></body></html>"""
MUNI_TARGOVE = """<html><body><div class="content"><ul>
<li><a href="/docs/zapoved-123.pdf">Заповед № 123 – публичен търг с явно наддаване за продажба на УПИ III-45, кв. 12 по плана на с. Бохот, площ 1 200 кв.м, начална цена 18 000 лв. Търгът ще се проведе на 20.11.2026 г.</a></li>
<li><a href="/news/42">Обществена поръчка за доставка на хранителни продукти</a></li>
<li><a href="/targove/77">Търг за отдаване под наем на земеделска земя – 45 дка ниви в землището на с. Ясен</a> 15.10.2026</li>
<li><a href="/targove/12">Търг за продажба на сграда (бивше училище) в с. Горталово</a> 12.03.2019</li>
</ul></div></body></html>"""
MUNI_T77 = "<html><body><main>Община Плевен обявява търг за отдаване под наем на земеделска земя 45,5 дка, нива в землището на с. Ясен. Начална наемна цена 60 лв./дка. Търгът ще се проведе на 05.11.2026 г.</main></body></html>"
MUNI_T12 = "<html><body><main>Търг за продажба на сграда (бивше училище) в с. Горталово, проведен на 12.03.2019 г.</main></body></html>"

WEB = {
    "https://sales.bcpea.org/properties?perpage=48": BCPEA_P1,
    "https://sales.bcpea.org/properties?perpage=48&p=2": BCPEA_EMPTY,
    "https://estate-sales.uslugi.io/upcoming-public": APPK_UP,
    "https://estate-sales.uslugi.io/upcoming-public?page=2": BCPEA_EMPTY,
    "https://estate-sales.uslugi.io/upcoming-public/view/1148": APPK_DETAIL,
    "https://estate-sales.uslugi.io/upcoming-public/view/1142": APPK_DETAIL.replace("55155.12.241", "62517.502.109"),
    "https://estate-sales.uslugi.io/past-public": APPK_PAST,
    "https://estate-sales.uslugi.io/past-public?page=2": BCPEA_EMPTY,
    "https://www.pleven.bg/": MUNI_HOME,
    "https://www.pleven.bg/targove": MUNI_TARGOVE,
    "https://www.pleven.bg/imoti/prodazhba": MUNI_TARGOVE,
    "https://www.pleven.bg/targove/77": MUNI_T77,
    "https://www.pleven.bg/targove/12": MUNI_T12,
}


def fake_get(url, params=None):
    if params:
        url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    if url.endswith(".pdf"):
        raise fetch.FetchError("HTTP 404 " + url)
    if url not in WEB:
        raise fetch.FetchError("HTTP 404 " + url)
    return fetch.Page(url, 200, WEB[url].encode(), "text/html; charset=utf-8", WEB[url])


SOURCES = [
    {"id": "bcpea", "name": "ЧСИ", "category": "chsi", "kind": "cards", "urls": ["https://sales.bcpea.org/properties"],
     "item_link": r"/properties/\d+$", "page_param": "p", "extra_params": {"perpage": 48}, "max_pages": 5},
    {"id": "appk-upcoming", "group": "appk-e", "name": "АППК", "category": "apk", "kind": "cards", "detail": True,
     "urls": ["https://estate-sales.uslugi.io/upcoming-public"], "item_link": r"/upcoming-public/view/\d+", "page_param": "page"},
    {"id": "appk-past", "group": "appk-e", "name": "АППК минали", "category": "apk", "kind": "cards", "results_only": True,
     "urls": ["https://estate-sales.uslugi.io/past-public"], "item_link": r"/past-public/view/\d+", "page_param": "page"},
    {"id": "ob-pleven", "name": "Община Плевен", "municipality": "Община Плевен", "oblast": "Плевен",
     "category": "obshtina", "kind": "discover", "home": "https://www.pleven.bg/", "urls": []},
]


def test_end_to_end():
    tmp = Path(tempfile.mkdtemp())
    try:
        run.DATA, run.STATE = tmp / "data", tmp / "state"
        run.ITEMS_FILE, run.SOURCES_FILE, run.DISC_FILE = run.DATA / "items.json", run.DATA / "sources.json", run.STATE / "d.json"
        fetch.get = fake_get
        import scanner.discover as d, scanner.generic as g, scanner.parsers.cards as c
        d.fetch.get = g.fetch.get = c.fetch.get = fake_get
        geo.locate = lambda item: None
        run.load_all = lambda: SOURCES
        sys.argv = ["run", "--workers", "2"]
        run.main()
        items = {i["id"]: i for i in json.loads(run.ITEMS_FILE.read_text())}
        for k, v in items.items():
            print(k, "|", v["title"][:70], "|", v.get("price_eur"), v.get("area_m2"), v.get("auction_date"),
                  v.get("cadastral_ids"), v["status"], "ARCH" if v.get("archived") else "")
        assert "bcpea:92810" in items and items["bcpea:92810"]["price_eur"] == 1000.0
        assert items["bcpea:92811"]["area_m2"] == 85.0
        assert items["appk-e:1148"]["cadastral_ids"] == ["55155.12.241"]
        assert items["appk-e:1148"]["auction_date"] == "2026-10-21"
        assert items["appk-e:1142"]["status"] == "unsuccessful", "past-public result must update status"
        muni = [v for v in items.values() if v["source_id"] == "ob-pleven"]
        titles = " ".join(v["title"] for v in muni)
        assert "Обществена поръчка" not in titles
        assert any("УПИ" in v["title"] for v in muni)
        t77 = [v for v in muni if v["url"].endswith("/targove/77")][0]
        assert t77["deal"] == "lease" and t77["ptype"] == "agri" and t77["area_m2"] == 45500
        t12 = [v for v in muni if v["url"].endswith("/targove/12")][0]
        assert t12.get("archived"), "2019 notice must be archived"
        disc = json.loads(run.DISC_FILE.read_text())
        assert "https://www.pleven.bg/targove" in disc["ob-pleven"]["urls"]
        assert all("porachki" not in u for u in disc["ob-pleven"]["urls"])
        # second run: nothing new, nothing gone yet
        run.main()
        items2 = json.loads(run.ITEMS_FILE.read_text())
        assert len(items2) == len(items)
        assert json.loads((run.DATA / "meta.json").read_text())["new_this_run"] == 0
        # remove an item from the web → after 2 misses becomes "gone"
        WEB["https://sales.bcpea.org/properties?perpage=48"] = BCPEA_P1.replace('/properties/92811', '/properties/99999')
        run.main(); run.main()
        items3 = {i["id"]: i for i in json.loads(run.ITEMS_FILE.read_text())}
        assert items3["bcpea:92811"]["status"] == "gone"
        assert items3["bcpea:99999"]["status"] == "active"
        print("OK", len(items3), "items")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_end_to_end()
