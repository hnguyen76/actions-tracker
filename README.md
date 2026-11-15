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
Chạy riêng phần tin và dựng lại dashboard, không lấy lại picks/odds:

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
