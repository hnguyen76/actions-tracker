# Actions Expert Tracker — Design Spec

- Ngày: 2026-11-09
- Chủ sở hữu: hnguyen76
- Trạng thái: chờ duyệt

## 1. Mục tiêu

Thu thập picks của các expert trên Action Network (actionnetwork.com), đối chiếu với kết quả trận sau khi kết thúc, để trả lời 3 câu hỏi (theo thứ tự ưu tiên):

- **A. Consensus** — khi đa số expert chọn cùng một side, side đó thắng bao nhiêu %? Đánh theo hay đánh ngược (fade) có lời?
- **B. Expert** — expert nào đáng tin theo giải / loại kèo, và thói quen chọn side của họ (favorite/underdog, home/away, over/under) có hiệu quả không?
- **C. Expert vs Public** — khi expert đi ngược số đông public bettors, ai thắng nhiều hơn?

Kết quả hiển thị qua: SQLite (nguồn chính), file Excel, và dashboard HTML trên GitHub Pages, cập nhật tự động trên cloud.

**Thành công nghĩa là:** hệ thống chạy tự động ≥ 2 tuần không cần can thiệp, không mất picks nào đã công khai, và dashboard trả lời được A/B/C với số mẫu + khoảng tin cậy.

## 2. Phạm vi

| Trong phạm vi | Ngoài phạm vi |
|---|---|
| Giải: NFL, NCAAF, NBA (ưu tiên); MLB, NHL, NCAAB bật sau bằng config | Đăng nhập / dữ liệu PRO |
| Loại kèo: spread, moneyline, total — toàn trận | Player props, kèo hiệp/quarter, futures, parlay |
| Lịch sử tích lũy kể từ ngày bắt đầu chạy (+ ~1 tháng picks gần nhất trang đang hiện) | Backfill lịch sử nhiều năm |
| Dashboard tĩnh, lọc phía trình duyệt | Đăng nhập dashboard, cảnh báo/thông báo kèo |

## 3. Nguồn dữ liệu (đã kiểm tra 2026-11-09)

Cho mỗi giải `league ∈ {nfl, ncaaf, nba, mlb, nhl, ncaab}`:

1. **Trang picks** — `GET https://www.actionnetwork.com/{league}/picks`
   - Đọc JSON trong `<script id="__NEXT_DATA__">` → `props.pageProps`.
   - `initialExpertsResponse.response.profiles[]`: `id, name, username, followers, record, picks[]`.
   - Mỗi pick: `id, user_id, game_id, league_name, type, period` (`game|firsthalf|...`), `player_id, value` (line), `odds, units, result` (`win|loss|push|pending`), `status, created_at, starts_at, settled_at, play` (text), `game{...}`.
   - `type` thấy trong mẫu: `spread_home, spread_away, ml_home, ml_away, over, under` (giữ) và `custom, away_under, ...` (loại — props, team total). Mapping: `spread_*`→market `spread`, side `home|away`; `ml_*`→`ml`; `over|under`→`total`.
   - Mẫu NFL ngày 2026-11-09: 54 expert, 103 picks hiển thị, trong đó ~35 picks spread/ml/total toàn trận (phần lớn còn lại là player props). Trang chỉ hiện picks gần đây → phải thu thập liên tục để tích lũy.
2. **Scoreboard API** — `GET https://api.actionnetwork.com/web/v2/scoreboard/{league}?bookIds=15`
   - `games[]`: `id, status, start_time, season, week, home_team_id, away_team_id, teams[], boxscore.total_home_points, boxscore.total_away_points`.
   - `markets["15"].event.{spread|moneyline|total}[]`: mỗi outcome có `side` (`home|away|over|under`), `team_id, value, odds, bet_info.tickets.percent, bet_info.money.percent`.
   - Book 15 = line consensus của Action Network kèm % public. Line/odds của book 15 tại lần lấy cuối trước giờ đá được dùng làm **line đóng cửa**.

