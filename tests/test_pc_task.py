"""The PC scheduled task steps aside while the phone is pushing data."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("pc_task", Path(__file__).resolve().parent.parent / "scripts" / "pc_task.py")
pc_task = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc_task)


def test_phone_active_only_for_recent_phone_commits():
    now = 1_800_000_000
    assert pc_task.phone_active(f"{now - 600}|data: update 2026-11-15 14:00 (phone live)", now)
    assert not pc_task.phone_active(f"{now - 3600}|data: update 2026-11-15 13:00 (phone update)", now)
    assert not pc_task.phone_active(f"{now - 60}|data: update 2026-11-15 14:09 (live)", now)   # the PC's own commit
    assert not pc_task.phone_active("", now)
