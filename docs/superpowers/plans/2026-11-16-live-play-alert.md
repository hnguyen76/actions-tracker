# Live big-play alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the dashboard is open, show a full-screen fireworks alert (+ chime, Android vibration) for a new
touchdown, field goal, missed/blocked field goal, interception or lost fumble in a game the owner has a play on.

**Architecture:** Scoring plays come from score jumps in the 5 s ESPN scoreboard poll (+6..+8 touchdown, +3 field
goal); non-scoring big plays come from the 10 s ESPN summary that already feeds the drive field. A pure `detect`
function diffs each poll against what the page saw before; `show` draws the overlay.

**Tech Stack:** plain browser JS (no libraries), canvas, Web Audio, `node --test` with the repo's vm/fake-DOM style.

**Spec:** `docs/superpowers/specs/2026-11-16-live-play-alert-design.md`

## Global Constraints

- Only games on the "Đang đá & chờ kết quả" card (`rawFilter(liveInPlayRows())`), NFL/NCAAF.
- No alert for anything that happened before the page saw the game; one alert per play.
- Tap anywhere dismisses; auto-dismiss ~4 s; `prefers-reduced-motion` → banner, no particles.
- Texts: `TOUCHDOWN`, `FIELD GOAL`, `FIELD GOAL MISSED`, `INTERCEPTION`, `FUMBLE`; bet line
  `Bạn đặt <pick> · đang thắng | đang thua | đang hòa` (from `ActionsScoreboard.betStatus`).
- Static files are cache-busted by `build_site.py`; a new static file needs only a `<script>` tag with `?v=__STATIC_V__`.

## Review Focus

- Page hidden / phone asleep for minutes, then visible again → no burst of old alerts (re-baseline when the last
  look is older than 60 s).
- Pick-six / fumble-return touchdown → one TOUCHDOWN alert, not an extra INTERCEPTION alert.
- Score correction (score goes down) or PAT / 2-pt / safety (+1/+2) → no alert.
- Two alerts at once (touchdown in one game while another game kicks a field goal) → queued, shown one after another.
- Game ends on a walk-off field goal (state becomes final in the same poll) → still alerts.

---

### Task 1: ESPN non-scoring big plays

**Files:** Modify `src/actions_tracker/templates/static/live-scores.js`; Test `tests/frontend/live_scores.test.cjs`

**Interfaces:**
- Produces: `ActionsLiveScores.parseBigPlays(summary, event, eventId) -> Array<{id: string, kind: "interception"|"fumble_lost"|"field_goal_missed", side: "away"|"home", text: string|null}>`
  where `side` is the team that GAINED from the play. Plays of the last `drives.previous` drive and `drives.current`;
  offense = that drive's `team.id`. Live drive rows carry them as `drive.big_plays`.

- [ ] Test `big plays come from the last two drives and name the team that gained`: previous drive (NE, away) ending
  `Pass Interception Return` id `"9001"` → `{id:"9001", kind:"interception", side:"home"}`; current drive (DET, home)
  with `Fumble Recovery (Opponent)` → `fumble_lost`, side `away`; `Blocked Field Goal` and `Field Goal Missed` →
  `field_goal_missed`; `Fumble Recovery (Own)`, `Field Goal Good`, `Interception Return Touchdown`, plays without id → none.
- [ ] Run, see it fail; implement; run `node --test tests/frontend/*.test.cjs`, all pass; commit.

### Task 2: Detect new big plays on the page

**Files:** Create `src/actions_tracker/templates/static/big-play.js`; Test `tests/frontend/big_play.test.cjs`

**Interfaces:**
- Produces: `ActionsBigPlay.detect(memory: Map, games: Array<card>, now: number) -> Array<{game_id, kind, side}>`
  (kinds above + `"touchdown"`, `"field_goal"`); `card` = merged live card (`game_id, state, away_score, home_score,
  drive.big_plays`). Mutates `memory`.
- [ ] Tests: first sight → `[]`; home 14→21 → `touchdown/home`; away 3→6 → `field_goal/away`; +1, +2, score down → `[]`;
  new big play id → that event, same id next poll → `[]`; last look 61 s ago → `[]` and re-baselined;
  state `final` with +3 in the same poll → `field_goal`.
- [ ] Run, fail, implement, pass, commit.

### Task 3: Overlay and page wiring

**Files:** Modify `big-play.js` (add `show(event, card)` + queue + chime + vibrate), `index.html` (script tag; call
`ActionsBigPlay.observe(cards)` in `refreshLiveScores` with the same merged cards as `renderLiveScoreboards`).

**Interfaces:**
- Consumes: `detect`; `ActionsScoreboard.betStatus(card)`.
- Produces: `ActionsBigPlay.observe(cards: Array<card>) -> void` (detect, then queue `show` per event).
- [ ] Test (`big_play.test.cjs`, fake DOM): `observe` twice with a +7 jump appends one `.bp-overlay` whose text has
  `TOUCHDOWN`, the team abbreviation and `Bạn đặt`; tone class `bp-good` when the scoring side is the bet side.
- [ ] Run, fail, implement, pass; Playwright screenshot of a TOUCHDOWN and an INTERCEPTION overlay (phone); full
  `python -m pytest -q` + node tests; commit; PR; merge.
