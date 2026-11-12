"""Publish site/ to the gh-pages branch as one fresh commit (force push).

GitHub Pages serves that branch. Because every publish replaces the branch instead of adding to it,
hourly updates never grow the repository. Used by scripts/update.ps1 (Desktop button) and
scripts/auto_update.sh (phone, every hour).

Usage: python scripts/publish_site.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main() -> int:
    site = REPO / "site"
    if not (site / "index.html").exists():
        print("Chua co site/index.html - chay `python -m actions_tracker run` truoc.")
        return 1
    url = git("remote", "get-url", "origin").stdout.strip()
    name = git("config", "user.name").stdout.strip() or "actions-tracker"
    email = git("config", "user.email").stdout.strip() or "actions-tracker@users.noreply.github.com"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        out = Path(tmp)
        for f in site.iterdir():
            if f.is_file():
                shutil.copy2(f, out / f.name)
        (out / ".nojekyll").write_text("", "utf-8")  # serve files as-is
        for step in (("init", "-q", "-b", "gh-pages"), ("add", "-A"),
                     ("-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", "site: publish")):
            r = git(*step, cwd=out)
            if r.returncode:
                print("Loi git:", r.stderr.strip())
                return 1
        r = git("push", "-q", "--force", url, "gh-pages:gh-pages", cwd=out)
        if r.returncode:
            print("Chua day duoc website len GitHub:", r.stderr.strip())
            return 1
    print("Da dua website len GitHub Pages (cap nhat sau 1-2 phut).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
