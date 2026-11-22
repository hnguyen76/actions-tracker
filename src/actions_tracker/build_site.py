"""Render the static dashboard: one HTML file with the analysis tables embedded as JSON (spec §8)."""

import hashlib
import json
import math
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd

PLACEHOLDER = "/*__DATA__*/null"
STALE_SUFFIXES = {".js", ".css", ".png", ".svg", ".webmanifest", ".txt", ".json", ".map"}  # static asset kinds


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


def site_version(template: str, static_files: list[tuple[str, bytes]]) -> str:
    """Cache-busting version of the published page: changes whenever the page template or a static file changes.
    An open dashboard compares it with the published page and reloads itself when a new design is out."""
    digest = hashlib.sha1(template.encode("utf-8"))
    for name, content in sorted(static_files):
        digest.update(name.encode() + content)
    return digest.hexdigest()[:10]


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
    static = resources.files("actions_tracker").joinpath("templates/static")
    files = [(f.name, f.read_bytes()) for f in static.iterdir() if f.is_file()] if static.is_dir() else []
    html = template.replace(PLACEHOLDER, data).replace("__STATIC_V__", site_version(template, files))
    out.write_text(html, encoding="utf-8")
    static = resources.files("actions_tracker").joinpath("templates/static")
    if static.is_dir():  # home-screen icons and the web app manifest (iPhone "Add to Home Screen")
        for f in static.iterdir():
            if f.is_file():
                (out_dir / f.name).write_bytes(f.read_bytes())
    # the same site/ folder is rebuilt and published again and again: drop asset files removed from the code
    current = {name for name, _ in files}
    for old in out_dir.iterdir():
        if old.is_file() and old.suffix.lower() in STALE_SUFFIXES and old.name not in current:
            old.unlink()
    if xlsx is not None and Path(xlsx).exists():
        shutil.copyfile(xlsx, out_dir / "actions_report.xlsx")
    return out