Lịch sự với nguồn: User-Agent trình duyệt thường, nghỉ 2–4 giây giữa request, ≤ 12 request mỗi lần chạy (2 request × 6 giải).

## 4. Kiến trúc

```
GitHub Actions (cron 4h/lần + chạy tay)
  └─ python -m actions_tracker run
       fetch ─► parse ─► db upsert ─► grade ─► analysis ─► export_excel ─► build_site
                                                                 │              │
                                                     reports/*.xlsx      site/index.html
  └─ commit data/ reports/ site/ (nếu có thay đổi) ─► deploy GitHub Pages (site/)
```

### Cấu trúc repo

```
Actions/
├─ src/actions_tracker/
│  ├─ config.py          # danh sách giải bật/tắt, ngưỡng (min experts, min sample...)
│  ├─ fetch.py           # HTTP: retry 3 lần backoff, delay, UA
│  ├─ parse.py           # __NEXT_DATA__ → experts/picks/games; scoreboard → games/markets/public
│  ├─ db.py              # schema + upsert (idempotent)
│  ├─ grading.py         # gắn nhãn side, chấm theo line đóng cửa
│  ├─ analysis/
│  │  ├─ stats.py        # win%, ROI, Wilson CI
│  │  ├─ consensus.py    # A
│  │  ├─ experts.py      # B
│  │  ├─ public.py       # C
│  │  └─ trend.py        # theo tuần
│  ├─ export_excel.py
│  ├─ build_site.py      # nhúng JSON vào template HTML
│  ├─ templates/index.html
│  └─ cli.py             # run | fetch | analyze | build
├─ tests/ + tests/fixtures/  # JSON/HTML thật đã lưu cho từng giải
├─ data/actions.db
├─ reports/actions_report.xlsx
├─ site/index.html
├─ .github/workflows/collect.yml
└─ pyproject.toml        # Python ≥3.12; deps: requests, pandas, openpyxl; dev: pytest
```

Mỗi module có một việc, giao tiếp qua dataclass/dict thuần hoặc SQLite; analysis chỉ đọc DB, không gọi mạng.

## 5. Mô hình dữ liệu (SQLite)

```sql
experts(id INTEGER PK, name, username, followers, first_seen, last_seen)

games(id INTEGER PK, league, season, week, start_time, status,
      home_team_id, away_team_id, home_abbr, away_abbr,
      home_score, away_score, updated_at)

picks(id INTEGER PK, expert_id, game_id, league,
      market TEXT CHECK(market IN ('spread','ml','total')),
      pick_side TEXT CHECK(pick_side IN ('home','away','over','under')),
      line REAL, odds INTEGER, units REAL,
      an_result TEXT,             -- kết quả AN chấm: win/loss/push/NULL
      created_at, starts_at, settled_at, play_text, updated_at)

closing_lines(game_id, market, side, line REAL, odds INTEGER,
              tickets_pct REAL, money_pct REAL, captured_at,
              PRIMARY KEY(game_id, market, side))
```

Quy tắc:
- Upsert theo id của Action Network → chạy lại không trùng.
- `closing_lines` được ghi đè mỗi lần chạy **chỉ khi trận chưa bắt đầu** (`captured_at < start_time`); sau giờ đá giữ nguyên → giá trị cuối cùng là line đóng cửa + % public sát giờ đá.
- Pick bị loại khi: `period != 'game'`, `type` không thuộc 6 type giữ ở mục 3, hoặc có `player_id`.
- **Kỳ vọng số mẫu:** với ~35 picks hợp lệ/giải tại một thời điểm, consensus ≥ 3 expert sẽ thưa trong vài tuần đầu; các bảng sẽ gắn cờ `low_sample` cho tới khi đủ dữ liệu.
- Không bao giờ xóa dòng; không ghi gì nếu parse thất bại.

## 6. Gắn nhãn và chấm kết quả (`grading.py`)

