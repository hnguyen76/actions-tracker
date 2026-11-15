#!/usr/bin/env bash
# Phone (Termux) / home Linux box: same three jobs as the PC scheduled tasks (scripts/pc_task.py).
#   auto_update.sh update   every 15 min: `run --budget` (picks, ESPN lines/scores, news, rules)
#   auto_update.sh alert    every 5 min:  Telegram message ~15 min before kickoff (collects first when due)
#   auto_update.sh live     every 5 min:  ESPN live scores + finals (light)
# Each one: pull -> run -> commit data/actions.db (only when it changed) -> push -> publish the site.
# Commits are tagged "(phone <mode>)" so the PC tasks step aside while the phone is active.
# The cron lines are installed by scripts/termux_setup.sh.
set -u
MODE="${1:-update}"
case "$MODE" in
  update) CMD="run --budget" ;;
  alert)  CMD="alert" ;;
  live)   CMD="live" ;;
  *) echo "che do khong hop le: $MODE (update | alert | live)"; exit 2 ;;
esac
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO/src"
export PYTHONIOENCODING=utf-8
PY="${PYTHON:-python}"
LOG="$HOME/actions-auto.log"
stamp="$(date '+%Y-%m-%d %H:%M')"

# keep the log small
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# one job at a time; the others skip this tick (a lock older than 20 minutes is stale)
LOCK="$REPO/.auto_update.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then
    rm -rf "$LOCK" && mkdir "$LOCK"
  else
    exit 0
  fi
fi
trap 'rm -rf "$LOCK"' EXIT

echo "=== [$stamp] $MODE ==="

sync_main() {
  # take the latest data from GitHub; if our unpushed data conflicts (the PC pushed meanwhile),
  # drop ours - the next collection re-reads everything that is still on Action Network / ESPN
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

COMMITTED=0
collect_and_commit() {
  # shellcheck disable=SC2086
  "$PY" -m actions_tracker $CMD
  echo "$MODE ma thoat: $?"
  git add data/actions.db
  if ! git diff --cached --quiet; then
    git commit -q -m "data: update $stamp (phone $MODE)" && COMMITTED=1
  fi
}

sync_main
collect_and_commit
if [ "$COMMITTED" = 1 ] && ! git push -q 2>/dev/null; then
  sync_main
  if [ -z "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
    collect_and_commit  # our data was dropped for GitHub's newer copy: collect again on top of it
  fi
  git push -q 2>/dev/null || echo "Chua push duoc du lieu - lan sau se thu lai."
fi

# republish only when there is new data (the update job always republishes so the page clock stays fresh)
if [ "$COMMITTED" = 1 ] || [ "$MODE" = update ]; then
  "$PY" scripts/publish_site.py
fi
echo "=== xong $MODE ==="
