# Actions Expert Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tự động thu thập picks của expert trên Action Network (NFL/NCAAF/NBA trước), chấm theo kết quả trận, phân tích Consensus / Expert / Expert-vs-Public, xuất Excel + dashboard trên GitHub Pages.

**Architecture:** Pipeline Python thuần chạy trên GitHub Actions mỗi 4 giờ: `fetch → parse → SQLite upsert → grade → analysis (pandas) → Excel + HTML tĩnh`. SQLite commit trong repo là nguồn dữ liệu chính; analysis chỉ đọc DB.

**Tech Stack:** Python ≥3.12 (CI 3.12, local 3.14), requests, pandas, openpyxl, pytest; Chart.js 4.4.1 (cdnjs) trong HTML; GitHub Actions + GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-09-actions-expert-tracker-design.md`

## Global Constraints

- Giải: `nfl, ncaaf, nba` bật; `mlb, nhl, ncaab` có trong config nhưng tắt (`enabled=False`).
- Chỉ market `spread`, `ml`, `total`, `period == 'game'`, không `player_id`. Pick `type` giữ: `spread_home, spread_away, ml_home, ml_away, over, under`.
- Nguồn: `https://www.actionnetwork.com/{league}/picks` và `https://api.actionnetwork.com/web/v2/scoreboard/{league}?bookIds=15`; book `"15"` cho line + % public.
- Lịch sự: UA trình duyệt, nghỉ 2–4 s giữa request, retry 3 lần backoff 2/4/8 s cho lỗi mạng/5xx/429.
- `MIN_EXPERTS = 3`; bucket consensus `[50,60) [60,75) [75,90) [90,100]`; `MIN_SAMPLE = 20` → `low_sample`; public `heavy` ≥ 65; money-vs-tickets ≥ 15 điểm; odds thiếu → −110; hòa vốn −110 = 52,38%.
- Tuần trend: thứ Hai–Chủ nhật theo `America/New_York`.
- Không bao giờ xóa dòng DB; parse lỗi cấu trúc → không ghi gì cho giải đó.
- Repo GitHub `hnguyen76/actions-tracker`, public. Commit message kết thúc bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- UI tiếng Việt, thuật ngữ kèo tiếng Anh; `<meta name="robots" content="noindex">`.
- Tên bảng/sheet: `Picks, Consensus, Experts, Expert_Habits, Expert_vs_Public, Trend_Weekly, Upcoming`.

## Review Focus

1. **Giải đang nghỉ mùa / trang không có picks** (`profiles` rỗng, scoreboard `games: []`) → không phải lỗi; giải được đánh dấu thành công với 0 picks. Chỉ thiếu `__NEXT_DATA__` hoặc thiếu khóa `initialExpertsResponse` mới là lỗi. Test ở Task 3.
2. **DB rỗng lần chạy đầu** → mọi bảng phân tích trả DataFrame rỗng đúng cột, Excel + HTML vẫn tạo được, dashboard hiện "Chưa có dữ liệu". Test ở Task 6 và Task 10.
3. **Trận hoãn/hủy** (`status` khác `complete` mãi mãi, ví dụ `postponed`, `cancelled`) → pick không được chấm, không vào thống kê, nhưng vẫn không hiện ở "Kèo sắp tới" khi `start_time` đã qua. Test ở Task 5 và Task 6.
4. **Pick thiếu odds** (`odds` None/0) → tính lãi như −110, không crash. Test ở Task 5.
5. **Expert đổi pick** (2 pick cùng game+market, khác side) → chỉ pick `created_at` mới nhất được tính 1 phiếu. Test ở Task 6.

---

## File Structure

| File | Trách nhiệm |
|---|---|
| `pyproject.toml` | package `actions_tracker` (src layout), deps, pytest config |
| `src/actions_tracker/config.py` | `LEAGUES`, hằng số ngưỡng, URL |
| `src/actions_tracker/fetch.py` | HTTP có retry/delay |
| `src/actions_tracker/parse.py` | HTML/JSON → row dicts |
| `src/actions_tracker/db.py` | schema + upsert + league_status |
| `src/actions_tracker/grading.py` | chấm side, lãi theo odds, nhãn, `load_graded_picks` |
| `src/actions_tracker/analysis/stats.py` | `summarize`, `wilson_ci` |
| `src/actions_tracker/analysis/consensus.py` | A + Upcoming |
| `src/actions_tracker/analysis/experts.py` | B |
| `src/actions_tracker/analysis/public.py` | C |
| `src/actions_tracker/analysis/trend.py` | xu hướng tuần |
| `src/actions_tracker/analysis/__init__.py` | `build_tables(conn, now) -> dict[str, DataFrame]` |
| `src/actions_tracker/export_excel.py` | ghi xlsx |
| `src/actions_tracker/build_site.py` + `templates/index.html` | dashboard |
| `src/actions_tracker/cli.py`, `__main__.py` | orchestration, exit code |
| `scripts/capture_fixtures.py` | tải + cắt gọn fixture thật |
| `tests/…`, `tests/fixtures/…` | test |
| `.github/workflows/collect.yml` | cron + Pages |

**Bổ sung so với spec mục 5:** bảng `league_status(league TEXT PK, last_success_at TEXT, last_error TEXT, last_error_at TEXT)` để dashboard hiện "cập nhật lần cuối" từng giải (spec mục 8, 10 yêu cầu nhưng mục 5 chưa có bảng).

---

### Task 1: Repo GitHub + kiểm tra IP GitHub Actions có bị chặn

**Files:**
- Create: `.gitignore`, `.github/workflows/probe.yml`

- [ ] **Step 1: Tạo `.gitignore`** với `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`.

- [ ] **Step 2: Tạo `probe.yml`** — `workflow_dispatch` only, `ubuntu-latest`, một step chạy cho `league in nfl ncaaf nba`: `curl -s -A "<UA trình duyệt>" -o /dev/null -w "$league picks %{http_code} %{size_download}\n" https://www.actionnetwork.com/$league/picks` và tương tự cho scoreboard v2 `?bookIds=15`; thêm `grep -c __NEXT_DATA__` trên HTML picks nfl.

- [ ] **Step 3: Tạo repo và push**

```bash
git add .gitignore .github/workflows/probe.yml
git commit -m "ci: add Action Network reachability probe"
gh repo create hnguyen76/actions-tracker --public --source . --push
```

- [ ] **Step 4: Chạy probe**

Run: `gh workflow run probe.yml && sleep 5 && gh run watch $(gh run list -w probe.yml -L1 --json databaseId -q '.[0].databaseId') && gh run view --log $(gh run list -w probe.yml -L1 --json databaseId -q '.[0].databaseId') | grep -E "picks|scoreboard|__NEXT"`
Expected: 6 dòng `200` với size > 10000, và đếm `__NEXT_DATA__` ≥ 1.
**Nếu có 403/429/size nhỏ:** DỪNG, báo người dùng; chuyển sang phương án dự phòng spec mục 10 (collector chạy Task Scheduler local) trước khi tiếp Task 11.

