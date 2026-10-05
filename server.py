"""Self-hosted mode: one process that serves the dashboard (password protected) and runs the schedule.

Environment (.env):
  DASH_USER / DASH_PASS   – вход за таблото (задължително)
  PORT                    – порт на таблото (по подразбиране 8090)
  SCAN_EVERY_HOURS        – през колко часа да сканира (по подразбиране 4)
  SCAN_MAX_MINUTES        – максимална продължителност на едно сканиране (по подразбиране 90)
  DIGEST_AT               – час на сутрешния имейл, напр. 07:40 (Europe/Sofia)
  SMTP_USER / SMTP_PASS / MAIL_TO – за имейла
  DASHBOARD_URL           – адрес на таблото, за линка в имейла
  ANTHROPIC_API_KEY       – по избор
"""
from __future__ import annotations

import base64
import datetime as dt
import functools
import hmac
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
TZ = ZoneInfo("Europe/Sofia")
log = logging.getLogger("server")

USER = os.environ.get("DASH_USER", "")
PASS = os.environ.get("DASH_PASS", "")
PORT = int(os.environ.get("PORT", "8090"))
EVERY_H = float(os.environ.get("SCAN_EVERY_HOURS", "4"))
MAX_MIN = os.environ.get("SCAN_MAX_MINUTES", "90")
DIGEST_AT = os.environ.get("DIGEST_AT", "07:40")
LOCK = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def _authorized(self) -> bool:
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            u, _, p = base64.b64decode(h[6:]).decode("utf-8").partition(":")
        except Exception:
            return False
        return hmac.compare_digest(u, USER) and hmac.compare_digest(p, PASS)

    def do_GET(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="imoti", charset="UTF-8"')
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def run_job(args: list[str]):
    if not LOCK.acquire(blocking=False):
        log.info("job skipped – another one is running")
        return
    try:
        log.info("start: %s", " ".join(args))
        r = subprocess.run([sys.executable, "-m", *args], cwd=ROOT)
        log.info("end: %s (exit %s)", args[0], r.returncode)
    finally:
        LOCK.release()


def scheduler():
    last_scan = 0.0
    last_digest_day = None  # first scan runs right after start
    while True:
        now = dt.datetime.now(TZ)
        if time.time() - last_scan >= EVERY_H * 3600:
            last_scan = time.time()
            run_job(["scanner.run", "--max-minutes", MAX_MIN])
        hh, mm = map(int, DIGEST_AT.split(":"))
        now = dt.datetime.now(TZ)
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= due and last_digest_day != now.date():
            # after a restart late in the day, wait for tomorrow instead of mailing at a random hour
            if now - due < dt.timedelta(hours=2):
                run_job(["scanner.digest"])
            last_digest_day = now.date()
        time.sleep(30)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if not USER or not PASS:
        sys.exit("Задайте DASH_USER и DASH_PASS в .env – таблото не се пуска без парола.")
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), functools.partial(Handler, directory=str(DOCS)))
    log.info("dashboard on :%s (every %sh scan, digest at %s)", PORT, EVERY_H, DIGEST_AT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