**Nhãn cho mỗi pick** (tính lúc đọc, không lưu):
- `home_away`: spread/ml → `home|away`; total → NULL.
- `fav_dog`: spread → favorite nếu line của side đó < 0 tại line đóng cửa, underdog nếu > 0, `pickem` nếu 0; ml → favorite nếu odds đóng cửa của side đó < odds bên kia; total → NULL.
- `over_under`: total → `over|under`.

**Chấm side theo line đóng cửa** (dùng cho A và C, để các expert cùng side cùng một kết quả):
- spread: `margin = điểm side − điểm đối thủ + line_side`; >0 win, =0 push, <0 loss.
- ml: side thắng trận → win; hòa → push.
- total: `home+away` so với line total: over/under win, bằng → push.
- Trận chưa `complete` → chưa chấm.

**Thành tích expert (B)** dùng `an_result` (line thực tế expert lấy). Nếu `an_result` NULL mà trận đã kết thúc, chấm bằng line/odds của chính pick theo công thức trên.

**ROI**: đánh 1 unit mỗi pick theo odds Mỹ: odds âm → lãi `100/|odds|`, odds dương → lãi `odds/100`; thua −1; push 0. ROI = tổng lãi / số pick không push. Hòa vốn ở −110 = 52,38%.

**Khoảng tin cậy**: Wilson 95% cho win% (push loại khỏi mẫu). Nhóm có n < 20 gắn cờ `low_sample`.

## 7. Phân tích

### A. Consensus (`consensus.py`)
- Đơn vị: (game, market). Mỗi expert 1 phiếu = pick có `created_at` mới nhất của expert đó cho (game, market).
- Chỉ tính khi tổng phiếu ≥ 3 (config `MIN_EXPERTS=3`).
- `majority_pct = phiếu side đa số / tổng phiếu`; hòa phiếu → bỏ qua.
- Bucket: `[50,60)`, `[60,75)`, `[75,90)`, `[90,100]`.
- Output theo (league, market, bucket): n, W-L-P, win%, CI, ROI đánh theo, ROI đánh ngược (dùng odds đóng cửa của từng side).
- Dữ liệu "Kèo sắp tới": các (game, market) chưa đá với side đa số, % và số expert, % public tickets/money, win% lịch sử của bucket tương ứng.

### B. Expert (`experts.py`)
- Theo (expert, league, market) và tổng: W-L-P, win%, CI, units net, ROI — cho cửa sổ `all`, `last_30_days`, `last_30_picks`.
- Thói quen: tỉ lệ favorite/underdog, home/away, over/under + win% và ROI theo từng nhãn.
- Leaderboard: expert có ≥ 20 picks đã chấm, sắp theo ROI.

### C. Expert vs Public (`public.py`)
- Đơn vị: (game, market) có consensus (theo A) và có `tickets_pct`.
- `public_side` = side có tickets_pct > 50; `heavy` khi ≥ 65; = 50 → bỏ qua.
- Phân loại: `agree` (expert đa số = public_side) / `contrarian`. Output: win% của side expert đa số theo (league, market, agree|contrarian, heavy?).
- Chỉ số phụ "money vs tickets": side có `money_pct − tickets_pct ≥ 15` điểm → win% của side đó.

### Trend (`trend.py`)
- Theo tuần (thứ Hai–Chủ nhật, giờ US/Eastern): win% consensus (bucket ≥ 60), win% top-10 expert leaderboard, win% side contrarian.

## 8. Đầu ra

**Excel** `reports/actions_report.xlsx` — tạo lại mỗi lần chạy: sheet `Picks`, `Consensus`, `Experts`, `Expert_Habits`, `Expert_vs_Public`, `Trend_Weekly`, `Upcoming`. Header đóng băng + autofilter.

**Dashboard** `site/index.html` — 1 file, dữ liệu nhúng JSON, Chart.js 4.4.1 từ cdnjs. Tab: Kèo sắp tới · Consensus · Experts (bấm xem chi tiết) · Expert vs Public · Xu hướng. Bộ lọc chung: giải, loại kèo, khoảng thời gian. UI tiếng Việt, thuật ngữ kèo tiếng Anh. Responsive mobile. Hiển thị "cập nhật lần cuối" từng giải. Nút tải Excel (`site/actions_report.xlsx` được copy cùng). `<meta name="robots" content="noindex">`.