---

### Task 2: Scaffold, config, stats

**Files:**
- Create: `pyproject.toml`, `src/actions_tracker/__init__.py`, `src/actions_tracker/config.py`, `src/actions_tracker/analysis/__init__.py` (tạm để trống), `src/actions_tracker/analysis/stats.py`
- Test: `tests/test_stats.py`

**Interfaces:**
- Produces:
  - `config.LEAGUES: dict[str, bool]` = `{"nfl": True, "ncaaf": True, "nba": True, "mlb": False, "nhl": False, "ncaab": False}`
  - `config.PICKS_URL = "https://www.actionnetwork.com/{league}/picks"`, `config.SCOREBOARD_URL = "https://api.actionnetwork.com/web/v2/scoreboard/{league}?bookIds=15"`, `config.BOOK_ID = "15"`
  - `config.MIN_EXPERTS = 3`, `MIN_SAMPLE = 20`, `HEAVY_PUBLIC = 65`, `MONEY_TICKET_GAP = 15`, `DEFAULT_ODDS = -110`, `BUCKETS = [(50, 60, "50-60"), (60, 75, "60-75"), (75, 90, "75-90"), (90, 100.01, "90-100")]`, `TZ = "America/New_York"`, `KEEP_TYPES = {"spread_home": ("spread","home"), "spread_away": ("spread","away"), "ml_home": ("ml","home"), "ml_away": ("ml","away"), "over": ("total","over"), "under": ("total","under")}`
  - `stats.american_profit(odds: int | None) -> float` — lãi của 1 unit khi thắng; None/0 → dùng −110.
  - `stats.wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]` — n=0 → `(nan, nan)`.
  - `stats.summarize(results: Sequence[str], odds: Sequence[int | None]) -> dict` với khóa `n, wins, losses, pushes, win_pct, ci_low, ci_high, units, roi, low_sample`. `n = wins+losses` (push loại); `win_pct = wins/n` (nan khi n=0); `units = Σ(american_profit(o) nếu win, −1 nếu loss, 0 nếu push)`; `roi = units/n`; `low_sample = n < MIN_SAMPLE`. Kết quả khác `win/loss/push` bị bỏ qua.

- [ ] **Step 1: Tạo venv và pyproject**

`pyproject.toml`: name `actions-tracker`, `requires-python = ">=3.12"`, deps `requests>=2.32`, `pandas>=2.2`, `openpyxl>=3.1`; optional `dev = ["pytest>=8"]`; setuptools src layout; package-data `actions_tracker = ["templates/*.html"]`; `[tool.pytest.ini_options] testpaths = ["tests"]`.

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
Expected: cài thành công.

- [ ] **Step 2: Viết test thất bại** `tests/test_stats.py`

```python
import math
from actions_tracker.analysis.stats import american_profit, wilson_ci, summarize

def test_american_profit():
    assert american_profit(-110) == 100 / 110
    assert american_profit(150) == 1.5
    assert american_profit(None) == 100 / 110
    assert american_profit(0) == 100 / 110

def test_wilson_ci_known_value():
    lo, hi = wilson_ci(55, 100)
    assert round(lo, 4) == 0.4524 and round(hi, 4) == 0.6439

def test_wilson_ci_empty():
    assert all(math.isnan(x) for x in wilson_ci(0, 0))

def test_summarize_mixed():
    s = summarize(["win", "loss", "push", "win", "pending"], [-110, -110, -110, 200, -110])
    assert (s["n"], s["wins"], s["losses"], s["pushes"]) == (3, 2, 1, 1)
    assert s["win_pct"] == 2 / 3
    assert math.isclose(s["units"], 100 / 110 + 2.0 - 1)
    assert math.isclose(s["roi"], s["units"] / 3)
    assert s["low_sample"] is True

def test_summarize_empty():
    s = summarize([], [])
    assert s["n"] == 0 and math.isnan(s["win_pct"]) and s["units"] == 0
```

- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_stats.py -v` → FAIL (ImportError).
- [ ] **Step 4: Implement** `config.py` và `stats.py` theo Interfaces.
- [ ] **Step 5: Run** cùng lệnh → 5 PASS.
- [ ] **Step 6: Commit** `git add pyproject.toml src tests && git commit -m "feat: scaffold package with config and stats helpers"`

---

### Task 3: Fixtures thật + parser

**Files:**
- Create: `scripts/capture_fixtures.py`, `src/actions_tracker/parse.py`
- Create (sinh ra): `tests/fixtures/{nfl,ncaaf,nba}_picks.html`, `tests/fixtures/{nfl,ncaaf,nba}_scoreboard.json`, viết tay `tests/fixtures/mini_picks.html`
- Test: `tests/test_parse.py`

**Interfaces:**
- Produces:
  - `class ParseError(Exception)`
  - `extract_next_data(html: str) -> dict` — lỗi `ParseError` nếu không có `<script id="__NEXT_DATA__">` hoặc JSON hỏng.
  - `@dataclass PicksPage: experts: list[dict]; picks: list[dict]; games: list[dict]`
  - `parse_picks_page(html: str, league: str) -> PicksPage` — `ParseError` nếu thiếu `props.pageProps.initialExpertsResponse.response.profiles`; danh sách rỗng là hợp lệ.
  - `@dataclass Scoreboard: games: list[dict]; lines: list[dict]`
  - `parse_scoreboard(data: dict, league: str) -> Scoreboard` — `ParseError` nếu thiếu khóa `games`.
  - Row dicts có đúng tên cột DB (Task 4):
    - expert: `id, name, username, followers`
    - game: `id, league, season, week, start_time, status, home_team_id, away_team_id, home_abbr, away_abbr, home_score, away_score` (score lấy `boxscore.total_home_points/total_away_points`, None nếu thiếu; abbr tra `teams[]` theo id, None nếu không thấy)
    - pick: `id, expert_id (=user_id), game_id, league, market, pick_side, line, odds, units, an_result, created_at, starts_at, settled_at, play_text` — `market, pick_side` từ `KEEP_TYPES`; `line = value` nhưng `None` khi market `ml`; `an_result = result` nếu thuộc `win/loss/push`, ngược lại None.
    - line: `game_id, market, side, line, odds, tickets_pct, money_pct` — từ `markets["15"].event.{spread,moneyline,total}`, `moneyline` → market `ml` (line None), `tickets_pct = bet_info.tickets.percent`, `money_pct = bet_info.money.percent` (None nếu thiếu `bet_info`); bỏ outcome có `side` không thuộc home/away/over/under; game không có book "15" → không có line.

- [ ] **Step 1: Viết `scripts/capture_fixtures.py`** — nhận danh sách league; với mỗi league tải picks HTML và scoreboard JSON (UA trình duyệt, nghỉ 3 s); với HTML, giữ lại chỉ `pageProps.initialExpertsResponse` bên trong một HTML tối thiểu `<html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"initialExpertsResponse":...}}}</script></body></html>`; ghi vào `tests/fixtures/`.

Run: `.venv/Scripts/python scripts/capture_fixtures.py nfl ncaaf nba`
Expected: 6 file; mỗi HTML < 1 MB.

- [ ] **Step 2: Viết tay `tests/fixtures/mini_picks.html`** — 2 profile: expert 1 (`id 1, name "A", username "a", followers 10`) có picks: `id 11 type spread_home period game value -3.5 odds -110 result win game_id 100`; `id 12 type ml_away period game value 0 odds 150 result pending`; `id 13 type custom player_id 9` (loại); `id 14 type under period firsthalf` (loại); `id 15 type away_under period game` (loại). Expert 2 (`id 2`) `picks: []`. Mỗi pick có `game` object với `id 100, status "complete", teams [{id 10, abbr "HOM"}, {id 20, abbr "AWY"}], home_team_id 10, away_team_id 20, season 2026, week 9, start_time "2026-11-06T01:15:00.000Z", boxscore {total_home_points 24, total_away_points 17}`.

- [ ] **Step 3: Viết test thất bại** `tests/test_parse.py`

```python
import json, pathlib, pytest
from actions_tracker.parse import parse_picks_page, parse_scoreboard, extract_next_data, ParseError
from actions_tracker.config import KEEP_TYPES
F = pathlib.Path(__file__).parent / "fixtures"

