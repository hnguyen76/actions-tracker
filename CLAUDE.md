# Actions Expert Tracker — notes for Claude

The owner writes Vietnamese without diacritics; reply in Vietnamese with diacritics, keep betting terms
in English (spread, total, moneyline, favorite, underdog, fade).

## How the live system runs
- An Android phone at home (Termux, `scripts/auto_update.sh update|alert|live`, data cron 11:00–23:00) pulls
  `main`, collects data, commits `data/actions.db` as "data: update … (phone …)", rebuilds the site and
  force-pushes `gh-pages` (`scripts/publish_site.py`). A separate `sync` cron runs every 5 minutes 24/7; it
  only pulls, rebuilds from existing data and publishes when HEAD changed. The laptop tasks are a backup.
- So a code change merged into `main` goes live by itself within ~5–15 minutes. Do not publish from here.
- Dashboard: https://hnguyen76.github.io/actions-tracker/ — template `src/actions_tracker/templates/index.html`,
  static JS/CSS in `src/actions_tracker/templates/static/`, built by `src/actions_tracker/build_site.py`.
- "?" opens the Hỏi Actions artifact (https://claude.ai/artifact/3pMbgv9aTTrbptD5dDhwTE, source `artifacts/hoi-actions.html`,
  republish it with the Artifact tool). Claude answers there with the viewer's Claude account; the dashboard passes its
  data in the link's #name (`static/ask.js`) and copies it to the clipboard for a paste.

## Hard rules
- Never fetch actionnetwork.com from a cloud machine and never work around its bot block (no internal/app
  APIs, proxies, Apify, other clouds). Picks are collected only on the home network. ESPN and Open-Meteo are fine.
- Never commit secrets or the gitignored key files (`.telegram_bot_token`, `.telegram_chat_id`, `.odds_api_key`, …).
- Do not commit `data/actions.db` from a cloud session (the phone owns it; a stale copy would overwrite fresh
  data). Read it for analysis only. Same for `data/history/*.csv` unless asked.
- Rules in `src/actions_tracker/rules.py` are frozen forward tests: do not change their thresholds unless the
  owner explicitly asks to drop/replace one. Never recommend real-money bets on rules still being tested.
- The Decision card's "Cách của bạn": Mon–Fri ET follow every NFL/NCAAF/NBA spread, total or moneyline majority
  with at least 2 distinct experts on that side; Sat–Sun keeps spread-only NFL/NCAAF, ≥5 total picks, and fades
  the majority (unanimous crowds included). The owner MAY change it any time — follow the
  "Sửa Cách của bạn" section of the project skill `.claude/skills/bettingskill/SKILL.md` (back-test first).
- Analysis and reports: use the `bettingskill` project skill.

## Design (owner's preference)
- Keep every design simple, with as few words as possible: numbers, colours and icons over sentences
  (e.g. "CIN -4,5  23,5" in green/red instead of "Bạn đặt CIN -4,5 · ĐANG THẮNG · hơn 23,5 điểm").
- Say "banh", not "bóng".

## Checks before finishing
- `pip install -e .[dev]` then `python -m pytest -q` (all must pass) and `node --test tests/frontend/*.test.cjs`.
- Keep changes small and say in Vietnamese what changed on the page.
