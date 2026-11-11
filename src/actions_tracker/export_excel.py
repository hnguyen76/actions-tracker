"""Write the analysis tables to one Excel workbook (spec §8)."""

import os
from pathlib import Path

import pandas as pd
from openpyxl.utils import get_column_letter

SHEETS = ["Upcoming", "Past_Plays", "Consensus", "Experts", "Expert_Habits", "Expert_Form", "Trend_Weekly", "Picks"]
PERCENT_COLS = {"win_pct", "roi", "ci_low", "ci_high", "share", "fade_win_pct", "fade_roi", "hist_win_pct"}
MAX_WIDTH = 40


def write_report(tables: dict[str, pd.DataFrame], path: Path) -> bool:
    """Write the workbook atomically. Returns False (and leaves the old file) when it is open in Excel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        for name in SHEETS:
            df = tables.get(name, pd.DataFrame())
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = "A2"
            if ws.max_column and len(df.columns):
                ws.auto_filter.ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"
            for idx, col in enumerate(df.columns, start=1):
                letter = get_column_letter(idx)
                values = [str(col)] + [str(v) for v in df[col].head(500) if v is not None]
                ws.column_dimensions[letter].width = min(MAX_WIDTH, max(len(v) for v in values) + 2)
                if col in PERCENT_COLS:
                    for cell in ws[letter][1:]:
                        cell.number_format = "0.0%"
    try:
        os.replace(tmp, path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        return False
    return True