def test_mini_page_maps_and_filters():
    p = parse_picks_page((F / "mini_picks.html").read_text("utf-8"), "nfl")
    assert {e["id"] for e in p.experts} == {1, 2}
    assert [(x["id"], x["market"], x["pick_side"], x["line"], x["an_result"]) for x in p.picks] == [
        (11, "spread", "home", -3.5, "win"), (12, "ml", "away", None, None)]
    g = {x["id"]: x for x in p.games}[100]
    assert (g["home_abbr"], g["away_abbr"], g["home_score"], g["away_score"], g["status"]) == ("HOM", "AWY", 24, 17, "complete")

@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_real_page_counts_match_raw(league):
    html = (F / f"{league}_picks.html").read_text("utf-8")
    raw = extract_next_data(html)["props"]["pageProps"]["initialExpertsResponse"]["response"]["profiles"]
    expected = sum(1 for pr in raw for k in (pr.get("picks") or [])
                   if k["type"] in KEEP_TYPES and k["period"] == "game" and not k.get("player_id"))
    p = parse_picks_page(html, league)
    assert len(p.picks) == expected and len(p.experts) == len(raw)
    assert all(x["league"] == league for x in p.picks)

@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_real_scoreboard(league):
    s = parse_scoreboard(json.loads((F / f"{league}_scoreboard.json").read_text("utf-8")), league)
    assert {l["market"] for l in s.lines} <= {"spread", "ml", "total"}
    assert {l["side"] for l in s.lines} <= {"home", "away", "over", "under"}
    assert all(l["line"] is None for l in s.lines if l["market"] == "ml")

def test_empty_offseason_is_valid():
    html = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"initialExpertsResponse":{"response":{"profiles":[]}}}}}</script>'
    p = parse_picks_page(html, "mlb")
    assert p.picks == [] and p.experts == []
    assert parse_scoreboard({"games": []}, "mlb").games == []

def test_structure_change_raises():
    with pytest.raises(ParseError):
        parse_picks_page("<html>no data</html>", "nfl")
    with pytest.raises(ParseError):
        parse_picks_page('<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{}}}</script>', "nfl")
    with pytest.raises(ParseError):
        parse_scoreboard({"error": "x"}, "nfl")
```

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest tests/test_parse.py -v` → FAIL (ImportError).
- [ ] **Step 5: Implement** `parse.py` theo Interfaces (regex lấy script `__NEXT_DATA__`, `json.loads`).
- [ ] **Step 6: Run** → tất cả PASS.
- [ ] **Step 7: Commit** `git add scripts src tests && git commit -m "feat: parse Action Network picks pages and scoreboard"`

---

### Task 4: Database

**Files:**
- Create: `src/actions_tracker/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: row dicts của Task 3.
- Produces:
  - `connect(path: str | Path) -> sqlite3.Connection` — tạo thư mục cha, bật `foreign_keys=OFF`, `row_factory=sqlite3.Row`, tạo schema spec mục 5 + `league_status` nếu chưa có.
  - `upsert_experts(conn, rows: list[dict], seen_at: str) -> None` — insert set `first_seen=last_seen=seen_at`; conflict cập nhật name/username/followers/last_seen, giữ first_seen.
  - `upsert_games(conn, rows: list[dict], updated_at: str) -> None` — conflict: mỗi cột = `COALESCE(excluded.col, games.col)` (không ghi đè bằng NULL). Row có thể thiếu cột (chỉ cần `id`); cột thiếu coi như None.
  - `upsert_picks(conn, rows: list[dict], updated_at: str) -> None` — conflict: cập nhật `an_result, settled_at, odds, line, units, updated_at` bằng COALESCE như trên.
  - `upsert_lines(conn, rows: list[dict], captured_at: str) -> None` — chỉ ghi row khi game tương ứng trong bảng `games` có `start_time > captured_at` (so chuỗi ISO UTC; cùng định dạng `YYYY-MM-DDTHH:MM:SS.sssZ`); game chưa có trong DB → bỏ qua.
  - `mark_league(conn, league: str, ok: bool, at: str, error: str | None = None) -> None` — ok → `last_success_at=at`; lỗi → `last_error, last_error_at`.
  - Mọi hàm ghi tự `commit`.

- [ ] **Step 1: Viết test thất bại** `tests/test_db.py`

```python
from actions_tracker import db

G = dict(id=100, league="nfl", season=2026, week=9, start_time="2026-11-10T01:00:00.000Z", status="scheduled",
         home_team_id=10, away_team_id=20, home_abbr="HOM", away_abbr="AWY", home_score=None, away_score=None)
P = dict(id=11, expert_id=1, game_id=100, league="nfl", market="spread", pick_side="home", line=-3.5, odds=-110,
         units=1, an_result=None, created_at="2026-11-09T10:00:00.000Z", starts_at=G["start_time"], settled_at=None, play_text="HOM -3.5")
L = dict(game_id=100, market="spread", side="home", line=-3.5, odds=-110, tickets_pct=60, money_pct=70)

def test_upsert_idempotent_and_coalesce(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [G], "t1"); db.upsert_picks(c, [P], "t1")
    db.upsert_games(c, [G | {"status": "complete", "home_score": 24, "away_score": 17}], "t2")
    db.upsert_games(c, [G | {"home_abbr": None}], "t3")
    db.upsert_picks(c, [P | {"an_result": "win"}], "t2"); db.upsert_picks(c, [P], "t3")
    assert c.execute("select count(*) from picks").fetchone()[0] == 1
    g = c.execute("select status, home_score, home_abbr from games").fetchone()
    assert tuple(g) == ("scheduled", 24, "HOM")  # status từ lần cuối non-null; score/abbr không bị NULL đè
    assert c.execute("select an_result from picks").fetchone()[0] == "win"
    db.upsert_games(c, [{"id": 100, "status": "complete"}], "t4")
    assert tuple(c.execute("select status, home_abbr from games").fetchone()) == ("complete", "HOM")

