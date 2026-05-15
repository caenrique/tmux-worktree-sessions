"""Pure scoring helpers for tmux-sessions picker entries.

The score file is a TSV with one row per picked entry: ``name<TAB>score<TAB>ts``.
Scores decay exponentially with a configurable half-life. ``sort_rows``
orders TSV input lines by current score (highest first), optionally
adding a path-similarity boost so same-repo worktrees outrank
same-org projects.

This module is the **pure layer** — it never touches ``os.environ``,
``sys.stdin``/``stdout``, ``argparse``, the wall clock, or files. The
CLI layer in ``tmux_sessions.__main__`` resolves those concerns and
calls the functions below with explicit parameters.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def parse_score_table(text: str) -> list[tuple[str, float, float]]:
    """Parse score-file text into ``(name, base, ts)`` rows.

    Empty input yields ``[]``. Rows that are blank, missing fields, or
    have non-numeric ``base``/``ts`` are silently skipped — the same
    forgiving behaviour the awk pipeline had.
    """
    rows: list[tuple[str, float, float]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            base = float(parts[1])
            ts = float(parts[2])
        except ValueError:
            continue
        rows.append((parts[0], base, ts))
    return rows


def current_scores(
    entries: Iterable[tuple[str, float, float]],
    *,
    now: float,
    half_life_secs: float,
) -> dict[str, float]:
    """Apply exponential decay to each ``(name, base, ts)`` entry."""
    scores: dict[str, float] = {}
    for name, base, ts in entries:
        elapsed = max(0.0, now - ts)
        scores[name] = base * math.exp(-math.log(2) * elapsed / half_life_secs)
    return scores


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
