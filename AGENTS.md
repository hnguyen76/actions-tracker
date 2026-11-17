# Actions Expert Tracker — instructions for Codex

The owner commonly writes Vietnamese without diacritics. Reply in clear Vietnamese with diacritics, while
keeping established betting terms in English (spread, total, moneyline, favorite, underdog, fade).

## Repository and deployment

- Dashboard: https://hnguyen76.github.io/actions-tracker/
- Site template: `src/actions_tracker/templates/index.html`.
- Frontend assets: `src/actions_tracker/templates/static/`.
- Site builder: `src/actions_tracker/build_site.py`.
- The Android/Termux collector pulls `main`, updates `data/actions.db`, rebuilds the site, and publishes
  `gh-pages` with `scripts/publish_site.py`. Its lightweight `sync` job runs every 5 minutes, 24/7, and rebuilds
  from existing data without calling sports APIs, so a merged code change normally appears in 5–15 minutes
  even overnight. Do not publish from a Codex Cloud task.

## Git workflow

- Start from the latest `origin/main` and make code changes on a separate branch.
- Create a pull request for every change. After the required checks pass and GitHub reports the PR mergeable,
  merge Codex-created PRs and delete their head branches automatically unless the owner explicitly asks to
  leave a PR open for review. Never push code directly to `main` or `gh-pages`.
- Keep commits focused. Do not include unrelated local or generated files.
- The phone writes frequently to `main`. Refresh from `origin/main` before finalizing a pull request.
- If a conflict involves `data/actions.db`, preserve the phone's newest version; never replace it with the
  cloud workspace copy.

## Data, secrets, and generated files

- Treat `data/actions.db` as read-only in cloud sessions. Never commit it from Codex Cloud.
- Treat `data/history/*.csv` as read-only unless the owner explicitly requests a historical-data change.
- Never commit credentials or ignored key files, including `.telegram_bot_token`, `.telegram_chat_id`,
  `.odds_api_key`, `.env`, cookies, API keys, or account tokens.
- Do not commit generated output from `site/` or `reports/`.
- Do not fetch Action Network from a cloud machine or attempt to bypass its bot protection. Picks are
  collected only by the home-network device. ESPN and Open-Meteo access is allowed when the task needs it.

## Betting behavior

- Rules in `src/actions_tracker/rules.py` are forward tests. Do not change their thresholds unless the owner
  explicitly asks to remove, replace, or modify a rule. Do not present unvalidated rules as real-money advice.
- The Decision card's "Cách của bạn" uses every market in NFL/NCAAF/NBA Monday–Friday ET: follow a majority
  side once it has at least 2 distinct expert picks. Saturday–Sunday retains the spread-only NFL/NCAAF method:
  at least 5 total picks and fade the majority, including unanimous crowds.
- The owner may change "Cách của bạn" at any time. For betting analysis or a requested method change, read
  `.claude/skills/bettingskill/SKILL.md` completely and follow its "Sửa Cách của bạn" workflow: back-test the
  proposed method first, then change code and tests, and update the method log described there.

## Verification

Install development dependencies when needed:

```bash
pip install -e ".[dev]"
```

Before finishing a code change, run the relevant tests; for a normal application or UI change, run both full
suites:

```bash
python -m pytest -q
node --test tests/frontend/*.cjs
```

Report what changed, which checks ran, and any check that could not run. Do not claim deployment is complete;
deployment occurs only after merge and the phone's next successful publish cycle.
