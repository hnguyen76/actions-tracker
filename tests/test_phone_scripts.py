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
