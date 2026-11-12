#!/usr/bin/env bash
# Hourly auto-update (phone / Termux, or any Linux box on the home network):
# pull -> collect picks (+ lines/scores in --budget mode) -> commit data/actions.db -> publish site to gh-pages.
# Cron: 7 * * * * bash ~/actions-tracker/scripts/auto_update.sh >> ~/actions-auto.log 2>&1
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO/src"
PY="${PYTHON:-python}"
LOG="$HOME/actions-auto.log"
stamp="$(date '+%Y-%m-%d %H:%M')"

# keep the log small
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# one run at a time (a stale lock older than 50 minutes is ignored)
LOCK="$REPO/.auto_update.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +50 2>/dev/null)" ]; then
    rm -rf "$LOCK" && mkdir "$LOCK"
  else
    echo "[$stamp] dang co mot lan chay khac - bo qua"
    exit 0
  fi
fi
trap 'rm -rf "$LOCK"' EXIT

echo "=== [$stamp] Actions auto update ==="

sync_main() {
  # take the latest data from GitHub; if our unpushed data conflicts (the PC button pushed meanwhile),
  # drop ours - the next collection re-reads everything that is still on Action Network
  if ! git pull -q --rebase 2>/dev/null; then
    git rebase --abort 2>/dev/null
    if git fetch -q 2>/dev/null; then
      echo "Xung dot du lieu voi GitHub - lay ban moi nhat roi thu thap lai."
      git reset -q --hard origin/main
    else
      echo "Khong ket noi duoc GitHub - chay voi du lieu tren may."
    fi
  fi
}

collect_and_commit() {
  "$PY" -m actions_tracker run --budget
  echo "ma thoat: $?"
  git add data/actions.db
  git diff --cached --quiet || git commit -q -m "data: auto update $stamp"
}

sync_main
collect_and_commit
if ! git push -q 2>/dev/null; then
  sync_main
  if [ -z "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
    collect_and_commit  # our data was dropped for GitHub's newer copy: collect again on top of it
  fi
  git push -q 2>/dev/null || echo "Chua push duoc du lieu - lan sau se thu lai."
fi

"$PY" scripts/publish_site.py
echo "=== xong ==="
