"""Tests for ``Config.from_env`` resolution.

The CLI handlers in ``tmux_sessions.__main__`` resolve env vars exactly
once via ``Config.from_env``. These cases lock down that resolution:
defaults when nothing is set, ``~`` expansion in paths, ``SCORE_FILE``
precedence, and the icon-style fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tmux_sessions.__main__ import Config
from tmux_sessions.picker import IconSet


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop any tmux-sessions env vars from the parent shell."""
    for key in (
        "HOME",
        "SCORE_FILE",
        "TMUX_SESSIONS_PROJECTS_DIRS",
        "TMUX_SESSIONS_MAX_DEPTH",
        "TMUX_SESSIONS_STRIP_PREFIXES",
        "TMUX_SESSIONS_MANUAL_SESSIONS",
        "TMUX_SESSIONS_SCORE_HALF_LIFE",
        "TMUX_SESSIONS_SCORE_PATH_BOOST",
        "TMUX_SESSIONS_SCORES_FILE",
        "TMUX_SESSIONS_ICON_STYLE",
        "TMUX_SESSIONS_DEFAULT_BRANCH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_from_env_defaults_when_nothing_set() -> None:
    cfg = Config.from_env()

    assert cfg.home == ""
    assert cfg.projects_roots == [Path("/Projects")]
    assert cfg.max_depth == 6
    assert cfg.strip_prefixes == []
    assert cfg.manual_spec == ""
    assert cfg.half_life_secs == 14 * 24 * 3600
    assert cfg.path_boost == 1.0
    assert cfg.score_file == Path("/.local/share/tmux-sessions/scores.tsv")
    assert cfg.icons == IconSet.from_style("nerd")
    assert cfg.default_branch_fallback == "main"


def test_from_env_expands_tilde_in_projects_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/u")
    monkeypatch.setenv("TMUX_SESSIONS_PROJECTS_DIRS", "~/work ~/play")

    cfg = Config.from_env()

    assert cfg.projects_roots == [Path("/home/u/work"), Path("/home/u/play")]


def test_from_env_score_file_precedence_explicit_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.tsv"
    configured = tmp_path / "configured.tsv"
    monkeypatch.setenv("SCORE_FILE", str(explicit))
    monkeypatch.setenv("TMUX_SESSIONS_SCORES_FILE", str(configured))

    cfg = Config.from_env()

    assert cfg.score_file == explicit


def test_from_env_score_file_precedence_falls_back_to_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "configured.tsv"
    monkeypatch.setenv("TMUX_SESSIONS_SCORES_FILE", str(configured))

    cfg = Config.from_env()

    assert cfg.score_file == configured


def test_from_env_score_file_default_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/u")

    cfg = Config.from_env()

    assert cfg.score_file == Path("/home/u/.local/share/tmux-sessions/scores.tsv")


def test_from_env_unknown_icon_style_falls_back_to_nerd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_ICON_STYLE", "totally-bogus")

    cfg = Config.from_env()

    assert cfg.icons == IconSet.from_style("nerd")


def test_from_env_icon_style_ascii_takes_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_ICON_STYLE", "ascii")

    cfg = Config.from_env()

    assert cfg.icons == IconSet.from_style("ascii")


def test_from_env_default_branch_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_DEFAULT_BRANCH", "trunk")

    cfg = Config.from_env()

    assert cfg.default_branch_fallback == "trunk"


def test_from_env_half_life_in_days_converts_to_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_HALF_LIFE", "7")

    cfg = Config.from_env()

    assert cfg.half_life_secs == 7 * 24 * 3600
