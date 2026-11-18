"""The phone's overnight sync republishes code changes without starting a data collection."""

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sync_builds_and_publishes_once_per_head_without_collecting(tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    (repo / ".git").mkdir()
    shutil.copy2(ROOT / "scripts" / "auto_update.sh", scripts / "auto_update.sh")

    git = fake_bin / "git"
    git.write_text("""#!/bin/sh
if [ "$1" = rev-parse ] && [ "$2" = --git-path ]; then echo .git/actions-last-published; exit 0; fi
if [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then echo abc123; exit 0; fi
if [ "$1" = pull ]; then exit 0; fi
exit 0
""", "utf-8")
    git.chmod(0o755)
    calls = tmp_path / "python-calls"
    python = fake_bin / "python"
    python.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{calls}'\n", "utf-8")
    python.chmod(0o755)

    env = os.environ.copy()
    env.update({"PATH": f"{fake_bin}:{env['PATH']}", "PY": str(python), "HOME": str(tmp_path / "home")})
    env.pop("PREFIX", None)
    command = ["bash", str(scripts / "auto_update.sh"), "sync"]
    subprocess.run(command, cwd=repo, env=env, check=True)
    subprocess.run(command, cwd=repo, env=env, check=True)

    assert calls.read_text("utf-8").splitlines() == ["-m actions_tracker build", "scripts/publish_site.py"]
    assert (repo / ".git" / "actions-last-published").read_text("utf-8").strip() == "abc123"


def test_termux_setup_installs_always_on_sync_and_overnight_news_crons():
    setup = (ROOT / "scripts" / "termux_setup.sh").read_text("utf-8")
    assert '2-59/5 * * * * $J sync $L' in setup
    assert '7-52/15 0-10,23 * * * $J news $L' in setup


def test_existing_termux_install_self_heals_overnight_news_cron():
    script = (ROOT / "scripts" / "auto_update.sh").read_text("utf-8")
    assert 'auto_update.sh news' in script
    assert '7-52/15 0-10,23 * * *' in script


def test_telegram_alert_schedule_runs_after_9pm_until_midnight():
    setup = (ROOT / "scripts" / "termux_setup.sh").read_text("utf-8")
    script = (ROOT / "scripts" / "auto_update.sh").read_text("utf-8")
    assert '1-59/5 11-23 * * * $J alert $L' in setup
    assert '1-59/5 11-22 * * * $J alert $L' not in setup
    assert '1-59/5 11-23 * * * bash $REPO/scripts/auto_update.sh alert' in script
    assert 'ensure_alert_cron' in script


def test_live_score_schedule_runs_every_five_minutes_until_3am():
    setup = (ROOT / "scripts" / "termux_setup.sh").read_text("utf-8")
    script = (ROOT / "scripts" / "auto_update.sh").read_text("utf-8")
    assert '3-59/5 0-2,9-23 * * * $J live $L' in setup
    assert '3-59/5 9-23 * * * $J live $L' not in setup
    assert '3-59/5 0-2,9-23 * * * bash $REPO/scripts/auto_update.sh live' in script
    assert 'ensure_live_cron' in script


def test_existing_termux_cron_is_replaced_with_late_alert_schedule(tmp_path):
    repo, fake_bin = tmp_path / "repo", tmp_path / "bin"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    (repo / ".git").mkdir()
    shutil.copy2(ROOT / "scripts" / "auto_update.sh", scripts / "auto_update.sh")
    state = tmp_path / "crontab"
    state.write_text(
        f"2-59/5 * * * * bash {scripts / 'auto_update.sh'} sync >> {tmp_path}/actions-auto.log 2>&1\n"
        f"7-52/15 0-10,23 * * * bash {scripts / 'auto_update.sh'} news >> {tmp_path}/actions-auto.log 2>&1\n"
        f"1-59/5 11-22 * * * bash {scripts / 'auto_update.sh'} alert >> {tmp_path}/actions-auto.log 2>&1\n"
        f"1-59/5 9-10 * * 0 bash {scripts / 'auto_update.sh'} alert >> {tmp_path}/actions-auto.log 2>&1\n"
        f"3-59/5 9-23 * * * bash {scripts / 'auto_update.sh'} live >> {tmp_path}/actions-auto.log 2>&1\n",
        "utf-8",
    )
    crontab = fake_bin / "crontab"
    crontab.write_text("""#!/bin/sh
if [ "$1" = "-l" ]; then cat "$CRON_STATE"; exit 0; fi
if [ "$1" = "-" ]; then cat > "$CRON_STATE"; exit 0; fi
exit 2
""", "utf-8")
    crontab.chmod(0o755)
    git = fake_bin / "git"
    git.write_text("""#!/bin/sh
if [ "$1" = rev-parse ] && [ "$2" = --git-path ]; then echo .git/actions-last-published; exit 0; fi
if [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then echo abc123; exit 0; fi
if [ "$1" = pull ]; then exit 0; fi
exit 0
""", "utf-8")
    git.chmod(0o755)
    python = fake_bin / "python"
    python.write_text("#!/bin/sh\nexit 0\n", "utf-8")
    python.chmod(0o755)
    env = os.environ.copy()
    env.update({"PATH": f"{fake_bin}:{env['PATH']}", "PY": str(python), "HOME": str(tmp_path),
                "PREFIX": "/data/data/com.termux/files/usr", "CRON_STATE": str(state)})
    subprocess.run(["bash", str(scripts / "auto_update.sh"), "sync"], cwd=repo, env=env, check=True)
    installed = state.read_text("utf-8")
    assert "1-59/5 11-23 * * *" in installed
    assert "1-59/5 11-22 * * *" not in installed
    assert installed.count("auto_update.sh alert") == 2
    assert "3-59/5 0-2,9-23 * * *" in installed
    assert "3-59/5 9-23 * * *" not in installed
    assert installed.count("auto_update.sh live") == 1
