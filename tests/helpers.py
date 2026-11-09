"""Build graded-pick DataFrames for analysis tests."""

import pandas as pd

from actions_tracker.grading import COLUMNS

DEFAULTS = {
    "league": "nfl",
    "created_at": "2026-11-09T12:00:00.000Z",
    "start_time": "2026-11-06T01:00:00.000Z",
    "status": "complete",
    "odds": -110,
}


def make_picks(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        row = {c: None for c in COLUMNS} | DEFAULTS | r
        row.setdefault("expert_name", None)
        if row["expert_name"] is None:
            row["expert_name"] = f"E{row['expert_id']}"
        if "expert_result" not in r:
            row["expert_result"] = row["side_result"]
        out.append(row)
    return pd.DataFrame(out, columns=COLUMNS).astype(object)
