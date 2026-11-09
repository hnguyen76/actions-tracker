import openpyxl
import pandas as pd

from actions_tracker import db
from actions_tracker.analysis import build_tables
from actions_tracker.export_excel import SHEETS, write_report

ORDER = ["Upcoming", "Consensus", "Experts", "Expert_Habits", "Expert_vs_Public", "Trend_Weekly", "Picks"]


def test_sheet_order_and_format(tmp_path):
    tables = {name: pd.DataFrame([{"league": "nfl", "win_pct": 0.55, "roi": 0.1, "n": 3}]) for name in ORDER}
    tables["Leaderboard"] = pd.DataFrame([{"rank": 1}])
    path = tmp_path / "r.xlsx"
    write_report(tables, path)
    wb = openpyxl.load_workbook(path)
    assert SHEETS == ORDER and wb.sheetnames == ORDER
    ws = wb["Consensus"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:D2"
    assert [c.value for c in ws[1]] == ["league", "win_pct", "roi", "n"]
    assert ws["B2"].number_format == "0.0%" and ws["C2"].number_format == "0.0%"


def test_empty_tables_still_write_headers(tmp_path):
    path = tmp_path / "e.xlsx"
    write_report(build_tables(db.connect(tmp_path / "e.db"), "2026-11-09T00:00:00.000Z"), path)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ORDER
    assert "win_pct" in [c.value for c in wb["Consensus"][1]]
