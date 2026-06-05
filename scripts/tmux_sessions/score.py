"""Pure scoring helpers for tmux-sessions picker entries.

The score file is a TSV with one row per picked entry: ``name<TAB>score<TAB>ts``.
Scores decay exponentially with a configurable half-life. ``sort_rows``
orders TSV input lines by current score (highest first), optionally
adding a path-similarity boost so same-repo worktrees outrank
same-org projects.

The functions below take all inputs as explicit parameters; the CLI
layer in ``tmux_sessions.__main__`` resolves env vars / wall-clock /
stdin/stdout. ``bump_in_file`` is the one place that owns score-file
I/O, replacing what would otherwise be a duplicated read/parse/merge/
atomic-rewrite dance at every call site.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def parse_score_table(text: str) -> list[tuple[str, float, float]]:
    """Parse score-file text into ``(name, base, ts)`` rows.

    Empty input yields ``[]``. Rows that are blank, missing fields, or
    have non-numeric ``base``/``ts`` are silently skipped.
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


def merge_score(
    entries: list[tuple[str, float, float]],
    *,
    name: str,
    now: float,
    half_life_secs: float,
) -> list[tuple[str, float, float]]:
    """Return ``entries`` with ``name``'s score decayed and incremented by 1.

    If ``name`` already has a row, replace it in place with
    ``base * exp(-ln2 * elapsed / half_life_secs) + 1`` and timestamp
    ``now``. Otherwise append ``(name, 1.0, now)``.
    """
    out: list[tuple[str, float, float]] = []
    found = False
    for entry_name, base, ts in entries:
        if entry_name == name:
            elapsed = max(0.0, now - ts)
            decay = math.exp(-math.log(2) * elapsed / half_life_secs)
            out.append((name, base * decay + 1.0, now))
            found = True
        else:
            out.append((entry_name, base, ts))
    if not found:
        out.append((name, 1.0, now))
    return out


def _format_number(x: float) -> str:
    """Format a float so integer-valued numbers print without a decimal."""
    if x == int(x):
        return str(int(x))
    return f"{x:.6g}"


def format_score_table(entries: list[tuple[str, float, float]]) -> str:
    """Serialize score entries to ``name<TAB>score<TAB>ts\\n`` rows."""
    if not entries:
        return ""
    lines = [f"{name}\t{_format_number(score)}\t{_format_number(ts)}" for name, score, ts in entries]
    return "\n".join(lines) + "\n"


def bump_in_file(
    path: Path,
    *,
    name: str,
    now: float,
    half_life_secs: float,
) -> None:
    """Read, decay-and-merge, atomically rewrite the score file.

    Creates the parent directory if missing; treats a missing file as
    empty input. Writes through a sibling ``.tmp`` then ``replace`` so
    a crash mid-write cannot leave a half-written score file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = path.read_text()
    except FileNotFoundError:
        existing = ""
    entries = parse_score_table(existing)
    new_entries = merge_score(entries, name=name, now=now, half_life_secs=half_life_secs)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(format_score_table(new_entries))
    tmp.replace(path)


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
