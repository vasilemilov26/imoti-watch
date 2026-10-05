# Windmill скрипт: сутрешен имейл с новите търгове.
#
# requirements:
# PyYAML

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
    github_repo: str,       # напр. "vasil-emilov/imoti-watch"
    github_token: str,
    smtp_user: str,         # Gmail адрес
    smtp_pass: str,         # Gmail App password (16 знака)
    mail_to: str,           # получател(и), със запетая
):
    _ensure_deps()
    work = tempfile.mkdtemp(prefix="imoti-")
    try:
        _git(["clone", "--depth", "20", f"https://x-access-token:{github_token}@github.com/{github_repo}.git", work])
        owner, name = github_repo.split("/", 1)
        env = dict(os.environ, SMTP_USER=smtp_user, SMTP_PASS=smtp_pass, MAIL_TO=mail_to,
                   DASHBOARD_URL=f"https://{owner.lower()}.github.io/{name}/")
        proc = subprocess.run([sys.executable, "-m", "scanner.digest"], cwd=work, env=env,
                              capture_output=True, text=True)
        print(proc.stdout, proc.stderr[-4000:])
        if proc.returncode != 0:
            raise RuntimeError("бюлетинът спря с грешка – вижте лога горе")
        _git(["config", "user.name", "imoti-watch-bot"], work)
        _git(["config", "user.email", "bot@imoti-watch.local"], work)
        _git(["add", "-A", "state", "docs/digests"], work)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=work).returncode != 0:
            _git(["commit", "-m", "digest (windmill)"], work)
            _git(["pull", "--rebase", "-X", "theirs", "--depth", "50"], work)
            _git(["push"], work)
        return proc.stdout.strip()
    finally:
        shutil.rmtree(work, ignore_errors=True)