## 9. Vận hành

- Repo GitHub: `hnguyen76/actions-tracker`, **public** (để dùng GitHub Pages miễn phí; dữ liệu đều là dữ liệu công khai của Action Network). Đổi sang private nếu có gói GitHub Pro.
- **Thay đổi 2026-11-09 sau probe:** GitHub Actions bị Action Network chặn ở trang picks (202, nội dung rỗng); scoreboard vẫn 200. Vì vậy **thu thập chạy trên máy Windows của người dùng**, kích hoạt bằng **nút bấm tay trên Desktop**; cloud chỉ đăng dashboard.
- **Nút Desktop "Actions - Cap nhat"** (shortcut → `scripts/update.ps1`): `git pull` → `python -m actions_tracker run` → `git add data reports site` + commit `data: update <thời gian>` + `git push` → in tóm tắt (số picks mới mỗi giải, lỗi nếu có) → mở URL dashboard → chờ phím Enter để đóng cửa sổ. Nếu pipeline lỗi cấu trúc (exit 2) vẫn push dữ liệu các giải thành công và in cảnh báo đỏ.
- Trang picks chỉ hiện picks vài ngày gần nhất → cần bấm **ít nhất mỗi ngày** để không mất picks. Dashboard hiện cảnh báo khi lần cập nhật cuối > 24 giờ.
- Workflow `pages.yml`: `on: push` (main, paths `site/**`) + `workflow_dispatch` → deploy `site/` lên GitHub Pages. Không gọi Action Network từ cloud.
- Local: venv `.venv` với Python 3.14 hiện có; CI không cần Python.

## 10. Xử lý lỗi

- HTTP: retry 3 lần (2s, 4s, 8s) cho lỗi mạng/5xx/429.
- Lỗi một giải → log, tiếp tục giải khác; cuối lần chạy nếu **mọi** giải đang bật đều lỗi, hoặc parse thất bại do cấu trúc thay đổi (thiếu `__NEXT_DATA__`/khóa bắt buộc) → exit code ≠ 0 → cửa sổ nút bấm in cảnh báo đỏ.
- Giải lỗi vẫn giữ dữ liệu cũ; dashboard hiện thời điểm cập nhật thành công cuối của giải đó.
- `git push` thất bại (mất mạng, xung đột) → in lỗi, dữ liệu vẫn nằm trong commit local, lần bấm sau push tiếp.

## 11. Kiểm thử

- **Parser**: fixtures thật (picks HTML + scoreboard JSON) cho nfl, ncaaf, nba → số experts/picks/games đúng, lọc bỏ props/period khác.
- **Grading**: case viết tay — spread cover/không cover/push đúng line, ml thắng/thua/hòa, total over/under/push, fav/dog ở ml và spread, pickem.
- **Stats**: ROI với odds âm/dương/push, Wilson CI so với giá trị tính tay.
- **Analysis**: DB nhỏ dựng sẵn với đáp án biết trước cho A, B, C, trend; kiểm tra quy tắc 1 phiếu/expert, MIN_EXPERTS, hòa phiếu, public = 50.
- **DB**: upsert 2 lần không trùng; closing_lines không bị ghi sau giờ đá.
- **End-to-end**: từ fixtures → tạo được Excel (đủ sheet) và HTML (JSON parse được).

---

## 12. Sửa đổi 2026-11-09 — phương án C: Action Network chỉ dùng cho picks

Người dùng chọn: **chỉ picks của expert lấy từ Action Network (AN)**; tỉ số và line/odds lấy từ **The Odds API** (API chính thức, có key); **bỏ phân tích Expert vs Public (§7C)** vì không có nguồn % public chính thức. Mục này thay thế các phần tương ứng ở §3, §5, §6, §7, §8.

