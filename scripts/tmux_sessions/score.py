"""Score storage and ranking for tmux-sessions picker entries.

The score file is a TSV with one row per picked entry: ``name<TAB>score<TAB>ts``.
Scores decay exponentially with a configurable half-life. ``sort_rows``
orders TSV input lines by current score (highest first), optionally
adding a path-similarity boost so same-repo worktrees outrank
same-org projects.
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections.abc import Iterable
from typing import IO


def load_scores(path: str, now: float, half_life_secs: float) -> dict[str, float]:
    """Load decayed scores from ``path``. Returns ``{}`` if the file is missing."""
    scores: dict[str, float] = {}
    if not path:
        return scores
    try:
        with open(path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3 or not parts[0]:
                    continue
                try:
                    base = float(parts[1])
                    ts = float(parts[2])
                except ValueError:
                    continue
                elapsed = max(0.0, now - ts)
                scores[parts[0]] = base * math.exp(-math.log(2) * elapsed / half_life_secs)
    except FileNotFoundError:
        return scores
    return scores


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def sort_rows(
    lines: Iterable[str],
    *,
    boost_path: str,
    scores: dict[str, float],
    path_boost: float,
) -> list[str]:
    """Sort TSV ``name<TAB>...<TAB>path`` lines by score, descending.

    Lines shorter than 3 fields are passed through with no boost. Equal
    scores preserve input order (stable sort via index tiebreaker).
    """
    rows: list[tuple[float, int, str]] = []
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\n")
        cols = line.split("\t")
        score: float = scores.get(cols[0], 0.0)
        if boost_path and len(cols) >= 3 and cols[2]:
            cpl = common_prefix_len(boost_path, cols[2])
            score += (cpl / 120.0) * path_boost
        rows.append((-score, idx, line))
    rows.sort()
    return [line for _, _, line in rows]


def run_sort(
    boost_path: str,
    *,
    score_file: str | None = None,
    half_life_days: float | None = None,
    path_boost: float | None = None,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    now: float | None = None,
) -> int:
    """CLI entry point for ``score sort``.

    Reads TSV from ``stdin`` and writes the score-sorted rows to ``stdout``.
    Configuration is read from ``SCORE_FILE``,
    ``TMUX_SESSIONS_SCORE_HALF_LIFE`` (days), and
    ``TMUX_SESSIONS_SCORE_PATH_BOOST`` when arguments are omitted.
    """
    if score_file is None:
        score_file = os.environ.get("SCORE_FILE", "")
    if half_life_days is None:
        half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    if path_boost is None:
        path_boost = float(os.environ.get("TMUX_SESSIONS_SCORE_PATH_BOOST") or 1.0)
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if now is None:
        now = time.time()

    half_life_secs: float = half_life_days * 24 * 3600
    scores = load_scores(score_file, now, half_life_secs)
    sorted_lines = sort_rows(stdin, boost_path=boost_path, scores=scores, path_boost=path_boost)
    for line in sorted_lines:
        stdout.write(line)
        stdout.write("\n")
    return 0
