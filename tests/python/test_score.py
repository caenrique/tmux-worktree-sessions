"""Pure-layer tests for the score module.

Cover the ranking logic (``sort_rows`` / ``current_scores``), the score-
table parser/serialiser, the ``merge_score`` decay-and-increment, and
the ``bump_in_file`` atomic rewrite.
"""

from __future__ import annotations

import math
from pathlib import Path

from tmux_sessions.score import (
    bump_in_file,
    current_scores,
    format_score_table,
    merge_score,
    parse_score_table,
    sort_rows,
)

NOW = 1_700_000_000.0
HALF_LIFE_SECS = 14 * 24 * 3600


def _scores_for(rows: list[tuple[str, float, float]]) -> dict[str, float]:
    return current_scores(rows, now=NOW, half_life_secs=HALF_LIFE_SECS)


def test_higher_score_first() -> None:
    scores = _scores_for([("alpha", 1.0, NOW), ("beta", 9.0, NOW)])

    lines = sort_rows(
        ["alpha\t/p/a\t/p/a", "beta\t/p/b\t/p/b"],
        boost_path="",
        scores=scores,
        path_boost=1.0,
    )

    assert lines[0].startswith("beta")
    assert lines[1].startswith("alpha")


def test_path_boost_lifts_equal_score_row_sharing_prefix() -> None:
    scores = _scores_for([("alpha", 1.0, NOW), ("beta", 1.0, NOW)])

    lines = sort_rows(
        ["alpha\t/p/repo\t/p/repo/main", "beta\t/q/other\t/q/other"],
        boost_path="/p/repo/feature",
        scores=scores,
        path_boost=1.0,
    )

    assert lines[0].startswith("alpha")


def test_path_boost_disabled_at_zero_keeps_base_ordering() -> None:
    scores = _scores_for([("alpha", 1.0, NOW), ("beta", 2.0, NOW)])

    lines = sort_rows(
        ["alpha\t/p/repo\t/p/repo/main", "beta\t/q/other\t/q/other"],
        boost_path="/p/repo/feature",
        scores=scores,
        path_boost=0.0,
    )

    assert lines[0].startswith("beta")


def test_empty_score_table_treats_all_as_zero() -> None:
    scores = _scores_for(parse_score_table(""))

    lines = sort_rows(
        ["alpha\t/p/a\t/p/a", "beta\t/p/b\t/p/b"],
        boost_path="",
        scores=scores,
        path_boost=1.0,
    )

    assert len(lines) == 2
    assert scores == {}


def test_parse_score_table_skips_invalid_rows() -> None:
    text = "alpha\t1.0\t100\nblank-row\nbeta\tnotnum\t200\ngamma\t2.0\t300\n"
    rows = parse_score_table(text)

    assert rows == [("alpha", 1.0, 100.0), ("gamma", 2.0, 300.0)]


def test_merge_score_appends_fresh_entry() -> None:
    out = merge_score([], name="alpha", now=NOW, half_life_secs=HALF_LIFE_SECS)

    assert out == [("alpha", 1.0, NOW)]


def test_merge_score_decays_existing_entry_in_place() -> None:
    one_half_life_ago = NOW - HALF_LIFE_SECS
    out = merge_score(
        [("alpha", 4.0, one_half_life_ago)],
        name="alpha",
        now=NOW,
        half_life_secs=HALF_LIFE_SECS,
    )

    assert len(out) == 1
    name, score, ts = out[0]
    assert name == "alpha"
    assert ts == NOW
    assert math.isclose(score, 3.0, abs_tol=0.01)  # 4 * 0.5 + 1 = 3


def test_merge_score_preserves_other_entries() -> None:
    out = merge_score(
        [("alpha", 5.0, NOW), ("gamma", 2.0, NOW)],
        name="beta",
        now=NOW,
        half_life_secs=HALF_LIFE_SECS,
    )

    names = [n for n, _, _ in out]
    assert names == ["alpha", "gamma", "beta"]


def test_format_score_table_integer_floats_render_without_decimal() -> None:
    rendered = format_score_table([("alpha", 1.0, 1700000000.0)])

    assert rendered == "alpha\t1\t1700000000\n"


def test_format_score_table_empty_input_returns_empty() -> None:
    assert format_score_table([]) == ""


def test_bump_in_file_creates_parent_directory_when_missing(tmp_path: Path) -> None:
    score_file = tmp_path / "nested" / "dir" / "scores.tsv"

    bump_in_file(score_file, name="alpha", now=NOW, half_life_secs=HALF_LIFE_SECS)

    assert score_file.is_file()


def test_bump_in_file_writes_score_one_for_fresh_entry(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"

    bump_in_file(score_file, name="alpha", now=NOW, half_life_secs=HALF_LIFE_SECS)

    assert score_file.read_text() == f"alpha\t1\t{int(NOW)}\n"


def test_bump_in_file_decays_and_increments_existing_entry(tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    one_half_life_ago = NOW - HALF_LIFE_SECS
    score_file.write_text(f"alpha\t4\t{int(one_half_life_ago)}\n")

    bump_in_file(score_file, name="alpha", now=NOW, half_life_secs=HALF_LIFE_SECS)

    entries = parse_score_table(score_file.read_text())
    assert len(entries) == 1
    name, value, ts = entries[0]
    assert name == "alpha"
    assert ts == NOW
    assert math.isclose(value, 3.0, abs_tol=0.01)  # 4 * 0.5 + 1 = 3
