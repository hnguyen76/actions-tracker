# Actions Expert Tracker

Theo dõi picks của expert trên Action Network (NFL, NCAAF, NBA), chấm theo tỉ số và line từ
ESPN miễn phí (dữ liệu cũ có The Odds API) và phân tích:

- **Consensus** — khi đa số expert chọn cùng một side, side đó thắng bao nhiêu %, đánh theo hay đánh ngược có lời.
- **Expert** — thành tích và thói quen chọn side (favorite/underdog, nhà/khách, over/under) của từng expert.

Dashboard: https://hnguyen76.github.io/actions-tracker/

Mục **Đang đá & chờ kết quả** lấy điểm trực tiếp từ scoreboard công khai của ESPN mỗi **5 giây**
khi trang đang mở, độc lập với lịch quét/đăng website 5 phút. Hiển thị đội cầm bóng, down & distance,
vị trí bóng, đồng hồ/hiệp và điểm từng hiệp khi ESPN có dữ liệu. Trang giữ điểm lần trước nếu lỗi,
thử lại chậm dần và ngừng lấy khi bị ẩn. Nhịp lấy 5 giây không bảo đảm độ trễ 5 giây của nguồn.
Tỉ số cuối trên trình duyệt chờ lượt chấm của hệ thống trước khi vào thống kê.
Halftime có đồng hồ **ước tính** từ mốc `End of Half` hiệp 2 của ESPN: mùa thường NFL 13 phút,
NCAAF 20 phút. Đồng hồ chạy theo thời gian thực, dừng khi ESPN báo hiệp 3; quá mốc dự kiến thì
hiện “chờ hiệp 3”. Thiếu mốc kết thúc hiệp 2 hoặc ngoài mùa thường thì chỉ hiện trạng thái halftime.
Nguồn thời lượng: [NFL Rule 4-1-3](https://operations.nfl.com/game-operations-logistics/preparation-safety/game-and-stadium-prep),
[NCAA Rule 3-2-1-b](https://ncaaorg.s3.amazonaws.com/championships/sports/football/rules/PRMFB_RulesBook.pdf).

## Cập nhật dữ liệu

Bấm shortcut **Actions - Cap nhat** trên Desktop **ít nhất mỗi ngày** (trang picks chỉ hiện picks vài ngày gần nhất).
Nút này lấy picks mới, chấm kết quả, xuất `reports/actions_report.xlsx`, dựng `site/index.html` rồi push lên GitHub;
workflow `pages` tự đăng dashboard.

Mặc định lấy điểm và line ESPN, không dùng credit The Odds API. Nếu chủ động chạy `run --odds-api`,
đặt key trong `.odds_api_key` ở thư mục repo (đã gitignore) hoặc biến môi trường `ODDS_API_KEY`;
các lượt gọi tùy chọn đó mới dùng credit theo gói API.

Trong **Kèo sắp tới**, cột **Tin tức** sau **Vì sao** tóm tắt có lợi/bất lợi cho từng đội NFL/NCAAF,
chỉ ở các kèo tô vàng (từ 8 expert trên cùng market). Tin có link nguồn, tối đa 2 ý mỗi nhóm;
không có tin xác minh thì để trống. Các lần cập nhật trực tuyến tự làm mới tin công khai từ RotoWire,
có cache 1 giờ và bỏ tin đã quá hạn. Có thể bổ sung tin đã kiểm chứng từ PFF, 247Sports và NFL.com.

Cột **Chuyên gia chọn winner** bên cạnh **Tin tức** hiển thị winner của các chuyên gia truyền thông,
có số người chọn mỗi đội, danh sách tên và link nguồn. Chỉ lấy **Straight Up / đội thắng trận**;
các picks ATS không được đổi thành winner. Cùng một chuyên gia/trận chỉ tính một lần dù bài được đăng lại.
Nguồn tự động là CBS Sports và NFL.com; có thể bổ sung picks College GameDay/Yahoo đã xác minh.
Các lượt chọn này có bộ đếm riêng với expert Action Network, chỉ ở trận NFL/NCAAF tô vàng.
Cùng cột cũng có trong bảng **Cách của bạn — Thứ 2–6 theo đám đông, Thứ 7–CN đánh ngược**
ở tab **Quy tắc**, dùng dữ liệu đã xác minh của các trận sắp đá tương ứng.

Cột **Chuyên gia chọn spread** giữ picks ATS riêng với winner và gom thêm các bài có tên tác giả
từ Covers, Sporting News, SportsBettingDime và NBC Sports, cùng bảng CBS hiện có. Mỗi chuyên gia/trận
chỉ tính một lần; giữ nguyên đội và line của từng người, kèm nguồn. Không chuyển tỉ số dự đoán thành ATS,
không tính props, total, kèo hiệp hoặc picks của mô hình AI vào số chuyên gia. Nguồn tự làm mới khi quét,
có cache 1 giờ; thiếu bài ATS xác minh thì không tạo picks.

Tab **Biểu đồ cả mùa** xem NFL và NCAAF từ tuần 1 đến dữ liệu đã thu, chia **Thứ 2–6** và
**Thứ 7–CN**, với ngưỡng đồng thuận 75%. **Over/Under** và **kèo đội (Spread/Moneyline)**
có biểu đồ và bảng chi tiết riêng trong từng tuần, xếp từ tuần 1. Có bộ lọc tuần, giải,
market và phân trang biểu đồ; số thắng/thua/hòa tính riêng theo tuần, nhóm kèo và nhóm ngày,
bao gồm mọi trang đang lọc. Nguồn là picks trên thẻ By Game lịch sử,
không phải số expert duy nhất của dữ liệu live. Tuần mới nhất có thể chưa đủ trận;
tab hiển thị phạm vi thực tế của từng giải.

Chạy riêng phần tin và picks chuyên gia, rồi dựng lại dashboard; không dùng credit The Odds API:

```bash
.venv/Scripts/python -m actions_tracker news
```

Tạo lại shortcut: `powershell -ExecutionPolicy Bypass -File scripts/install_shortcut.ps1`

## Chạy tay / phát triển

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m actions_tracker run              # lấy dữ liệu thật
.venv/Scripts/python -m actions_tracker run --offline tests/fixtures --db /tmp/t.db   # dùng dữ liệu mẫu
.venv/Scripts/python -m pytest
node --test tests/frontend/live_scores.test.cjs          # bộ lấy điểm trực tiếp trên trình duyệt
```

Thiết kế: `docs/superpowers/specs/2026-11-09-actions-expert-tracker-design.md`
