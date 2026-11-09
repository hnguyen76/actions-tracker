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
