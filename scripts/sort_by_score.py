#!/usr/bin/env python3
"""Score-sort tmux-sessions picker entries.

Reads tab-separated rows from stdin and writes them back in order of
decreasing score (highest first). Each row's score is read from the file
at $SCORE_FILE (decayed forward to "now") and optionally augmented by a
path-similarity boost against the boost_path argument.

Stdin/stdout format
-------------------
Each line is `name<TAB>...<TAB>path` (3+ TAB-delimited fields). Column 1
is the score-file key; column 3 is the path used for the boost. Lines
shorter than 3 fields are still passed through, just with no boost.

Arguments
---------
argv[1]   boost_path. Pass an empty string to disable the boost.

Environment
-----------
SCORE_FILE                       path to the score TSV (name, score, ts)
TMUX_SESSIONS_SCORE_HALF_LIFE    decay half-life in days (default 14)
TMUX_SESSIONS_SCORE_PATH_BOOST   path-boost multiplier  (default 1.0)
"""

from __future__ import annotations

import math
import os
import sys
import time


def load_scores(path: str, now: float, half_life_secs: float) -> dict[str, float]:
    scores: dict[str, float] = {}
    if not path:
        return scores
    try:
        f = open(path)
    except FileNotFoundError:
        return scores
    with f:
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
    return scores


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def main() -> None:
    boost_path: str = sys.argv[1] if len(sys.argv) > 1 else ""
    score_file: str = os.environ.get("SCORE_FILE", "")
    half_life_days: float = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    path_boost: float = float(os.environ.get("TMUX_SESSIONS_SCORE_PATH_BOOST") or 1.0)

    half_life_secs: float = half_life_days * 24 * 3600
    now: float = time.time()
    scores: dict[str, float] = load_scores(score_file, now, half_life_secs)

    rows: list[tuple[float, int, str]] = []
    for idx, raw in enumerate(sys.stdin):
        line = raw.rstrip("\n")
        cols = line.split("\t")
        score: float = scores.get(cols[0], 0.0)
        if boost_path and len(cols) >= 3 and cols[2]:
            cpl = common_prefix_len(boost_path, cols[2])
            score += (cpl / 120.0) * path_boost
        # idx as tiebreaker preserves input order for equal scores (stable).
        rows.append((-score, idx, line))

    rows.sort()
    for _, _, line in rows:
        sys.stdout.write(line)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
