#!/usr/bin/env bash
# Phone (Termux) / home Linux box: scheduled collection plus an always-on lightweight site sync.
#   auto_update.sh update   every 15 min: `run --budget` (picks, ESPN lines/scores, news, rules)
#   auto_update.sh alert    every 5 min:  Telegram message ~15 min before kickoff (collects first when due)
#   auto_update.sh live     every 5 min:  ESPN live scores + finals (light)
#   auto_update.sh news     every 15 min overnight: ESPN breaking + Yahoo Sports, then rebuild
#   auto_update.sh sync     every 5 min, 24/7: pull code, rebuild locally and publish only when HEAD changed
# Collection jobs: pull -> run -> commit data/actions.db (only when it changed) -> push -> publish the site.
# Commits are tagged "(phone <mode>)" so the PC tasks step aside while the phone is active.
# The cron lines are installed by scripts/termux_setup.sh.
set -u
MODE="${1:-update}"
case "$MODE" in
  update) CMD="run --budget" ;;
  alert)  CMD="alert" ;;
  live)   CMD="live" ;;
  news)   CMD="news" ;;
  sync)   CMD="" ;;
  *) echo "che do khong hop le: $MODE (update | alert | live | news | sync)"; exit 2 ;;
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

# Existing S21 installs learn the new overnight job automatically after they have pulled this version once.
# Restrict this self-heal to Termux; a normal Linux cron remains under its owner's control.
ensure_sync_cron() {
  case "${PREFIX:-}" in
    *com.termux*) ;;
    *) return ;;
  esac
  command -v crontab >/dev/null 2>&1 || return
  if crontab -l 2>/dev/null | grep -Fq "auto_update.sh sync"; then
    return
  fi
  ( crontab -l 2>/dev/null || true
    echo "2-59/5 * * * * bash $REPO/scripts/auto_update.sh sync >> $HOME/actions-auto.log 2>&1" ) | crontab -
  echo "Da them lich sync site 24/7 moi 5 phut."
}

ensure_news_cron() {
  case "${PREFIX:-}" in
    *com.termux*) ;;
    *) return ;;
  esac
  command -v crontab >/dev/null 2>&1 || return
  if crontab -l 2>/dev/null | grep -Fq "auto_update.sh news"; then
    return
  fi
  ( crontab -l 2>/dev/null || true
    echo "7-52/15 0-10,23 * * * bash $REPO/scripts/auto_update.sh news >> $HOME/actions-auto.log 2>&1" ) | crontab -
  echo "Da them lich tin ESPN/Yahoo xuyen dem moi 15 phut."
}

ensure_alert_cron() {
  case "${PREFIX:-}" in
    *com.termux*) ;;
    *) return ;;
  esac
  command -v crontab >/dev/null 2>&1 || return
  if crontab -l 2>/dev/null | grep -Fq "1-59/5 11-23 * * * bash $REPO/scripts/auto_update.sh alert"; then
    return
  fi
  ( crontab -l 2>/dev/null | grep -v "auto_update.sh alert" || true
    echo "1-59/5 11-23 * * * bash $REPO/scripts/auto_update.sh alert >> $HOME/actions-auto.log 2>&1"
    echo "1-59/5 9-10 * * 0 bash $REPO/scripts/auto_update.sh alert >> $HOME/actions-auto.log 2>&1" ) | crontab -
  echo "Da mo rong lich Telegram den 23:59; tam ngung tu 00:00."
}

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

PUBLISHED_HEAD="$(git rev-parse --git-path actions-last-published 2>/dev/null)"
published_head_changed() {
  current="$(git rev-parse HEAD 2>/dev/null)"
  previous="$(cat "$PUBLISHED_HEAD" 2>/dev/null || true)"
  [ -n "$current" ] && [ "$current" != "$previous" ]
}

publish_site() {
  rebuild="${1:-0}"
  if [ "$rebuild" = 1 ]; then
    "$PY" -m actions_tracker build || return
  fi
  if "$PY" scripts/publish_site.py; then
    git rev-parse HEAD 2>/dev/null > "$PUBLISHED_HEAD"
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

ensure_sync_cron
ensure_news_cron
ensure_alert_cron
sync_main

# The overnight job never collects or commits data. It only republishes when a new main HEAD has arrived.
if [ "$MODE" = sync ]; then
  if published_head_changed; then
    publish_site 1
  else
    echo "Site da o ban moi nhat."
  fi
  echo "=== xong $MODE ==="
  exit 0
fi

collect_and_commit
if [ "$COMMITTED" = 1 ] && ! git push -q 2>/dev/null; then
  sync_main
  if [ -z "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
    collect_and_commit  # our data was dropped for GitHub's newer copy: collect again on top of it
  fi
  git push -q 2>/dev/null || echo "Chua push duoc du lieu - lan sau se thu lai."
fi

# Republish for new data, for the regular update clock, or when alert/live pulled a code change first.
if [ "$COMMITTED" = 1 ] || [ "$MODE" = update ] || published_head_changed; then
  rebuild=0
  if [ "$COMMITTED" = 0 ] && [ "$MODE" != update ]; then
    rebuild=1
  fi
  publish_site "$rebuild"
fi
echo "=== xong $MODE ==="
