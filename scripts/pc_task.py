"""Windows scheduled tasks (run with pythonw.exe so no window appears), only while the PC is on and logged in.

  pc_task.py update   every 15 minutes: `run --budget` (picks, lines only before kickoffs, scores sparingly)
  pc_task.py alert    every 5 minutes: Telegram message ~15 minutes before kickoff (collects first when due)

After either one, a changed data/actions.db is committed and pushed, and the dashboard is republished when
there is new data (same steps as the Desktop button). Both share one lock, so they never run at the same time.
Output goes to reports/pc_task.log.

The phone (scripts/auto_update.sh, commits tagged "(phone ...)") is the main collector. While it has pushed
data in the last PHONE_ACTIVE_S seconds the PC skips its turn, so the two never fight over data/actions.db;
when the phone goes quiet the PC fast-forwards to the phone's data and takes over.

Install (PowerShell, see the README / chat): Register-ScheduledTask "Actions Update 15m" and
"Actions Telegram Alert" with action  <repo>\\.venv\\Scripts\\pythonw.exe "<repo>\\scripts\\pc_task.py" <mode>
"""

import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
LOCK = REPO / ".pc_task.lock"
LOG = REPO / "reports" / "pc_task.log"
LOCK_STALE_S = 20 * 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMMANDS = {"update": ["run", "--budget"], "alert": ["alert"], "live": ["live"]}
PHONE_ACTIVE_S = 30 * 60


def phone_active(last_db_commit: str, now: float) -> bool:
    """`git log -1 --format=%ct|%s` of the newest origin/main commit touching data/actions.db."""
    stamp, _, subject = last_db_commit.partition("|")
    return "(phone" in subject and stamp.isdigit() and now - int(stamp) < PHONE_ACTIVE_S


def sh(log, *cmd: str) -> int:
    r = subprocess.run(list(cmd), cwd=REPO, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                       env=os.environ | {"PYTHONIOENCODING": "utf-8"})
    return r.returncode


def out(*cmd: str) -> str:
    return subprocess.run(list(cmd), cwd=REPO, capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()


def main(mode: str) -> int:
    if mode not in COMMANDS:
        return 2
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S:
        return 0  # the other task is busy; the next tick tries again
    LOCK.write_text(f"{mode} {os.getpid()}", "utf-8")
    LOG.parent.mkdir(exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.replace(LOG.with_suffix(".old.log"))
    try:
        with LOG.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} {mode} ===\n")
            log.flush()
            sh(log, "git", "fetch", "-q", "origin", "main")
            if phone_active(out("git", "log", "-1", "--format=%ct|%s", "origin/main", "--", "data/actions.db"),
                            time.time()):
                log.write("dien thoai dang chay - may tinh bo qua luot nay\n")
                return 0
            if out("git", "rev-parse", "--abbrev-ref", "HEAD") == "main":
                sh(log, "git", "merge", "--ff-only", "-q", "origin/main")  # take the phone's newest data first
            code = sh(log, str(PYTHON), "-m", "actions_tracker", *COMMANDS[mode])
            log.write(f"{mode} exit={code}\n")
            log.flush()
            if out("git", "status", "--porcelain", "--", "data/actions.db") and \
                    out("git", "rev-parse", "--abbrev-ref", "HEAD") == "main":
                sh(log, "git", "add", "--", "data/actions.db")
                if sh(log, "git", "commit", "-q", "-m", f"data: update {dt.datetime.now():%Y-%m-%d %H:%M} ({mode})") == 0:
                    if sh(log, "git", "push", "-q") != 0:
                        sh(log, "git", "pull", "--rebase", "--autostash", "-q")
                        sh(log, "git", "push", "-q")
                sh(log, str(PYTHON), str(REPO / "scripts" / "publish_site.py"))
        return code
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "update"))
