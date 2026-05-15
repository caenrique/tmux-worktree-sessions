from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_dispatcher_prints_usage() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")

    result = subprocess.run(
        [sys.executable, "-m", "tmux_sessions"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "usage" in (result.stdout + result.stderr).lower()
