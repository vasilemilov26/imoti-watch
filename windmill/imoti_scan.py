# Windmill скрипт: сканиране на търгове за имоти.
# Взима кода и данните от вашето GitHub хранилище, пуска скенера и записва резултата обратно.
# Таблото продължава да е на GitHub Pages.
#
# requirements:
# requests
# beautifulsoup4
# lxml
# PyYAML
# pdfminer.six
# python-docx

import os
import shutil
import subprocess
import sys
import tempfile


def _ensure_deps():
    """Fallback if this Windmill version ignores the `# requirements:` header."""
    try:
        import bs4, lxml, yaml, pdfminer, docx, requests  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "requests", "beautifulsoup4", "lxml",
                        "PyYAML", "pdfminer.six", "python-docx"], check=True)


def _git(args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[-500:]}")
    return r.stdout


def main(
    github_repo: str,            # напр. "vasil-emilov/imoti-watch"
    github_token: str,           # GitHub token с право Contents: Read and write
    max_minutes: int = 40,       # колко време да сканира в един пуск
    only: str = "",              # само определени източници (id, със запетая); празно = всички
    rediscover: bool = False,    # търси наново секциите с търгове
    anthropic_api_key: str = "", # по избор – по-умно разчитане на обявите
):
    _ensure_deps()
    work = tempfile.mkdtemp(prefix="imoti-")
    url = f"https://x-access-token:{github_token}@github.com/{github_repo}.git"
    try:
        _git(["clone", "--depth", "20", url, work])
        env = dict(os.environ, MAX_MINUTES=str(max_minutes), PYTHONUNBUFFERED="1")
        if anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = anthropic_api_key
        cmd = [sys.executable, "-m", "scanner.run", "--max-minutes", str(max_minutes)]
        if only:
            cmd += ["--only", only]
        if rediscover:
            cmd.append("--rediscover")
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True)
        print(proc.stdout[-6000:])
        print(proc.stderr[-12000:])
        if proc.returncode != 0:
            raise RuntimeError("скенерът спря с грешка – вижте лога горе")

        _git(["config", "user.name", "imoti-watch-bot"], work)
        _git(["config", "user.email", "bot@imoti-watch.local"], work)
        _git(["add", "-A", "docs/data", "state", "sources"], work)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=work).returncode == 0:
            return {"changed": False}
        _git(["commit", "-m", "data: scan (windmill)"], work)
        for _ in range(3):
            try:
                _git(["pull", "--rebase", "-X", "theirs", "--depth", "50"], work)
                _git(["push"], work)
                break
            except RuntimeError as e:
                last = e
        else:
            raise last
        import json
        meta = json.load(open(os.path.join(work, "docs/data/meta.json"), encoding="utf-8"))
        return meta
    finally:
        shutil.rmtree(work, ignore_errors=True)