def test_lines_frozen_after_start(tmp_path):
    c = db.connect(tmp_path / "a.db"); db.upsert_games(c, [G], "t")
    db.upsert_lines(c, [L], "2026-11-09T20:00:00.000Z")
    db.upsert_lines(c, [L | {"line": -7.0}], "2026-11-10T02:00:00.000Z")
    db.upsert_lines(c, [L | {"game_id": 999}], "2026-11-09T20:00:00.000Z")
    rows = c.execute("select game_id, line from closing_lines").fetchall()
    assert [tuple(r) for r in rows] == [(100, -3.5)]

def test_experts_first_seen_kept(tmp_path):
    c = db.connect(tmp_path / "a.db")
    e = dict(id=1, name="A", username="a", followers=10)
    db.upsert_experts(c, [e], "t1"); db.upsert_experts(c, [e | {"followers": 20}], "t2")
    assert tuple(c.execute("select first_seen, last_seen, followers from experts").fetchone()) == ("t1", "t2", 20)

def test_mark_league(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.mark_league(c, "nfl", True, "t1"); db.mark_league(c, "nfl", False, "t2", "boom")
    assert tuple(c.execute("select last_success_at, last_error, last_error_at from league_status").fetchone()) == ("t1", "boom", "t2")
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_db.py -v` → FAIL.
- [ ] **Step 3: Implement** `db.py`. Lưu ý test 1: `status` đi theo COALESCE nên lần upsert t3 (status "scheduled") ghi lại "scheduled" — đúng ý: status mới nhất từ nguồn thắng; chỉ NULL mới không đè.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: sqlite schema and idempotent upserts"` (sau `git add src tests`).

---

### Task 5: Fetch + grading

**Files:**
- Create: `src/actions_tracker/fetch.py`, `src/actions_tracker/grading.py`
- Test: `tests/test_fetch.py`, `tests/test_grading.py`

**Interfaces:**
- Produces (fetch):
  - `class FetchError(Exception)`
  - `class Fetcher: __init__(self, session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep, delay: tuple[float, float] = (2, 4))`; `get_text(url) -> str`; `get_json(url) -> dict`. Trước mỗi request (trừ request đầu) gọi `sleep(random.uniform(*delay))`. Retry tối đa 3 lần cho `requests.ConnectionError`, `Timeout`, status 5xx/429 với `sleep(2)`, `sleep(4)`, `sleep(8)`; 4xx khác → `FetchError` ngay; hết retry → `FetchError`. Timeout 30 s, header UA trình duyệt.
  - `fetch_league(fetcher: Fetcher, league: str) -> tuple[str, dict]` — (picks HTML, scoreboard JSON).
- Produces (grading):
  - `grade_side(market: str, side: str, line: float | None, home_score: int, away_score: int) -> str` — `"win"|"loss"|"push"` theo spec mục 6 (spread: line là line của chính side; total: line là tổng).
  - `opposite(side: str) -> str` — home↔away, over↔under.
  - `load_graded_picks(conn) -> pandas.DataFrame` — mỗi dòng = 1 pick join games, experts, closing_lines (của side được chọn và side đối diện). Cột: `pick_id, expert_id, expert_name, league, game_id, market, pick_side, line, odds, created_at, start_time, status, home_abbr, away_abbr, home_score, away_score, close_line, close_odds, opp_close_odds, tickets_pct, money_pct, home_away, fav_dog, over_under, side_result, expert_result`.
    - `side_result`: chấm theo `close_line` (fallback: median `line` của mọi pick cùng game+market+side), chỉ khi `status == "complete"`, ngược lại None.
    - `expert_result`: `an_result` nếu có; ngược lại nếu complete thì chấm theo `line` của pick; ngược lại None.
    - `fav_dog`: spread → dấu của `close_line` (fallback `line`): <0 favorite, >0 underdog, 0 pickem; ml → `close_odds < opp_close_odds` favorite, `>` underdog, bằng → pickem, thiếu → dùng odds của pick so với −100 (âm favorite); total → None.
    - `home_away`: spread/ml → pick_side; total → None. `over_under`: total → pick_side; khác → None.
    - `close_odds`, `opp_close_odds` None → giữ None (stats tự dùng −110).

- [ ] **Step 1: Viết test thất bại** `tests/test_fetch.py` — dùng session giả trả về chuỗi response định sẵn:

```python
import pytest, requests
from actions_tracker.fetch import Fetcher, FetchError

class R:
    def __init__(s, code, text="ok"): s.status_code, s.text = code, text
    def json(s): return {"games": []}
class S:
    def __init__(s, seq): s.seq, s.calls = list(seq), 0
    def get(s, url, **kw):
        s.calls += 1; x = s.seq.pop(0)
        if isinstance(x, Exception): raise x
        return x

def test_retries_then_succeeds():
    slept = []; s = S([R(503), requests.ConnectionError(), R(200, "hi")])
    assert Fetcher(s, sleep=slept.append).get_text("u") == "hi"
    assert s.calls == 3 and slept[:2] == [2, 4]

def test_403_fails_fast():
    s = S([R(403)])
    with pytest.raises(FetchError): Fetcher(s, sleep=lambda x: None).get_text("u")
    assert s.calls == 1

def test_gives_up_after_retries():
    s = S([R(429)] * 4)
    with pytest.raises(FetchError): Fetcher(s, sleep=lambda x: None).get_text("u")
    assert s.calls == 4
```

- [ ] **Step 2: Viết test thất bại** `tests/test_grading.py`

```python
import pytest
from actions_tracker import db
from actions_tracker.grading import grade_side, load_graded_picks

@pytest.mark.parametrize("market,side,line,h,a,exp", [
    ("spread", "home", -3.5, 24, 20, "win"), ("spread", "home", -3.5, 23, 20, "loss"),
    ("spread", "home", -3.0, 23, 20, "push"), ("spread", "away", 3.0, 23, 20, "push"),
    ("spread", "away", 7.5, 27, 20, "win"), ("ml", "away", None, 17, 24, "win"),
    ("ml", "home", None, 20, 20, "push"), ("total", "over", 44.5, 24, 21, "win"),
    ("total", "under", 45.0, 24, 21, "push"), ("total", "under", 44.5, 24, 21, "loss")])
def test_grade_side(market, side, line, h, a, exp):
    assert grade_side(market, side, line, h, a) == exp

def _seed(tmp_path, status="complete", pick_odds=-110, an_result=None):
    c = db.connect(tmp_path / "g.db")
    db.upsert_experts(c, [dict(id=1, name="A", username="a", followers=1)], "t")
    db.upsert_games(c, [dict(id=100, league="nfl", season=2026, week=9, start_time="2026-11-10T01:00:00.000Z",
        status="scheduled", home_team_id=10, away_team_id=20, home_abbr="HOM", away_abbr="AWY", home_score=None, away_score=None)], "t")
    db.upsert_lines(c, [dict(game_id=100, market="spread", side="home", line=-3.0, odds=-105, tickets_pct=40, money_pct=60),
                        dict(game_id=100, market="spread", side="away", line=3.0, odds=-115, tickets_pct=60, money_pct=40),
                        dict(game_id=100, market="ml", side="home", line=None, odds=-150, tickets_pct=50, money_pct=50),
                        dict(game_id=100, market="ml", side="away", line=None, odds=130, tickets_pct=50, money_pct=50)],
                   "2026-11-09T00:00:00.000Z")
    db.upsert_games(c, [dict(id=100, status=status, home_score=23 if status == "complete" else None,
        away_score=20 if status == "complete" else None)], "t2")
    db.upsert_picks(c, [dict(id=11, expert_id=1, game_id=100, league="nfl", market="spread", pick_side="home", line=-2.5,
        odds=pick_odds, units=1, an_result=an_result, created_at="2026-11-09T10:00:00.000Z", starts_at=None, settled_at=None, play_text=""),
        dict(id=12, expert_id=1, game_id=100, league="nfl", market="ml", pick_side="away", line=None,
        odds=130, units=1, an_result=None, created_at="2026-11-09T10:00:00.000Z", starts_at=None, settled_at=None, play_text="")], "t")
    return c

def test_closing_vs_expert_line(tmp_path):
    df = load_graded_picks(_seed(tmp_path)).set_index("pick_id")
    r = df.loc[11]
    assert r.side_result == "push"        # chấm theo close -3.0, thắng 3
    assert r.expert_result == "win"       # chấm theo line của pick -2.5
    assert (r.fav_dog, r.home_away, r.over_under) == ("favorite", "home", None)
    assert (r.close_odds, r.opp_close_odds, r.tickets_pct) == (-105, -115, 40)
    assert df.loc[12].fav_dog == "underdog"

def test_an_result_wins_over_self_grade(tmp_path):
    assert load_graded_picks(_seed(tmp_path, an_result="loss")).set_index("pick_id").loc[11].expert_result == "loss"

@pytest.mark.parametrize("status", ["postponed", "cancelled", "inprogress"])
def test_not_complete_not_graded(tmp_path, status):
    df = load_graded_picks(_seed(tmp_path, status=status))
    assert df.side_result.isna().all() and df.expert_result.isna().all()
```

- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_fetch.py tests/test_grading.py -v` → FAIL.
- [ ] **Step 4: Implement** `fetch.py` và `grading.py` (SQL join + pandas; chấm từng dòng bằng `grade_side`).
- [ ] **Step 5: Run** → PASS; chạy toàn bộ `pytest` → PASS.
- [ ] **Step 6: Commit** `git add src tests && git commit -m "feat: resilient fetcher and pick grading"`

---

### Task 6: Consensus (A) + Upcoming

**Files:**
- Create: `src/actions_tracker/analysis/consensus.py`, `tests/__init__.py` (rỗng), `tests/helpers.py` (hàm `make_picks(rows: list[dict]) -> DataFrame` điền mặc định đủ cột của `load_graded_picks` cho test)
- Test: `tests/test_consensus.py`

**Interfaces:**
- Consumes: DataFrame `load_graded_picks`; `stats.summarize`; config.
- Produces:
  - `consensus_games(picks: DataFrame) -> DataFrame` — 1 dòng/(game_id, market) có ≥ `MIN_EXPERTS` phiếu và không hòa phiếu. Phiếu: mỗi expert lấy pick `created_at` lớn nhất. Cột: `game_id, league, market, start_time, status, home_abbr, away_abbr, side, votes, total_votes, majority_pct (0–100), bucket, side_result, side_odds, opp_odds, tickets_pct, money_pct` — `side_result/side_odds/opp_odds/tickets_pct/money_pct` lấy từ dòng của side đa số (`close_odds`/`opp_close_odds`).
  - `consensus_summary(cg: DataFrame) -> DataFrame` — group `(league, market, bucket)` + dòng tổng `league="ALL"` và `market="ALL"`; cột = khóa `summarize` (theo `side_result`, `side_odds`) + `fade_win_pct, fade_roi` (kết quả đảo win↔loss, odds = `opp_odds`). Chỉ dòng có `side_result` không null.
  - `upcoming(cg: DataFrame, summary: DataFrame, now: str) -> DataFrame` — dòng có `status` ∉ {complete} và `start_time > now`; thêm `hist_win_pct, hist_n` từ summary cùng `(league, market, bucket)`; sắp theo `start_time`.
  - Mọi hàm trả DataFrame rỗng có đủ cột khi input rỗng.

- [ ] **Step 1: Viết test thất bại**

```python
import math
from tests.helpers import make_picks
from actions_tracker.analysis.consensus import consensus_games, consensus_summary, upcoming

def votes(game, sides, result_home="win", status="complete", market="spread"):
    return [dict(pick_id=game * 100 + i, expert_id=i, game_id=game, market=market, pick_side=s, status=status,
                 side_result=(result_home if s == "home" else {"win": "loss", "loss": "win", "push": "push"}[result_home]),
                 close_odds=-110, opp_close_odds=-110, start_time="2026-11-20T01:00:00.000Z") for i, s in enumerate(sides)]

def test_bucket_votes_and_min_experts():
    df = make_picks(votes(1, ["home"] * 3 + ["away"]) + votes(2, ["home", "away"]) + votes(3, ["home", "home", "away", "away"]))
    cg = consensus_games(df)
    assert list(cg.game_id) == [1]                      # game 2 <3 phiếu, game 3 hòa phiếu
    r = cg.iloc[0]
    assert (r.side, r.votes, r.total_votes, r.majority_pct, r.bucket) == ("home", 3, 4, 75.0, "75-90")

def test_latest_pick_per_expert_counts_once():
    rows = votes(1, ["home", "home", "home"])
    rows.append(dict(rows[0], pick_id=999, pick_side="away", created_at="2026-11-09T23:00:00.000Z"))
    rows[0]["created_at"] = "2026-11-09T10:00:00.000Z"
    r = consensus_games(make_picks(rows)).iloc[0]
    assert (r.votes, r.total_votes) == (2, 3)

def test_summary_follow_and_fade():
    df = make_picks(votes(1, ["home"] * 3, "win") + votes(2, ["home"] * 3, "loss") + votes(3, ["home"] * 3, "win"))
    s = consensus_summary(consensus_games(df))
    row = s[(s.league == "nfl") & (s.market == "spread") & (s.bucket == "90-100")].iloc[0]
    assert (row.n, row.wins) == (3, 2) and math.isclose(row.fade_win_pct, 1 / 3)

def test_upcoming_excludes_past_and_postponed():
    df = make_picks(votes(1, ["home"] * 3, status="scheduled") + votes(2, ["away"] * 3, status="postponed")
                    + [dict(r, start_time="2026-11-01T00:00:00.000Z") for r in votes(3, ["home"] * 3, status="scheduled")])
    cg = consensus_games(df)
    up = upcoming(cg, consensus_summary(cg), now="2026-11-10T00:00:00.000Z")
    assert list(up.game_id) == [1, 2]   # postponed nhưng start_time tương lai vẫn hiện; start_time đã qua thì không
```

- [ ] **Step 2: Viết test rỗng** `test_empty_inputs`: `consensus_games(make_picks([]))`, `consensus_summary`, `upcoming` đều `.empty` và có cột `bucket`/`hist_win_pct`.
- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_consensus.py -v` → FAIL.
- [ ] **Step 4: Implement** `tests/helpers.py` (mặc định: `league="nfl"`, `expert_name="E{expert_id}"`, `created_at="2026-11-09T12:00:00.000Z"`, `start_time="2026-11-06T01:00:00.000Z"`, `status="complete"`, các cột còn lại None; `expert_result` mặc định = `side_result`; `odds` mặc định −110) và `consensus.py`.
- [ ] **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `git add src tests && git commit -m "feat: expert consensus analysis and upcoming games"`

---

### Task 7: Expert analysis (B)

**Files:**
- Create: `src/actions_tracker/analysis/experts.py`
- Test: `tests/test_experts.py`

**Interfaces:**
- Produces:
  - `expert_summary(picks: DataFrame, now: str) -> DataFrame` — group `(expert_id, expert_name, league, market, window)`; `league`, `market` có thêm giá trị `"ALL"`; `window ∈ {"all", "last_30_days", "last_30_picks"}` (`last_30_days`: `start_time >= now − 30 ngày`; `last_30_picks`: 30 pick đã chấm có `start_time` mới nhất của expert trong nhóm đó). Cột = khóa `summarize` (theo `expert_result`, `odds`).
  - `expert_habits(picks: DataFrame) -> DataFrame` — với mỗi `(expert_id, expert_name, league ∪ ALL)` và `label_type ∈ {fav_dog, home_away, over_under}`, mỗi `label` không null: `share` (tỷ lệ pick có label đó trên số pick có label_type khác null) + khóa `summarize`.
  - `leaderboard(summary: DataFrame) -> DataFrame` — `window=="all" & league=="ALL" & market=="ALL" & n >= MIN_SAMPLE`, sắp `roi` giảm dần, thêm cột `rank` từ 1.

- [ ] **Step 1: Viết test thất bại**

```python
from tests.helpers import make_picks
from actions_tracker.analysis.experts import expert_summary, expert_habits, leaderboard

def mk(expert, n, result, fav="favorite", start="2026-11-05T00:00:00.000Z", market="spread"):
    return [dict(pick_id=expert * 1000 + i, expert_id=expert, game_id=i, market=market, pick_side="home",
                 expert_result=result, fav_dog=fav, home_away="home", start_time=start) for i in range(n)]

def test_summary_windows():
    df = make_picks(mk(1, 20, "win") + mk(1, 15, "loss", start="2026-09-01T00:00:00.000Z"))
    s = expert_summary(df, now="2026-11-09T00:00:00.000Z").set_index(["league", "market", "window"])
    assert s.loc[("ALL", "ALL", "all")].n == 35
    assert s.loc[("ALL", "ALL", "last_30_days")].n == 20
    assert s.loc[("ALL", "ALL", "last_30_picks")].wins == 20 and s.loc[("ALL", "ALL", "last_30_picks")].n == 30

def test_habits_share_and_win():
    df = make_picks(mk(1, 3, "win", fav="underdog") + mk(1, 1, "loss", fav="favorite"))
    h = expert_habits(df)
    r = h[(h.league == "ALL") & (h.label_type == "fav_dog") & (h.label == "underdog")].iloc[0]
    assert r.share == 0.75 and r.win_pct == 1.0

def test_leaderboard_min_sample_and_order():
    df = make_picks(mk(1, 25, "win") + mk(2, 25, "loss") + mk(3, 5, "win"))
    lb = leaderboard(expert_summary(df, now="2026-11-09T00:00:00.000Z"))
    assert list(lb.expert_id) == [1, 2] and list(lb["rank"]) == [1, 2]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (thêm test rỗng như Task 6).
- [ ] **Step 5: Commit** `git commit -m "feat: expert performance, habits and leaderboard"`

---

### Task 8: Expert vs Public (C) + Trend + build_tables

**Files:**
- Create: `src/actions_tracker/analysis/public.py`, `src/actions_tracker/analysis/trend.py`; Modify: `src/actions_tracker/analysis/__init__.py`
- Test: `tests/test_public_trend.py`

**Interfaces:**
- Produces:
  - `public_games(cg: DataFrame) -> DataFrame` — từ `consensus_games`; bỏ dòng `tickets_pct` null hoặc = 50. `public_side` = side đa số nếu `tickets_pct > 50` ngược lại side đối diện; `relation = "agree"|"contrarian"`; `heavy = max(tickets_pct, 100 − tickets_pct) >= HEAVY_PUBLIC`.
  - `public_summary(pg: DataFrame) -> DataFrame` — group `(league ∪ ALL, market ∪ ALL, relation, heavy)`, khóa `summarize` theo `side_result`, `side_odds`.
  - `money_vs_tickets(picks: DataFrame) -> DataFrame` — từ các (game, market, side) duy nhất trong `picks` có `money_pct − tickets_pct >= MONEY_TICKET_GAP` và đã chấm; group `(league ∪ ALL, market ∪ ALL)`, khóa `summarize` theo `side_result`, `close_odds`.
  - `weekly_trend(cg: DataFrame, picks: DataFrame, lb: DataFrame, pg: DataFrame) -> DataFrame` — cột `week_start (YYYY-MM-DD, thứ Hai theo America/New_York của start_time), series, n, wins, win_pct`; `series ∈ {"consensus_60plus", "top10_experts", "contrarian"}` (consensus: bucket ≠ "50-60"; top10: `expert_result` của expert trong 10 hạng đầu `lb`; contrarian: `relation=="contrarian"`).
  - `analysis.build_tables(conn, now: str) -> dict[str, DataFrame]` với khóa đúng tên sheet: `Picks` (load_graded_picks), `Consensus` (consensus_summary), `Experts` (expert_summary), `Expert_Habits`, `Expert_vs_Public` (public_summary nối money_vs_tickets với cột `relation="money>tickets"`), `Trend_Weekly`, `Upcoming`; thêm khóa `Leaderboard` (không thành sheet riêng — Excel bỏ qua, dashboard dùng).

- [ ] **Step 1: Viết test thất bại**

```python
from tests.helpers import make_picks
from actions_tracker.analysis.consensus import consensus_games
from actions_tracker.analysis.public import public_games, public_summary
from actions_tracker.analysis.trend import weekly_trend
import pandas as pd

def game(gid, tickets, result, start="2026-11-06T01:00:00.000Z"):
    return [dict(pick_id=gid * 10 + i, expert_id=i, game_id=gid, market="spread", pick_side="home",
                 side_result=result, tickets_pct=tickets, money_pct=tickets, start_time=start) for i in range(3)]

def test_relation_and_heavy():
    pg = public_games(consensus_games(make_picks(game(1, 70, "win") + game(2, 30, "loss") + game(3, 50, "win"))))
    r = pg.set_index("game_id")
    assert list(r.index) == [1, 2]
    assert (r.loc[1].relation, r.loc[1].heavy) == ("agree", True)
    assert (r.loc[2].relation, r.loc[2].heavy, r.loc[2].public_side) == ("contrarian", True, "away")
    s = public_summary(pg)
    assert s[(s.league == "ALL") & (s.market == "ALL") & (s.relation == "contrarian")].iloc[0].losses == 1

def test_week_bucket_eastern():
    # 2026-11-10T03:00Z = thứ Hai 22:00 ET 9/11 → tuần 2026-11-09; 2026-11-09T03:00Z = Chủ nhật 8/11 ET → tuần 2026-11-02
    df = make_picks(game(1, 70, "win", "2026-11-10T03:00:00.000Z") + game(2, 70, "loss", "2026-11-09T03:00:00.000Z"))
    cg = consensus_games(df)
    t = weekly_trend(cg, df, pd.DataFrame(columns=["expert_id", "rank"]), public_games(cg))
    c = t[t.series == "consensus_60plus"].set_index("week_start")
    assert (c.loc["2026-11-09"].wins, c.loc["2026-11-02"].wins) == (1, 0)
```

- [ ] **Step 2: Viết test** `test_build_tables_empty_db(tmp_path)`: `build_tables(db.connect(tmp_path/"e.db"), "2026-11-09T00:00:00.000Z")` trả đủ 8 khóa, mọi DataFrame `.empty`.
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run toàn bộ** `pytest` → PASS.
- [ ] **Step 6: Commit** `git commit -m "feat: expert-vs-public, weekly trend and table builder"`

---

### Task 9: Excel export

**Files:**
- Create: `src/actions_tracker/export_excel.py`
- Test: `tests/test_export_excel.py`

**Interfaces:**
- Produces: `write_report(tables: dict[str, DataFrame], path: Path) -> None` — ghi 7 sheet theo thứ tự `Upcoming, Consensus, Experts, Expert_Habits, Expert_vs_Public, Trend_Weekly, Picks` (bỏ qua `Leaderboard`); mỗi sheet `freeze_panes="A2"`, autofilter toàn vùng dữ liệu, cột rộng theo nội dung (tối đa 40); số % format `0.0%`, `roi` format `0.0%`. Sheet rỗng vẫn có hàng header. Ghi ra file tạm rồi `os.replace` để không để lại file hỏng.

- [ ] **Step 1: Test thất bại** — tạo tables nhỏ (1 dòng mỗi bảng) và tables rỗng (từ `build_tables` DB rỗng); sau `write_report`, mở bằng `openpyxl.load_workbook` và assert `wb.sheetnames == [...7 tên...]`, `ws.freeze_panes == "A2"`, `ws.auto_filter.ref` không None ở sheet có dữ liệu, hàng 1 sheet `Consensus` chứa `"win_pct"`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (pandas `ExcelWriter(engine="openpyxl")`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: excel report export"`

---

### Task 10: Dashboard HTML

**Files:**
- Create: `src/actions_tracker/build_site.py`, `src/actions_tracker/templates/index.html`
- Test: `tests/test_build_site.py`

Trước khi viết template: load skill `dataviz` (màu chart, stat tile, chú giải, light/dark).

**Interfaces:**
- Produces: `build_site(tables: dict[str, DataFrame], status: list[dict], out_dir: Path, xlsx: Path | None, generated_at: str) -> Path` — đọc template bằng `importlib.resources`; thay đúng một placeholder `/*__DATA__*/null` bằng JSON `{"generated_at", "league_status": status, "tables": {name: records}}` (NaN → null; escape `</` thành `<\/`); ghi `out_dir/index.html`; copy xlsx sang `out_dir/actions_report.xlsx` nếu có. `status` = các dòng `league_status`.
- Template (một file, không build step): `<html lang="vi">`, `<meta name="robots" content="noindex">`, viewport meta, Chart.js `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js`. Header: tên "Actions Expert Tracker", thời điểm cập nhật + trạng thái từng giải, nút "Tải Excel". Bộ lọc: giải (Tất cả/NFL/NCAAF/NBA/…lấy từ data), loại kèo (Tất cả/Spread/ML/Total), khoảng thời gian (7/30/90 ngày/Tất cả — áp cho Upcoming, Trend, Picks). 5 tab:
  1. **Kèo sắp tới** — bảng `Upcoming`: giờ đá (giờ máy người xem), trận `AWY @ HOM`, kèo, side đa số, `votes/total_votes`, `majority_pct`, % public tickets/money, win% lịch sử bucket + n.
  2. **Consensus** — bar chart win% theo bucket (đường kẻ 52,38%), bảng follow/fade ROI.
  3. **Experts** — bảng `Leaderboard`; bấm một dòng → panel thói quen (`Expert_Habits`) + 3 cửa sổ (`Experts`).
  4. **Expert vs Public** — bảng agree/contrarian × heavy, và dòng money>tickets.
  5. **Xu hướng** — line chart `Trend_Weekly`, 3 series.
  Mọi bảng hiện `n` và gắn nhãn "chưa đủ mẫu" khi `low_sample`. Bảng/biểu đồ rỗng hiện "Chưa có dữ liệu". Layout dùng được ở 375 px.

- [ ] **Step 1: Test thất bại**

```python
import json, re
from actions_tracker.build_site import build_site

def _data(html):
    return json.loads(re.search(r"const DATA = (.*?);\n", html, re.S).group(1))

def test_embeds_json_and_copies_xlsx(tmp_path):
    import pandas as pd
    x = tmp_path / "r.xlsx"; x.write_bytes(b"x")
    t = {"Upcoming": pd.DataFrame([{"game_id": 1, "majority_pct": float("nan"), "note": "</script>"}])}
    out = build_site(t, [{"league": "nfl", "last_success_at": "t"}], tmp_path / "site", x, "2026-11-09T00:00:00Z")
    html = out.read_text("utf-8")
    d = _data(html)
    assert d["tables"]["Upcoming"][0]["majority_pct"] is None
    assert "</script>" not in html.split("const DATA = ")[1].split(";\n")[0]
    assert (tmp_path / "site" / "actions_report.xlsx").exists()
    assert 'name="robots" content="noindex"' in html and "chart.umd.min.js" in html

def test_empty_tables_render(tmp_path):
    out = build_site({}, [], tmp_path / "s", None, "t")
    assert "Chưa có dữ liệu" in out.read_text("utf-8")
```

Template phải có dòng `const DATA = /*__DATA__*/null;` theo sau bởi xuống dòng.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** `build_site.py` + template. **Step 4: Run** → PASS.
- [ ] **Step 5: Kiểm tra bằng mắt** — sinh site từ fixtures (sau Task 11 có lệnh `run --offline`; tạm thời dùng DB seed của test grading) và mở bằng Playwright ở 1280 px và 375 px; chụp màn hình; kiểm tra không lỗi console, 5 tab chuyển được, bộ lọc đổi nội dung.
- [ ] **Step 6: Commit** `git commit -m "feat: static dashboard"`

---

### Task 11: CLI orchestration + end-to-end

**Files:**
- Create: `src/actions_tracker/cli.py`, `src/actions_tracker/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: mọi module trên.
- Produces:
  - `run(db_path: Path, report_path: Path, site_dir: Path, leagues: list[str], fetcher: Fetcher, now: str) -> int` — với mỗi league: `fetch_league` → `parse_*` → upsert (experts, games từ picks page, games từ scoreboard, picks, lines với `captured_at=now`) → `mark_league(ok=True)`; bắt `FetchError`/`ParseError` → `mark_league(ok=False, error=str(e))`, log, tiếp tục. Sau đó `build_tables` → `write_report` → `build_site` (dù có giải lỗi). Exit code: `2` nếu có `ParseError` bất kỳ (đổi cấu trúc); `1` nếu mọi giải đều lỗi; `0` còn lại.
  - `main(argv: list[str] | None = None) -> int` — `python -m actions_tracker run [--leagues nfl,nba] [--db data/actions.db] [--report reports/actions_report.xlsx] [--site site] [--offline tests/fixtures]`; mặc định leagues = các league `enabled` trong config; `--offline DIR` dùng fetcher đọc `{league}_picks.html` / `{league}_scoreboard.json` từ DIR (để dev và e2e). `now` = UTC hiện tại, định dạng `YYYY-MM-DDTHH:MM:SS.000Z`. Log ra stdout: số experts/picks/games/lines mỗi giải.

- [ ] **Step 1: Test thất bại**

```python
from pathlib import Path
from actions_tracker.cli import main
FX = str(Path(__file__).parent / "fixtures")

def test_offline_end_to_end(tmp_path):
    args = ["run", "--offline", FX, "--leagues", "nfl,ncaaf,nba", "--db", str(tmp_path / "a.db"),
            "--report", str(tmp_path / "r.xlsx"), "--site", str(tmp_path / "site")]
    assert main(args) == 0
    assert (tmp_path / "r.xlsx").exists() and (tmp_path / "site" / "index.html").exists()
    import sqlite3
    c = sqlite3.connect(tmp_path / "a.db")
    n1 = c.execute("select count(*) from picks").fetchone()[0]
    assert n1 > 0
    assert main(args) == 0
    assert c.execute("select count(*) from picks").fetchone()[0] == n1      # idempotent
    assert c.execute("select count(*) from league_status where last_success_at is not null").fetchone()[0] == 3

def test_parse_error_exit_2_and_others_continue(tmp_path):
    d = tmp_path / "fx"; d.mkdir()
    for f in Path(FX).glob("nba_*"): (d / f.name).write_bytes(f.read_bytes())
    (d / "nfl_picks.html").write_text("<html>changed</html>"); (d / "nfl_scoreboard.json").write_text('{"games": []}')
    rc = main(["run", "--offline", str(d), "--leagues", "nfl,nba", "--db", str(tmp_path / "a.db"),
               "--report", str(tmp_path / "r.xlsx"), "--site", str(tmp_path / "s")])
    assert rc == 2 and (tmp_path / "s" / "index.html").exists()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run toàn bộ** `pytest` → PASS.
- [ ] **Step 5: Chạy thật local** `.venv/Scripts/python -m actions_tracker run` → exit 0, log có số picks > 0 cho nfl/ncaaf/nba; mở `site/index.html` kiểm tra (Playwright, 1280 và 375 px).
- [ ] **Step 6: Commit** `git add src tests data reports site && git commit -m "feat: cli pipeline with first live data"`

---

### Task 12: Workflow cron + GitHub Pages

**Files:**
- Create: `.github/workflows/collect.yml`; Delete: `.github/workflows/probe.yml`
- Modify: `README.md` (tạo mới: mô tả ngắn, link dashboard, cách chạy local)

**Interfaces:** workflow gọi `python -m actions_tracker run`.

- [ ] **Step 1: Viết `collect.yml`**
  - `on: schedule: - cron: "0 */4 * * *"` và `workflow_dispatch`.
  - `permissions: contents: write, pages: write, id-token: write`; `concurrency: { group: collect, cancel-in-progress: false }`.
  - Job `collect` (ubuntu-latest): checkout → `actions/setup-python@v5` 3.12 (cache pip) → `pip install -e ".[dev]"` → `pytest -q` → `python -m actions_tracker run` (bước có `id: run`, `continue-on-error: true`) → commit `data/ reports/ site/` nếu `git status --porcelain` khác rỗng, user `github-actions[bot]`, message `data: update <UTC time>` → `actions/upload-pages-artifact@v3` với `path: site` → bước cuối `if: steps.run.outcome == 'failure'` thì `exit 1` (để đỏ + email nhưng vẫn commit/deploy dữ liệu các giải thành công).
  - Job `deploy` (needs collect, `if: always() && needs.collect.result != 'cancelled'`), environment `github-pages`, `actions/deploy-pages@v4`.
- [ ] **Step 2: Bật Pages** `gh api -X POST repos/hnguyen76/actions-tracker/pages -f build_type=workflow` (nếu đã bật thì `-X PUT`).
- [ ] **Step 3: Push và chạy** `git rm .github/workflows/probe.yml && git add . && git commit -m "ci: scheduled collection and pages deploy" && git push && gh workflow run collect.yml`
- [ ] **Step 4: Xác minh** `gh run watch <id>` → success; `curl -s -o /dev/null -w "%{http_code}" https://hnguyen76.github.io/actions-tracker/` → `200`; mở URL bằng Playwright kiểm tra có dữ liệu và thời gian cập nhật; `git pull` thấy commit `data: update …` của bot.
- [ ] **Step 5: Commit README** với link dashboard và push.

---

## Self-Review Notes

- Spec §1–3 → Task 1, 3; §4 cấu trúc → File Structure; §5 → Task 4 (+ `league_status`); §6 → Task 5; §7A → Task 6; §7B → Task 7; §7C + trend → Task 8; §8 → Task 9, 10; §9 → Task 12; §10 → Task 5 (retry), 11 (exit codes), 12 (đỏ + email), Task 1 (rủi ro IP); §11 → test của từng task.
- `upsert_games` nhận row thiếu cột (Task 4) — Task 5 `_seed` dựa vào điều này.
