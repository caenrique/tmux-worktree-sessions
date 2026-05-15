"""Pure-layer tests for the four bats `sort_by_score` scenarios.

These exercise the underlying Python logic in-process. The bats cases
exercise the bash shim end-to-end; the CLI handler is covered by
`test_score_cli.py`.
"""

from __future__ import annotations

from tmux_sessions.score import current_scores, parse_score_table, sort_rows

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
