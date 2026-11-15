# Actions Expert Tracker

Theo dõi picks của expert trên Action Network (NFL, NCAAF, NBA), chấm theo tỉ số và line của
[The Odds API](https://the-odds-api.com) và phân tích:

- **Consensus** — khi đa số expert chọn cùng một side, side đó thắng bao nhiêu %, đánh theo hay đánh ngược có lời.
- **Expert** — thành tích và thói quen chọn side (favorite/underdog, nhà/khách, over/under) của từng expert.

Dashboard: https://hnguyen76.github.io/actions-tracker/

## Cập nhật dữ liệu

Bấm shortcut **Actions - Cap nhat** trên Desktop **ít nhất mỗi ngày** (trang picks chỉ hiện picks vài ngày gần nhất).
Nút này lấy picks mới, chấm kết quả, xuất `reports/actions_report.xlsx`, dựng `site/index.html` rồi push lên GitHub;
workflow `pages` tự đăng dashboard.

API key The Odds API: đặt trong file `.odds_api_key` ở thư mục repo (đã gitignore) hoặc biến môi trường
`ODDS_API_KEY`. Gói miễn phí 500 credit/tháng; mỗi lần bấm tốn tối đa ~15 credit. Tỉ số chỉ lấy lại được 3 ngày,
nên đừng để quá 3 ngày không bấm.

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
```

Thiết kế: `docs/superpowers/specs/2026-11-09-actions-expert-tracker-design.md`
