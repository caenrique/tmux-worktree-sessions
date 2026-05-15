"""Pytest mirrors of the four bats `sort_by_score` cases.

The bats cases exercise the bash shim end-to-end (subprocess + env vars).
These cases test the underlying Python logic in-process.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

from tmux_sessions.score import run_sort


def _seed(score_file: Path, name: str, score: float, ts: float | None = None) -> None:
    score_file.parent.mkdir(parents=True, exist_ok=True)
    if ts is None:
        ts = time.time()
    with score_file.open("a") as f:
        f.write(f"{name}\t{score}\t{ts}\n")


def _run(
    stdin_text: str,
    *,
    boost_path: str,
    score_file: Path,
    path_boost: float = 1.0,
    half_life_days: float = 14,
) -> list[str]:
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    rc = run_sort(
        boost_path,
        score_file=str(score_file),
        half_life_days=half_life_days,
        path_boost=path_boost,
        stdin=stdin,
        stdout=stdout,
    )
    assert rc == 0
    return stdout.getvalue().splitlines()


def test_higher_score_first(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    now = time.time()
    _seed(score_file, "alpha", 1, now)
    _seed(score_file, "beta", 9, now)

    lines = _run(
        "alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n",
        boost_path="",
        score_file=score_file,
    )

    assert lines[0].startswith("beta")
    assert lines[1].startswith("alpha")


def test_path_boost_lifts_equal_score_row_sharing_prefix(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    now = time.time()
    _seed(score_file, "alpha", 1, now)
    _seed(score_file, "beta", 1, now)

    lines = _run(
        "alpha\t/p/repo\t/p/repo/main\nbeta\t/q/other\t/q/other\n",
        boost_path="/p/repo/feature",
        score_file=score_file,
    )

    assert lines[0].startswith("alpha")


def test_path_boost_disabled_at_zero_keeps_base_ordering(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    now = time.time()
    _seed(score_file, "alpha", 1, now)
    _seed(score_file, "beta", 2, now)

    lines = _run(
        "alpha\t/p/repo\t/p/repo/main\nbeta\t/q/other\t/q/other\n",
        boost_path="/p/repo/feature",
        score_file=score_file,
        path_boost=0,
    )

    assert lines[0].startswith("beta")


def test_missing_score_file_treats_all_as_zero(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"  # never created

    lines = _run(
        "alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n",
        boost_path="",
        score_file=score_file,
    )

    assert len(lines) == 2
