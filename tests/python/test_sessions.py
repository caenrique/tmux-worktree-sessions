"""Tests for :mod:`tmux_sessions.sessions`.

Pure-layer cases for ``parse_manual_sessions``,
``is_orphaned_worktree``, and the action rewrites; CLI-layer cases that
exercise ``sessions list-projects``, ``sessions is-orphaned-worktree``,
and ``sessions action ctrl-x`` via ``main(...)`` mirror the
corresponding bats coverage.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_sessions.__main__ import main
from tmux_sessions.picker import IconSet
from tmux_sessions.sessions import (
    apply_ctrl_x,
    is_orphaned_worktree,
    parse_manual_sessions,
)


def test_parse_manual_sessions_empty_spec_returns_empty() -> None:
    assert parse_manual_sessions("", home="/home/u") == []


def test_parse_manual_sessions_splits_name_path_pairs() -> None:
    pairs = parse_manual_sessions("dotfiles:/etc/cfg notes:/var/notes", home="/home/u")
    assert pairs == [
        ("dotfiles", Path("/etc/cfg")),
        ("notes", Path("/var/notes")),
    ]


def test_parse_manual_sessions_expands_leading_tilde() -> None:
    pairs = parse_manual_sessions("home:~/somewhere", home="/home/u")
    assert pairs == [("home", Path("/home/u/somewhere"))]


def test_parse_manual_sessions_skips_tokens_without_colon() -> None:
    pairs = parse_manual_sessions("ok:/p bad notagain:/q", home="/home/u")
    assert pairs == [("ok", Path("/p")), ("notagain", Path("/q"))]


def test_is_orphaned_worktree_true_when_sibling_has_dotgit(tmp_path: Path) -> None:
    container = tmp_path / "wt"
    orphan = container / "orphan"
    realrepo = container / "realrepo"
    orphan.mkdir(parents=True)
    realrepo.mkdir(parents=True)
    (realrepo / ".git").mkdir()
    assert is_orphaned_worktree(orphan, container=container) is True


def test_is_orphaned_worktree_false_when_no_siblings(tmp_path: Path) -> None:
    container = tmp_path / "lonely"
    only = container / "only"
    only.mkdir(parents=True)
    assert is_orphaned_worktree(only, container=container) is False


def test_is_orphaned_worktree_false_when_sibling_has_no_dotgit(tmp_path: Path) -> None:
    container = tmp_path / "wt"
    orphan = container / "orphan"
    notes = container / "notes"
    orphan.mkdir(parents=True)
    notes.mkdir(parents=True)
    assert is_orphaned_worktree(orphan, container=container) is False


def test_is_orphaned_worktree_accepts_dotgit_file_as_well_as_dir(tmp_path: Path) -> None:
    container = tmp_path / "wt"
    orphan = container / "orphan"
    linked = container / "linked"
    orphan.mkdir(parents=True)
    linked.mkdir(parents=True)
    (linked / ".git").write_text("gitdir: /elsewhere/.git/worktrees/linked\n")
    assert is_orphaned_worktree(orphan, container=container) is True


def test_is_orphaned_worktree_missing_container_returns_false(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    candidate = missing / "child"
    assert is_orphaned_worktree(candidate, container=missing) is False


def _run_sessions_list_projects(
    monkeypatch: pytest.MonkeyPatch,
    *,
    projects_dir: Path,
    home: str,
    manual: str = "",
    strip_prefixes: str = "",
    max_depth: str = "4",
) -> list[str]:
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("TMUX_SESSIONS_PROJECTS_DIRS", str(projects_dir))
    monkeypatch.setenv("TMUX_SESSIONS_MAX_DEPTH", max_depth)
    monkeypatch.setenv("TMUX_SESSIONS_STRIP_PREFIXES", strip_prefixes)
    monkeypatch.setenv("TMUX_SESSIONS_MANUAL_SESSIONS", manual)
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    rc = main(["sessions", "list-projects"])
    assert rc == 0
    return stdout.getvalue().splitlines()


def test_cli_list_projects_emits_one_row_per_git_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    make_repo: Callable[..., Path],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    bar = make_repo("projects/bar")

    lines = _run_sessions_list_projects(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    paths = [line.split("\t", 1)[1] for line in lines]
    assert str(foo) in paths
    assert str(bar) in paths


def test_cli_list_projects_appends_manual_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()

    lines = _run_sessions_list_projects(
        monkeypatch,
        projects_dir=projects_dir,
        home=str(tmp_path),
        manual=f"dotfiles:{cfg}",
    )

    assert f"dotfiles\t{cfg}" in lines


def test_cli_list_projects_expands_tilde_in_manual_session_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    lines = _run_sessions_list_projects(
        monkeypatch,
        projects_dir=projects_dir,
        home=str(tmp_path),
        manual="home:~/somewhere",
    )

    assert f"home\t{tmp_path}/somewhere" in lines


def test_cli_is_orphaned_worktree_exit_zero_when_sibling_has_dotgit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = tmp_path / "wt"
    orphan = container / "orphan"
    realrepo = container / "realrepo"
    orphan.mkdir(parents=True)
    realrepo.mkdir(parents=True)
    (realrepo / ".git").mkdir()

    rc = main(["sessions", "is-orphaned-worktree", str(orphan)])
    assert rc == 0


def test_cli_is_orphaned_worktree_exit_one_when_no_sibling_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = tmp_path / "lonely"
    only = container / "only"
    only.mkdir(parents=True)

    rc = main(["sessions", "is-orphaned-worktree", str(only)])
    assert rc == 1


def test_apply_ctrl_x_inserts_project_row_above_n_sentinel() -> None:
    icons = IconSet.from_style("none")
    lines = [
        "s\t3\talpha\talpha",
        "p\t/p/other\tother\tother",
        "n\t\tnew session\tnew session",
    ]
    out = apply_ctrl_x(lines, sid="3", sess_path="/p/alpha", icons=icons)
    assert out == [
        "p\t/p/other\tother\tother",
        "p\t/p/alpha\talpha\talpha",
        "n\t\tnew session\tnew session",
    ]


def test_apply_ctrl_x_appends_when_no_sentinel() -> None:
    icons = IconSet.from_style("none")
    lines = ["s\t3\talpha\talpha", "p\t/p/other\tother\tother"]
    out = apply_ctrl_x(lines, sid="3", sess_path="/p/alpha", icons=icons)
    assert out == [
        "p\t/p/other\tother\tother",
        "p\t/p/alpha\talpha\talpha",
    ]


def test_apply_ctrl_x_no_match_returns_lines_unchanged() -> None:
    icons = IconSet.from_style("none")
    lines = ["p\t/p/foo\tfoo\tfoo", "n\t\tnew session\tnew session"]
    out = apply_ctrl_x(lines, sid="9", sess_path="/p/x", icons=icons)
    assert out == lines


def test_apply_ctrl_x_uses_project_icon() -> None:
    icons = IconSet.from_style("ascii")
    lines = ["s\t3\talpha\talpha"]
    out = apply_ctrl_x(lines, sid="3", sess_path="/p/alpha", icons=icons)
    assert out == ["p\t/p/alpha\talpha\t. alpha"]


def test_cli_action_ctrl_x_rewrites_tmpfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_ICON_STYLE", "none")
    tmux_stub(sessions="alpha\t$3\t/p/alpha")
    tmpfile = tmp_path / "entries"
    tmpfile.write_text("s\t3\talpha\talpha\np\t/p/other\tother\tother\nn\t\tnew session\tnew session\n")

    rc = main(["sessions", "action", "ctrl-x", "s", "3", str(tmpfile)])
    assert rc == 0

    out = tmpfile.read_text().splitlines()
    assert out == [
        "p\t/p/other\tother\tother",
        "p\t/p/alpha\talpha\talpha",
        "n\t\tnew session\tnew session",
    ]


def test_cli_action_ctrl_x_non_session_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TMUX_SESSIONS_ICON_STYLE", "none")
    tmux_stub()
    tmpfile = tmp_path / "entries"
    before = "p\t/p/foo\tfoo\tfoo\n"
    tmpfile.write_text(before)

    rc = main(["sessions", "action", "ctrl-x", "p", "/p/foo", str(tmpfile)])
    assert rc == 0
    assert tmpfile.read_text() == before


def _run_sessions_build_entries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    projects_dir: Path,
    home: str,
    icon_style: str = "none",
) -> list[str]:
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("TMUX_SESSIONS_PROJECTS_DIRS", str(projects_dir))
    monkeypatch.setenv("TMUX_SESSIONS_MAX_DEPTH", "4")
    monkeypatch.setenv("TMUX_SESSIONS_STRIP_PREFIXES", "")
    monkeypatch.setenv("TMUX_SESSIONS_MANUAL_SESSIONS", "")
    monkeypatch.setenv("TMUX_SESSIONS_ICON_STYLE", icon_style)
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_HALF_LIFE", "14")
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_PATH_BOOST", "1.0")
    monkeypatch.setenv("SCORE_FILE", "")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    rc = main(["sessions", "build-entries"])
    assert rc == 0
    return stdout.getvalue().splitlines()


def test_cli_build_entries_project_only_ends_with_n_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    tmux_stub(sessions="")

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path), icon_style="ascii")

    assert any(line.startswith(f"p\t{foo}\t") for line in lines)
    assert lines[-1].startswith("n\t\tnew session\t")


def test_cli_build_entries_pins_current_session_yellow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    tmux_stub(sessions="alpha\t$1\t/p/alpha")

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")
    assert "alpha" in lines[0]
    assert "(current)" in lines[0]


def test_cli_build_entries_pins_previous_session_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    monkeypatch.setenv("TMUX_STUB_PREV", "beta")
    tmux_stub(sessions="alpha\t$1\t/p/alpha\nbeta\t$2\t/p/beta")

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")
    assert "(current)" in lines[0]
    assert lines[1].startswith("s\t2\t")
    assert "(previous)" in lines[1]


def test_cli_build_entries_remaining_sessions_ordered_by_last_attached_desc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    monkeypatch.setenv("TMUX_STUB_PREV", "beta")
    tmux_stub(
        sessions=(
            "alpha\t$1\t/p/alpha\t1000\n"
            "beta\t$2\t/p/beta\t900\n"
            "gamma\t$3\t/p/gamma\t800\n"
            "delta\t$4\t/p/delta\t950\n"
            "epsilon\t$5\t/p/epsilon\t850"
        ),
    )

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")  # alpha (current)
    assert lines[1].startswith("s\t2\t")  # beta (previous)
    assert lines[2].startswith("s\t4\t")  # delta last_attached=950
    assert lines[3].startswith("s\t5\t")  # epsilon last_attached=850
    assert lines[4].startswith("s\t3\t")  # gamma last_attached=800


def test_cli_build_entries_filters_projects_matching_open_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    from tmux_sessions.text import format_session_name

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    # The session is named after the project's format_session_name output;
    # tmux replaces dots with underscores so the comparison is dot-normalised.
    proj_name = format_session_name(str(foo), home=str(tmp_path), strip_prefixes=[])
    tmux_stub(sessions=f"{proj_name}\t$3\t{foo}")

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    assert not any(line.startswith(f"p\t{foo}\t") for line in lines)
    assert any(proj_name in line for line in lines)


def test_cli_build_entries_every_line_has_exactly_4_tsv_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    make_repo("projects/foo")
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    tmux_stub(sessions="alpha\t$1\t/p/alpha")

    lines = _run_sessions_build_entries(monkeypatch, projects_dir=projects_dir, home=str(tmp_path))

    for line in lines:
        assert line.count("\t") == 3, f"bad line: {line!r}"