### 12.1 Nguồn dữ liệu
| Dữ liệu | Nguồn |
|---|---|
| Experts, picks, đội và giờ đá của trận được pick | AN trang picks (`__NEXT_DATA__`) — như §3.1 |
| Tỉ số cuối, trạng thái xong | The Odds API `GET /v4/sports/{sport}/scores/?daysFrom=3` (2 credit/lần) |
| Line/odds trước giờ đá (spread, total, moneyline) | The Odds API `GET /v4/sports/{sport}/odds/?regions=us&markets=h2h,spreads,totals&oddsFormat=american` (3 credit/lần) |

- Sport key: `americanfootball_nfl`, `americanfootball_ncaaf`, `basketball_nba` (MLB/NHL/NCAAB thêm sau).
- AN scoreboard API **không còn dùng**. Kết quả AN chấm cho pick (`result`) vẫn được lưu nhưng **không dùng** để chấm; mọi pick tự chấm bằng tỉ số The Odds API.
- API key: biến môi trường `ODDS_API_KEY`, nếu không có thì đọc file `.odds_api_key` ở thư mục repo (gitignored). Không bao giờ commit key (repo public).

### 12.2 Ghép trận AN ↔ The Odds API
- Lưu thêm `home_name`, `away_name` (AN `full_name`) và `odds_event_id` cho mỗi game.
- So khớp tên đã chuẩn hóa (chữ thường, bỏ dấu câu, `&`→`and`, `st`→`state` ở cuối từ).
- Khớp khi: cả hai đội trùng tên chuẩn hóa và `commence_time` lệch ≤ 12 giờ; hoặc một đội trùng, đội kia giống ≥ 0,6 (difflib) và giờ lệch ≤ 3 giờ. Nhiều ứng viên → chọn giờ gần nhất.
- Không khớp → game không có tỉ số/line; dashboard hiện số "trận chưa ghép được nguồn tỉ số" theo giải (thay cho `ungraded_past_games`).

### 12.3 Line đóng cửa
- Mỗi lần bấm nút, với các trận chưa bắt đầu: line = **median** `point` các nhà cái vùng US cho spread/total; odds = median `price` mỗi side. Ghi vào `closing_lines` chỉ khi trận chưa bắt đầu (§5 giữ nguyên quy tắc đóng băng). `tickets_pct`/`money_pct` để trống.
- Trận đã bắt đầu trước lần bấm đầu tiên → không có line đóng cửa; fallback median line của expert (§6 giữ nguyên).

### 12.4 Ngân sách credit (gói miễn phí 500/tháng)
- Odds chỉ gọi cho giải có trận **sắp đá có pick**; scores chỉ gọi cho giải có trận **đã qua chưa có tỉ số có pick** trong 3 ngày.
- Tối đa ~15 credit/lần bấm (3 giải × (3 + 2)). Bấm 1 lần/ngày ≈ 450/tháng.
- Đọc header `x-requests-remaining`; lưu và in ra sau mỗi lần bấm, hiện trên dashboard. Khi còn < 30 credit: bỏ gọi odds, chỉ gọi scores.
- Tỉ số chỉ lấy lại được 3 ngày → phải bấm ít nhất mỗi 3 ngày (vẫn khuyên mỗi ngày vì picks AN chỉ hiện vài ngày).

### 12.5 Những gì bị bỏ
- §7C Expert vs Public, chỉ số money vs tickets, tab "Expert vs Public", sheet `Expert_vs_Public`, series trend `contrarian`, cột % public ở "Kèo sắp tới".
- Backfill AN theo ngày/tuần (thay bằng `daysFrom=3`).

### 12.6 Lỗi
- Không có key → giải vẫn lưu picks, bỏ phần tỉ số/odds, in đỏ "Chưa cấu hình ODDS_API_KEY"; exit 5.
- HTTP 401/429 hết credit từ The Odds API → ghi lỗi vào `league_status`, picks vẫn lưu.
