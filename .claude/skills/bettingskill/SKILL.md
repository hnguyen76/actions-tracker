---
name: bettingskill
description: Phân tích picks của expert Action Network (NFL, NCAAF, NBA) so với kết quả trận và cập nhật NFL/sports betting playbook của người dùng — consensus của expert, đánh theo hay đánh ngược (fade), thói quen chọn favorite/underdog, nhà/khách, over/under, xếp hạng expert, báo cáo một ngày hoặc một cuối tuần. Dùng skill này mỗi khi người dùng nhắc tới expert picks, Action Network, consensus, fade, kèo/side expert chọn, playbook, "phân tích hôm qua/cuối tuần", dashboard Actions, nút "Actions - Cap nhat", hoặc hỏi một quy tắc cá cược có còn đúng không — kể cả khi không nói rõ tên skill.
---

# bettingskill — phân tích expert picks và playbook

Người dùng nói tiếng Việt (thường không dấu); trả lời tiếng Việt có dấu, giữ thuật ngữ kèo tiếng Anh (spread, moneyline, total, favorite, underdog, fade).

## Hệ thống đang có

Repo (trên laptop: thư mục Desktop\Actions; GitHub `hnguyen76/actions-tracker`, dashboard https://hnguyen76.github.io/actions-tracker/):

| Dữ liệu | Nguồn | Giới hạn |
|---|---|---|
| Expert + picks | Action Network: trang `/{league}/picks` và trang "By Game" `/{league}/picks/game?id=<game>` (mọi expert, mọi trận trên bảng hiện tại) | Chỉ còn picks vài ngày gần nhất → mất nếu không bấm nút |
| Tỉ số cuối + điểm live | **ESPN scoreboard công khai** (`src/actions_tracker/live.py`, từ 14/11/2026) | Miễn phí; trận xong là chấm ngay; chỉ trận có picks bắt đầu trong 72h |
| Line/odds trước giờ đá | **ESPN scoreboard (line DraftKings)**, lần quét cuối trước giờ đá = line đóng cửa | Miễn phí; một nhà cái (không phải median). The Odds API chỉ dùng khi chạy `run --odds-api` (tốn credit) — người dùng muốn nguồn free |

Thu thập chỉ chạy trong mạng nhà người dùng: shortcut "Actions - Cap nhat" trên Desktop laptop (→ `scripts/update.ps1` → `python -m actions_tracker run`, bấm tay) và điện thoại Samsung S21 — **nguồn chính từ 15/11/2026** (Termux, `scripts/auto_update.sh update|alert|live`: picks mỗi 15 phút, Telegram và điểm live mỗi 5 phút, 11:00–23:00; laptop chỉ dự phòng). Website ở nhánh `gh-pages` (`scripts/publish_site.py`); nhật ký trên điện thoại: `~/actions-auto.log`. Key ở `.odds_api_key` (gitignored, không bao giờ in ra hay commit).

**Ranh giới đã thống nhất:** không lấy picks Action Network từ cloud (GitHub Actions bị chặn), không dùng API nội bộ/ứng dụng di động của Action Network hay Apify để vượt cơ chế chặn đó. Lịch sử picks cũ hơn vài ngày không lấy lại được — nói thẳng như vậy khi được hỏi.

## Quy trình phân tích một ngày / một cuối tuần

1. Đảm bảo dữ liệu mới: nếu lần chạy cuối > vài giờ, điện thoại sẽ tự quét trong ≤ 15 phút. **Phiên cloud (app Claude trên iPhone) không được chạy `run`** — Action Network chặn cloud và không được lách; chỉ đọc `data/actions.db` đã có trên GitHub (`git pull` trước để lấy bản mới nhất).
2. Chạy báo cáo có sẵn thay vì tự viết lại truy vấn:
   ```bash
   python -I .claude/skills/bettingskill/scripts/day_report.py --league nfl --date 2026-11-08
   ```
   `--date` lặp lại được cho cả cuối tuần; `--csv <thư mục>` xuất file. Ngày là ngày **giờ miền Đông Mỹ (ET)** — trận 20:20 ET Chủ nhật có `start_time` UTC sang thứ Hai.
3. Đọc kết quả rồi **kiểm chứng mọi câu nhận xét trước khi viết**: ví dụ muốn nói "đa số chọn underdog", phải xem dấu line của các pick đó (bài học 08/11: NO −3 là favorite, suýt bị ghi nhầm là underdog). Chấm consensus dùng line đóng cửa; thiếu thì dùng median line của expert — ghi rõ điều này trong báo cáo.
4. Luôn kèm cỡ mẫu: n, W-L-P, win%, ROI ở 1 unit; hòa vốn ở −110 là **52,38%**; n < 20 = "chưa đủ mẫu". Một ngày (~13 trận NFL) chỉ đủ để đặt giả thuyết, không đủ để kết luận.
5. Báo cáo dài/để giữ → làm doc (Claude Docs) như playbook; câu hỏi nhanh → trả lời trong chat.

## Playbook hiện tại (giả thuyết, từ NFL 08/11/2026)

Doc gốc: https://claude.ai/artifact/Vk3KQ13QHkWBCg1pZ5c3PE ("Playbook — NFL 08/11 & NCAAF 07/11/2026"; nay có thêm mục "Cả mùa" với bảng NFL vs NCAAF và biểu đồ consensus theo tuần, và bảng quy tắc 1–9 có cột Trạng thái). NFL 08/11: 177 picks/36 expert đi 69–108 (39,0%, ROI −25,8%); underdog 19–69, đội nhà 17–58, favorite 25–17, under 16–12; consensus ≥75% đi 3–11, dưới 75% đi 7–3; đội khách thắng 8/13.

Trạng thái sau khi kiểm chứng cả mùa (cập nhật 10/11/2026; NFL tuần 1–9, NCAAF tuần 1–10):

| # | Quy tắc | Bằng chứng cả mùa | Ngưỡng | Trạng thái |
|---|---|---|---|---|
| 1 | Đánh ngược spread khi ≥ 75% picks cùng một side | đánh ngược NFL 28–25 (52,8%), NCAAF 121–118 (50,6%) | ≥ 30 kèo, ≥ 55% | Đang theo dõi (chỉ nhỉnh ở NFL) |
| 2 | Không theo pick underdog | underdog NFL 48,8% (n=900), NCAAF 48,0% (n=1915) | underdog < 47% | Bác bỏ |
| 3 | Chỉ cân nhắc pick favorite | NFL 48,4%, NCAAF 50,6% | ≥ 54% | Bác bỏ |
| 4 | Theo under khi ≥ 3 picks cùng chọn | NFL 25–38, NCAAF 49–61 | ≥ 55% | Bác bỏ |
| 5 | Theo expert đang có phong độ | lịch sử By Game không có tên expert | ≥ 20 picks/người, ROI > 0 | Đang theo dõi (chỉ từ dữ liệu DB) |
| 6 | NFL: theo pick đội khách | 418–345 (54,8%, n=763); consensus spread khách 31–23 | giữ ≥ 54% thêm 4 tuần | Đang theo dõi |
| 7 | NFL: đánh ngược khi 90–100% picks cùng side | consensus 17–27 → ngược 61,4% (n=44) | ≥ 60 kèo, ≥ 55% | Đang theo dõi |
| 8 | NFL: đánh side public ít (≤ 35% bet) ở spread | 30–23 (56,6%, n=53); tuần 1–5 67,7% → tuần 6+ 40,9% | ≥ 80 kèo, ≥ 55% | Bác bỏ (12/11, đảo chiều) |
| 9 | NCAAF: đánh ngược public ở total | ngược 53,3% (n=659); Thứ 2–6 62,7% (n=83) | giữ ≥ 54% thêm 4 tuần | Đang theo dõi |

Cả mùa: expert picks NFL 48,2% (1107–1192), NCAAF 49,9% (2370–2377) — dưới hòa vốn. NFL: pick đội nhà 43,4%, đội khách 54,8%, thị trường đội nhà cover 42,7%; NCAAF ngược lại (đội nhà cover 53,5%). Consensus vượt 52,4% chỉ ở 3/9 tuần NFL và 3/10 tuần NCAAF. Monday Night 09/11 BUF 23–6 MIN: đa số MIN +3,5 (9/14) thua, Under 46 (4/6) thắng.

MACtion thứ Ba 10/11 (NCAAF tuần 11, 3 trận): expert 17–11 (spread 13–4, under 0–5, over 4–0); cả 3 trận đều Over. Public over 82–84% → quy tắc 9 (đánh ngược public total) **0–3**; quy tắc 10 ứng viên (total theo tiền lớn, KENT@BGSU under T16/M50) **0–1**. Cộng dồn T2-6: quy tắc 9 52–34 (60,5%), quy tắc 10 91–61. Lưu ý: line Action Network (KENT +3,5) khác median The Odds API (+5) → cùng trận có thể là thắng hoặc push tùy nguồn line. NBA 10/11: expert 8–9, favorite 6–0, underdog 1–7; LAC +3,5/+4,5 (4/5 picks) thua 23 điểm.

Kiểm tra quy tắc 9/10 trước giờ đá cho NCAAF giữa tuần: scoreboard `https://api.actionnetwork.com/web/v2/scoreboard/ncaaf?bookIds=15&week=N` (dùng `Fetcher().get_json`, cùng nguồn với lịch sử) → `bet_info.tickets/money.percent` theo side của total.

### Dữ liệu cả mùa (lịch sử)

`data/history/{nfl,ncaaf}_sides.csv` trong repo: mỗi dòng = trận × kèo × side với `picks` (số picks trên side), line/odds đóng cửa, % public, fav/dog, `day_group`, `result` theo line đóng cửa. Dựng lại (sau mỗi tuần mới):
1. Playwright: mở `/{league}/picks/game`, lặp chọn "Week N" (chờ tới khi thẻ đổi và **có tỉ số** — nếu không sẽ đọc nhầm bảng tuần hiện tại, đã xảy ra với NCAAF tuần 1–3), đọc text thẻ, lưu JSON `{"Week N": [card text...]}`.
2. `python scripts/build_history.py <league> <cards.json> <cache_dir>` (tải scoreboard Action Network theo tuần, có cache).
3. `python -I .claude/skills/bettingskill/scripts/history_report.py nfl ncaaf [--json out.json]` → báo cáo ALL / T2-6 / T7-CN + theo tuần, kèm đánh ngược consensus ≥75%.
4. Bấm nút / `python -m actions_tracker run` → dashboard tab **"Lịch sử mùa"** (bảng `History_Summary`, `History_Weekly`, `History_Plays`) tự đọc các CSV này.

**Ứng viên mới từ lịch sử (11/11/2026, chưa phải quy tắc; tổng ~80 phép thử → kỳ vọng ~4 dương tính giả ở p<0,05):**
- NCAAF consensus trận **ban ngày (< 19:00 ET)** 143–184 (43,7%), ổn định 44,3%/43,1%; đánh ngược spread+total 171–130 (56,8%, p=0,069, hai nửa đều 56,8%). Thứ Bảy ngày 138–184 vs Thứ Bảy tối 108–84 (56,2%). NFL cùng chiều nhưng yếu (đánh ngược 54,9%, nửa sau 50,7%).
- NCAAF đánh ngược consensus **ML underdog** (= ML favorite) 26–13, ROI +8,9%, p=0,051, hai nửa 66,7%/66,7% — n nhỏ.
- NCAAF đánh ngược consensus **spread đội khách underdog** 74–54 (57,8%, ROI +10,1%, p=0,13; 56,0%/60,4%).
- Không có "đà" theo tuần: consensus sau tuần xấu (<45%) ≈ sau tuần tốt (>55%) ≈ 48% ở cả hai giải.
- NFL home underdog (consensus 37,8%, thị trường 40,4%) là hiệu ứng thị trường mùa này và đảo chiều giữa hai nửa — không dùng.
Giờ đá lấy từ scoreboard cache (`start_time`); CSV lịch sử chưa có cột giờ.

**Hai loại consensus — không bao giờ gộp hay so như một:**
| | Live (tab "Kèo đã qua", `Past_Plays`) | Lịch sử (tab "Lịch sử mùa", `History_*`) |
|---|---|---|
| `count_basis` | `distinct_expert` — mỗi expert 1 phiếu/kèo (pick mới nhất) | `pick_count` — số picks trên thẻ, 1 expert có thể tính nhiều lần |
| `line_source` | `odds_api_close` (thiếu → `median_expert_line`) | `action_network_scoreboard` (ngoại lệ lịch sử) |
Khi viết playbook, ghi rõ con số lấy từ loại nào. Quy tắc học từ lịch sử phải kiểm chứng lại trên dữ liệu live trước khi tin. "Top 10 expert" ở tab Xu hướng được xếp hạng lại mỗi tuần chỉ bằng picks trước tuần đó (không look-ahead).

Doc còn có mục "NCAAF thứ Bảy 07/11" (49 trận, 44 kèo consensus): consensus 16–28, spread ≥75% 5–13, consensus spread vào đội nhà 3–15 / đội khách 7–4, under 0–4 — cùng kiểu với NFL 08/11. Thị trường: đội khách cover 34–15, theo public spread 28–18, total theo public 21–27 (scoreboard Action Network, ngoại lệ một lần).

Doc cũng tách **Thứ 2–6 / Thứ 7–CN** cho cả hai giải (người dùng muốn phân tích riêng hai nhóm ngày này): cuối tuần expert thua nặng (NFL 69–108, NCAAF 128–206), chủ yếu pick đội nhà (NFL 17–58, NCAAF 34–137); trong tuần mẫu nhỏ và khác chiều (NCAAF đội nhà 22–9). Khi báo cáo, luôn chia theo hai nhóm ngày này (giờ ET; `day_of_week` 0–4 = Thứ 2–6).

### Lấy picks của tuần đã qua (NFL/NCAAF)

HTML server của trang By Game chỉ chứa tuần hiện tại (kể cả `?id=<trận tuần cũ>` hay `?week=`), nên `python -m actions_tracker run` không lấy được tuần cũ. Nhưng trên trình duyệt, menu **Week** hiển thị tuần đã qua — **từ Week 1** cho cả NFL và NCAAF (xem "Dữ liệu cả mùa" ở trên). Cách đã dùng cho NCAAF tuần 10: Playwright mở `https://www.actionnetwork.com/{league}/picks/game`, chọn option "Week N" trong combobox, chờ vài giây, rồi đọc text của từng thẻ trận (thẻ chứa "See all picks"): tỉ số cuối "AWY a - h HOM" và số picks mỗi side ("AWY Spread", "HOM Spread", "Over", "Under", "AWY ML", "HOM ML"). Chỉ có **số đếm picks** (một expert có thể đếm hơn một lần), không có tên expert hay line của từng pick → dùng được cho consensus, không làm được bảng xếp hạng expert; chấm theo line đóng cửa (cần nguồn line của tuần đó). Đây là xem trang như người dùng, chạy trên máy người dùng — không gọi API nội bộ.

Khi người dùng hỏi một quy tắc còn đúng không: chạy `day_report.py` cho toàn bộ các ngày đã có, cộng dồn, so với ngưỡng; quy tắc chỉ "Xác nhận" khi đủ mẫu và vượt ngưỡng, rơi dưới 50% sau khi đủ mẫu thì "Bác bỏ". Ghi quy tắc mới khi một xu hướng lặp lại ≥ 2 tuần. Cập nhật bảng trên (và cột Trạng thái trong doc) sau mỗi lần kiểm chứng; không bao giờ khuyên đặt tiền theo quy tắc đang "theo dõi".

## Kiểm chứng quy tắc bằng kèo ghi trước giờ đá (từ 12/11/2026)

Mô phỏng theo thời gian trên 889 kèo lịch sử (12/11): "đánh ngược nhóm đang thua, theo nhóm đang thắng" **không** vượt hòa vốn ngoài mẫu (theo hết 48,6%, ngược hết 51,4%, các cách chia nhóm 46–53%; chỉ nhìn tuần trước 48,8%) — kết quả quá khứ của một nhóm chủ yếu là nhiễu. Vì vậy không chọn quy tắc theo thắng thua gần đây; chỉ kiểm chứng số ít quy tắc đã chốt:

| rule_id | Cách đặt | Nhìn lại cả mùa |
|---|---|---|
| `ncaaf_total_day_fade` | NCAAF total, đá trước 19:00 ET, có consensus (≥ 3 expert) → đặt bên còn lại | 56–35 |
| `ncaaf_total_money` | NCAAF total, % tiền − % số bet ≥ 15 ở một bên → đặt bên đó | 91–60 |
| `ncaaf_spread_away_dog_fade` | NCAAF spread, consensus chọn đội khách underdog → đặt đội nhà | 74–54 |
| `ncaaf_spread_daygroup` (thêm 14/11, ý của người dùng) | NCAAF spread, ≥ 5 expert (`DAYGROUP_MIN_VOTES`), có đa số: Thứ 2–6 ET → theo đa số; Thứ 7–CN → đánh ngược | 143–122 (T2-6 26–20, T7-CN 117–102; NFL cùng cách 62–58 nên không áp dụng). Trùng hướng với quy tắc đội khách underdog ở cuối tuần; ngày thường hai quy tắc có thể ngược nhau → "conflict", bỏ qua |
| `nfl_spread_heavy_follow` (thêm 14/11, ý của người dùng) | NFL spread, ≥ 10 expert (`NFL_HEAVY_VOTES`) cùng một bên → theo đa số. Không đọc trang public NFL (`PUBLIC_LEAGUES` = ncaaf) | 19–13 (59,4%, n=32; lịch sử đếm picks trên thẻ). Live đếm mỗi expert một phiếu, NFL thường chỉ 4–5 expert/kèo → có thể rất ít kèo. NCAAF ≥ 10 picks thì ngược: đa số 17–24 |

- Định nghĩa trong `src/actions_tracker/rules.py` (`RULES`) — **không sửa trong lúc kiểm chứng**; thêm quy tắc mới thì thêm id mới.
- Mỗi lần chạy: đọc trang công khai `/{league}/public-betting` (line, % số bet, % tiền; bảng `public_splits`, đóng băng lúc bắt đầu trận) → `sync_rule_plays` ghi kèo khớp vào `rule_plays`; lần đánh giá cuối trước giờ đá là kèo chính thức.
- Chấm: line đóng cửa The Odds API, thiếu thì line Action Network lúc ghi. Bảng `Rule_Summary`/`Rule_Plays`, tab **"Quy tắc"** trên dashboard.
- Ngưỡng: đủ 100 kèo đã chấm mới đánh giá — ≥ 55% "Đạt", < 50% "Bỏ" (`RULE_TARGET_N`, `RULE_PASS`, `RULE_FAIL`). Trước đó không khuyên đặt tiền theo quy tắc.
- Khi người dùng hỏi "quy tắc X thế nào rồi": đọc bảng `Rule_Summary` (cột forward), không trích số "nhìn lại" như bằng chứng.
- **Thẻ "Quyết định"** (đầu tab Kèo sắp tới, bảng `Decisions` trong `analysis/decisions.py`): mỗi ngày ET một câu kết luận. Đặt 1u chỉ khi quy tắc đã "Đạt"; quy tắc đang kiểm chứng = "Theo dõi — chưa đặt tiền"; hai quy tắc ngược nhau hoặc chỉ có consensus = "Bỏ qua". Khi người dùng hỏi "hôm nay đánh gì", trả lời theo bảng này, không tự đề xuất kèo ngoài nó.

### Nhật ký kiểm chứng (doc Playbook, mục "Nhật ký kiểm chứng (dữ liệu live)")

Sau mỗi ngày có trận: chạy cập nhật, đọc `Rule_Summary`, `Past_Plays` (tách T2-6/T7-CN), `Expert_Form`, `Expert_CLV`, rồi **thêm một dòng mới lên đầu** bảng nhật ký (Ngày · Kết quả mới · Cộng dồn · Điều rút ra). Doc và skill không tự học — chỉ dashboard tự cập nhật số; nhật ký là chỗ ghi bài học, và không đổi quyết định trước khi đủ mẫu.

12/11: quy tắc tiền lớn 1–0 (MEM @ USF Over 50,5). Consensus live cộng dồn 21–22–1. Expert "đang đỏ" 9–4 vs "đang xanh" 13–15 (41 picks, chưa đủ). CLV trung bình +0,39 điểm (74 tốt hơn / 23 tệ hơn, 136 picks) nhưng consensus vẫn ~49% → line chạy theo expert sau khi đăng; lưu ý CLV ở đây so line pick (Action Network) với median đóng cửa The Odds API, có thể lệch hệ thống giữa hai nguồn.

13/11: quy tắc đội khách underdog 0–1 (UCLA −10,5 thua). Consensus live cộng dồn 24–24–1 (T2-6 15–10–1). "Đang đỏ" 19–8–1 vs "đang xanh" 28–31 (đến trưa 14/11). CLV +0,49 (184 picks). Trưa 14/11 WF @ SMU Over 60,5 thua → cả 2 quy tắc total 0–1 cho kèo đó (ghi ở dòng 14/11).

14/11 (đủ ngày): tiền lớn 10–5 trong ngày (cộng dồn 11–5, +5,0u), quy tắc 4 2–4, cách của người dùng 5–4 (đánh ngược đồng thuận 1–2, không đồng thuận 4–2). Consensus live 40–43–1 (T7-CN 25–33). Từ 14/11 line/tỉ số = ESPN (DraftKings), CLV +0,65 không so trực tiếp với số cũ.

Kiểm tra theo yêu cầu 13/11 — NCAAF Thứ 2–6, ≥ 75% picks một bên (lịch sử By Game, ≥ 3 picks, line đóng cửa): cả mùa 36–34–2 (51,4%, n=70), bỏ tuần 1 còn 25–29–2, từ tuần 6 16–21–1; under 6–9, over 7–5; Thứ 7–CN 169–175–2. Kết luận: không theo, không đánh ngược.

## Phong độ expert lúc pick (từ 11/11/2026)

Câu hỏi của người dùng: "expert đang xanh (+units) thì pick tiếp theo có hay thua không?". Trang hồ sơ expert (bản free) chỉ có số tổng, không có danh sách pick cũ → không dựng lại được quá khứ. Vì vậy mỗi lần bấm nút, bảng `pick_form` lưu phong độ Action Network của expert **lần đầu thấy pick, trước giờ đá**: `units_30`/`wins_30`/`losses_30` (record 30 ngày **của giải đó**) và `streak_type` (hot/cold) + `streak_value`.
- Bảng phân tích `Expert_Form` (sheet Excel cùng tên, thẻ đầu tab Experts): win% theo nhóm — units 30 ngày: `hot` ≥ +3u, `neutral`, `cold` ≤ −3u (`FORM_UNITS` trong config); chuỗi: `hot_long`/`cold_long` ≥ 3 (`FORM_STREAK_LONG`), `hot`, `cold` — chia league × market × day_group (T2-6/T7-CN, có ALL).
- Kiểm tra sơ bộ 11/11 (trước khi có bảng này, mẫu rất nhỏ) ra hai chiều ngược nhau → chưa kết luận. Cần khoảng 3–4 tuần (≥ 1.000 picks) rồi mới đánh giá; giả thuyết đạt mới thành quy tắc 11.

## Lỗi hay gặp

- Consensus/Kèo sắp tới trống: chưa đủ 3 expert một kèo, hoặc trang By Game lỗi (xem dòng `[league] by game` khi chạy).
- "trận đã qua chưa có tỉ số": quá 3 ngày không bấm, hoặc tên đội không ghép được giữa Action Network và The Odds API (thêm vào `ALIASES` trong `src/actions_tracker/matching.py`, kèm test).
- Credit The Odds API hiện trên header dashboard; < 30 thì hệ thống tự bỏ phần lấy line.

## Lệnh Python

Chạy từ thư mục gốc repo. Trên laptop dùng `.venv/Scripts/python` thay cho `python`; trên cloud cài trước bằng
`pip install -e .[dev]`.

## Sửa "Cách của bạn" (cách bet của người dùng)

Người dùng **được phép** đổi cách bet của chính họ bất cứ lúc nào (khác với quy tắc 1–5 đã đóng băng):

| Muốn đổi | Sửa ở |
|---|---|
| Số picks tối thiểu (hiện 5), giải áp dụng (NFL, NCAAF) | `MIN_PICKS`, `LEAGUES` trong `src/actions_tracker/analysis/my_method.py` |
| Ngày theo / ngày đánh ngược (T2–6 theo, T7–CN ngược, giờ ET) | `my_method_plays` (`weekday = local.day_of_week <= 4`) và `season_plays` cùng file |
| Kèo nào vào bảng "Quyết định" | `src/actions_tracker/analysis/decisions.py` (action `mine`) |
| Tin Telegram 15 phút trước trận | `src/actions_tracker/alerts.py` (`due_games`, `build_messages`) |
| Tô vàng (≥ 8 picks và đồng thuận) | `HOT` trong `src/actions_tracker/templates/index.html` |

Cách làm:
1. Hỏi lại cho rõ quy tắc mới nếu mơ hồ (ví dụ "đồng thuận" = n/n).
2. Chạy số liệu cả mùa với quy tắc mới **trước khi sửa** (`data/history/*_sides.csv`, `history_report.py`):
   báo W–L, win%, n, ROI, hòa vốn 52,38%, chia T2–6 / T7–CN.
3. Sửa code + test (`tests/test_my_method.py`, `tests/test_decisions.py`, `tests/test_alerts.py`), chạy `python -m pytest -q`.
4. Ghi một dòng vào "Nhật ký cách bet" dưới đây (ngày, đổi gì, số liệu cả mùa).
5. Commit; người dùng merge vào `main` → điện thoại tự đăng web trong ~15 phút.

Không đổi ngưỡng các quy tắc đóng băng trong `src/actions_tracker/rules.py` trừ khi người dùng nói rõ muốn bỏ hoặc thay
quy tắc đó; khi đó nói rõ kết quả forward test cũ không còn so sánh được.

### Nhật ký cách bet

- 14/11/2026: spread, ≥ 5 picks, có bên đa số; T2–6 theo đám đông, T7–CN đánh ngược (cả khi đồng thuận 100%).
