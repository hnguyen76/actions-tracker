# Actions Expert Tracker — notes for Claude

The owner writes Vietnamese without diacritics; reply in Vietnamese with diacritics, keep betting terms
in English (spread, total, moneyline, favorite, underdog, fade).

## How the live system runs
- An Android phone at home (Termux, `scripts/auto_update.sh update|alert|live`, cron 11:00–23:00) pulls
  `main`, collects data, commits `data/actions.db` as "data: update … (phone …)", rebuilds the site and
  force-pushes `gh-pages` (`scripts/publish_site.py`). The laptop tasks (`scripts/pc_task.py`) are a backup.
- So a code change merged into `main` goes live by itself within ~5–15 minutes. Do not publish from here.
- Dashboard: https://hnguyen76.github.io/actions-tracker/ — template `src/actions_tracker/templates/index.html`,
  static JS/CSS in `src/actions_tracker/templates/static/`, built by `src/actions_tracker/build_site.py`.

## Hard rules
- Never fetch actionnetwork.com from a cloud machine and never work around its bot block (no internal/app
  APIs, proxies, Apify, other clouds). Picks are collected only on the home network. ESPN and Open-Meteo are fine.
- Never commit secrets or the gitignored key files (`.telegram_bot_token`, `.telegram_chat_id`, `.odds_api_key`, …).
- Do not commit `data/actions.db` from a cloud session (the phone owns it; a stale copy would overwrite fresh
  data). Read it for analysis only. Same for `data/history/*.csv` unless asked.
- Rules in `src/actions_tracker/rules.py` are frozen forward tests: do not change their thresholds.
  Never recommend real-money bets on rules still being tested.
- The owner's own method ("Cách của bạn"): spread only, ≥5 picks, majority side; Mon–Fri ET follow the crowd,
  Sat–Sun fade it (unanimous crowds included).

## Checks before finishing
- `pip install -e .[dev]` then `python -m pytest -q` (all must pass) and `node --test tests/frontend/`.
- Keep changes small and say in Vietnamese what changed on the page.
