"""Render the static dashboard: one HTML file with the analysis tables embedded as JSON (spec §8)."""

import json
import math
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd

PLACEHOLDER = "/*__DATA__*/null"


def _plain(v):
    if v is None:
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _plain(v) for k, v in row.items()} for row in df.astype(object).to_dict("records")]


def build_site(tables: dict[str, pd.DataFrame], status: list[dict], out_dir: Path, xlsx: Path | None,
               generated_at: str, meta: dict | None = None) -> Path:
    payload = {
        "generated_at": generated_at,
        "meta": {k: _plain(v) for k, v in (meta or {}).items()},
        "league_status": [{k: _plain(v) for k, v in s.items()} for s in status],
        "tables": {name: _records(df) for name, df in tables.items()},
    }
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")
    template = resources.files("actions_tracker").joinpath("templates/index.html").read_text("utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise RuntimeError("dashboard template must contain the data placeholder exactly once")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(template.replace(PLACEHOLDER, data), encoding="utf-8")
    if xlsx is not None and Path(xlsx).exists():
        shutil.copyfile(xlsx, out_dir / "actions_report.xlsx")
    return out
