"""Windows scheduled task (every 5 minutes, run with pythonw.exe so no window appears).

Calls `python -m actions_tracker alert`: nothing happens unless a game with picks starts within ~18 minutes.
When it does, the alert command collects fresh data and sends the Telegram message; this script then commits
data/actions.db, pushes and republishes the dashboard (same steps as the Desktop button). Output goes to
reports/alert.log.

Install:  schtasks /Create /SC MINUTE /MO 5 /TN "Actions Telegram Alert" /F
          /TR "\"<repo>\\.venv\\Scripts\\pythonw.exe\" \"<repo>\\scripts\\alert_task.py\""
"""

import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
LOCK = REPO / ".alert.lock"
LOG = REPO / "reports" / "alert.log"
LOCK_STALE_S = 20 * 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sh(log, *cmd: str) -> int:
    r = subprocess.run(list(cmd), cwd=REPO, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                       env=os.environ | {"PYTHONIOENCODING": "utf-8"})
    return r.returncode


def main() -> int:
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S:
        return 0  # the previous run is still busy
    LOCK.write_text(str(os.getpid()), "utf-8")
    LOG.parent.mkdir(exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.replace(LOG.with_suffix(".old.log"))
    try:
        with LOG.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            log.flush()
            code = sh(log, str(PYTHON), "-m", "actions_tracker", "alert")
            log.write(f"alert exit={code}\n")
            changed = subprocess.run(["git", "status", "--porcelain", "--", "data/actions.db"], cwd=REPO,
                                     capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, capture_output=True,
                                    text=True, creationflags=NO_WINDOW).stdout.strip()
            if changed and branch == "main":
                stamp = f"{dt.datetime.now():%Y-%m-%d %H:%M}"
                sh(log, "git", "add", "--", "data/actions.db")
                if sh(log, "git", "commit", "-q", "-m", f"data: update {stamp} (alert)") == 0:
                    if sh(log, "git", "push", "-q") != 0:
                        sh(log, "git", "pull", "--rebase", "--autostash", "-q")
                        sh(log, "git", "push", "-q")
                sh(log, str(PYTHON), str(REPO / "scripts" / "publish_site.py"))
            log.flush()
        return code
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
