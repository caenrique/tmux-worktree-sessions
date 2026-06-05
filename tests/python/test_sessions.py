"""Tests for :mod:`tmux_worktree_sessions.sessions`.

Pure-layer cases for ``parse_manual_sessions``, ``list_projects``,
``is_orphaned_worktree``, ``build_entries``, and the action-row
rewrites; CLI-layer cases for the four production action subcommands
(``ctrl-x``, ``ctrl-r``, ``ctrl-d``) plus ``display-name`` and
``manage`` exercise ``main(...)`` end-to-end.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_worktree_sessions.__main__ import main
from tmux_worktree_sessions.picker import IconSet
from tmux_worktree_sessions.sessions import (
    apply_ctrl_r_session_rename,
    apply_ctrl_x,
    build_entries,
    is_orphaned_worktree,
    list_projects,
    parse_manual_sessions,
    remove_project_row,
    remove_session_row,
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


def _list_projects_pairs(
    *,
    projects_dir: Path,
    home: str,
    manual: str = "",
    strip_prefixes: list[str] | None = None,
    max_depth: int = 4,
) -> list[tuple[str, str]]:
    return [
        (name, str(path))
        for name, path in list_projects(
            [projects_dir],
            max_depth=max_depth,
            home=home,
            strip_prefixes=strip_prefixes or [],
            manual_spec=manual,
        )
    ]


def test_list_projects_emits_one_row_per_git_project(
    tmp_path: Path,
    make_repo: Callable[..., Path],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    bar = make_repo("projects/bar")

    pairs = _list_projects_pairs(projects_dir=projects_dir, home=str(tmp_path))

    paths = [path for _, path in pairs]
    assert str(foo) in paths
    assert str(bar) in paths


def test_list_projects_appends_manual_sessions(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()

    pairs = _list_projects_pairs(
        projects_dir=projects_dir,
        home=str(tmp_path),
        manual=f"dotfiles:{cfg}",
    )

    assert ("dotfiles", str(cfg)) in pairs


def test_list_projects_expands_tilde_in_manual_session_paths(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    pairs = _list_projects_pairs(
        projects_dir=projects_dir,
        home=str(tmp_path),
        manual="home:~/somewhere",
    )

    assert ("home", f"{tmp_path}/somewhere") in pairs


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
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
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
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    tmux_stub()
    tmpfile = tmp_path / "entries"
    before = "p\t/p/foo\tfoo\tfoo\n"
    tmpfile.write_text(before)

    rc = main(["sessions", "action", "ctrl-x", "p", "/p/foo", str(tmpfile)])
    assert rc == 0
    assert tmpfile.read_text() == before


def _build_entries_lines(
    *,
    projects_roots: list[Path],
    home: str,
    icon_style: str = "none",
    strip_prefixes: list[str] | None = None,
    manual_spec: str = "",
    max_depth: int = 4,
    score_entries: list[tuple[str, float, float]] | None = None,
    now: float = 0.0,
    half_life_secs: float = 14 * 24 * 3600,
    path_boost: float = 1.0,
) -> list[str]:
    return list(
        build_entries(
            home=home,
            strip_prefixes=strip_prefixes or [],
            projects_roots=projects_roots,
            max_depth=max_depth,
            manual_spec=manual_spec,
            icons=IconSet.from_style(icon_style),
            score_entries=score_entries or [],
            now=now,
            half_life_secs=half_life_secs,
            path_boost=path_boost,
        )
    )


def test_build_entries_project_only_ends_with_n_sentinel(
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    tmux_stub(sessions="")

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path), icon_style="ascii")

    assert any(line.startswith(f"p\t{foo}\t") for line in lines)
    assert lines[-1].startswith("n\t\tnew session\t")


def test_build_entries_pins_current_session_yellow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    tmux_stub(sessions="alpha\t$1\t/p/alpha")

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")
    assert "alpha" in lines[0]
    assert "(current)" in lines[0]


def test_build_entries_pins_previous_session_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TMUX_STUB_CURRENT", "alpha")
    monkeypatch.setenv("TMUX_STUB_PREV", "beta")
    tmux_stub(sessions="alpha\t$1\t/p/alpha\nbeta\t$2\t/p/beta")

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")
    assert "(current)" in lines[0]
    assert lines[1].startswith("s\t2\t")
    assert "(previous)" in lines[1]


def test_build_entries_remaining_sessions_ordered_by_last_attached_desc(
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

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path))

    assert lines[0].startswith("s\t1\t")  # alpha (current)
    assert lines[1].startswith("s\t2\t")  # beta (previous)
    assert lines[2].startswith("s\t4\t")  # delta last_attached=950
    assert lines[3].startswith("s\t5\t")  # epsilon last_attached=850
    assert lines[4].startswith("s\t3\t")  # gamma last_attached=800


def test_build_entries_filters_projects_matching_open_sessions(
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    from tmux_worktree_sessions.text import format_session_name

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    foo = make_repo("projects/foo")
    # The session is named after the project's format_session_name output;
    # tmux replaces dots with underscores so the comparison is dot-normalised.
    proj_name = format_session_name(str(foo), home=str(tmp_path), strip_prefixes=[])
    tmux_stub(sessions=f"{proj_name}\t$3\t{foo}")

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path))

    assert not any(line.startswith(f"p\t{foo}\t") for line in lines)
    assert any(proj_name in line for line in lines)


def test_build_entries_every_line_has_exactly_4_tsv_fields(
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

    lines = _build_entries_lines(projects_roots=[projects_dir], home=str(tmp_path))

    for line in lines:
        assert line.count("\t") == 3, f"bad line: {line!r}"


def test_apply_ctrl_r_session_rename_rewrites_search_and_display() -> None:
    icons = IconSet.from_style("none")
    lines = [
        "s\t3\told-name\told-display",
        "p\t/p/foo\tfoo\tfoo",
    ]
    out = apply_ctrl_r_session_rename(lines, sid="3", new_name="new-name", icons=icons)
    assert out[0].startswith("s\t3\tnew-name\t")
    assert "new-name" in out[0]
    assert out[1] == "p\t/p/foo\tfoo\tfoo"


def test_apply_ctrl_r_session_rename_no_match_returns_lines_unchanged() -> None:
    icons = IconSet.from_style("none")
    lines = ["p\t/p/foo\tfoo\tfoo"]
    out = apply_ctrl_r_session_rename(lines, sid="9", new_name="x", icons=icons)
    assert out == lines


def test_cli_action_ctrl_r_session_non_worktree_calls_tmux_rename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    plain = tmp_path / "plain"
    plain.mkdir()
    stub = tmux_stub(sessions=f"alpha\t$3\t{plain}")
    fzf_stub.respond("shiny new")  # type: ignore[attr-defined]
    tmpfile = tmp_path / "entries"
    tmpfile.write_text("s\t3\talpha\talpha\n")

    rc = main(["sessions", "action", "ctrl-r", "s", "3", str(tmpfile)])
    assert rc == 0

    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(inv[:4] == ["tmux", "rename-session", "-t", "$3"] and inv[4:] == ["shiny-new"] for inv in invocations), (
        invocations
    )


def test_cli_action_ctrl_r_project_non_worktree_displays_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    plain = tmp_path / "plain"
    plain.mkdir()
    stub = tmux_stub()
    tmpfile = tmp_path / "entries"
    tmpfile.write_text(f"p\t{plain}\tplain\tplain\n")

    rc = main(["sessions", "action", "ctrl-r", "p", str(plain), str(tmpfile)])
    assert rc == 0

    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(
        inv[:2] == ["tmux", "display-message"] and "ctrl-r: not a linked worktree" in inv for inv in invocations
    ), invocations


def test_remove_session_row_drops_matching_sid() -> None:
    lines = ["s\t3\talpha\talpha", "s\t4\tbeta\tbeta", "p\t/p/x\tx\tx"]
    assert remove_session_row(lines, sid="3") == ["s\t4\tbeta\tbeta", "p\t/p/x\tx\tx"]


def test_remove_session_row_no_match_returns_lines_unchanged() -> None:
    lines = ["p\t/p/x\tx\tx"]
    assert remove_session_row(lines, sid="9") == lines


def test_remove_project_row_drops_matching_path() -> None:
    lines = ["p\t/p/foo\tfoo\tfoo", "p\t/p/bar\tbar\tbar"]
    assert remove_project_row(lines, path="/p/foo") == ["p\t/p/bar\tbar\tbar"]


def _mkworktree(repo: Path, branch: str, path: Path) -> None:
    """Create a linked worktree at ``path`` checked out on ``branch``."""
    import subprocess as _sp

    has_branch = (
        _sp.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", branch],
            capture_output=True,
        ).returncode
        == 0
    )
    if has_branch:
        _sp.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", str(path), branch],
            check=True,
            capture_output=True,
        )
    else:
        _sp.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", "-b", branch, str(path)],
            check=True,
            capture_output=True,
        )


def test_cli_action_ctrl_d_session_with_worktree_kills_and_removes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    make_repo: Callable[..., Path],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    repo = make_repo("r", with_remote=True)
    wt = tmp_path / "wt" / "feature"
    _mkworktree(repo, "feature", wt)
    stub = tmux_stub(sessions=f"feature\t$5\t{wt}")
    tmpfile = tmp_path / "entries"
    tmpfile.write_text("s\t5\tfeature\tfeature\np\t/other/proj\tother\tother\n")

    rc = main(["sessions", "action", "ctrl-d", "s", "5", str(tmpfile)])
    assert rc == 0

    out = tmpfile.read_text()
    assert "s\t5\t" not in out
    assert "p\t/other/proj" in out
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(inv[:4] == ["tmux", "kill-session", "-t", "$5"] for inv in invocations), invocations
    assert not wt.exists()


def test_cli_action_ctrl_d_session_only_path_kills_and_strips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    plain = tmp_path / "plain"
    plain.mkdir()
    stub = tmux_stub(sessions=f"plain\t$7\t{plain}")
    tmpfile = tmp_path / "entries"
    tmpfile.write_text("s\t7\tplain\tplain\np\t/other/proj\tother\tother\n")

    rc = main(["sessions", "action", "ctrl-d", "s", "7", str(tmpfile)])
    assert rc == 0

    out = tmpfile.read_text()
    assert "s\t7\t" not in out
    assert "p\t/other/proj" in out
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(inv[:4] == ["tmux", "kill-session", "-t", "$7"] for inv in invocations), invocations


def test_cli_action_ctrl_d_project_linked_worktree_removes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    make_repo: Callable[..., Path],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    repo = make_repo("r", with_remote=True)
    wt = tmp_path / "wt" / "feature"
    _mkworktree(repo, "feature", wt)
    tmpfile = tmp_path / "entries"
    tmpfile.write_text(f"p\t{wt}\tfeature\tfeature\np\t/other/proj\tother\tother\n")

    rc = main(["sessions", "action", "ctrl-d", "p", str(wt), str(tmpfile)])
    assert rc == 0

    out = tmpfile.read_text()
    assert str(wt) not in out
    assert "/other/proj" in out
    assert not wt.exists()


def test_cli_action_ctrl_d_orphan_dir_yes_deletes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fzf_stub: object,
    make_repo: Callable[..., Path],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    make_repo("wt/realrepo")
    orphan = tmp_path / "wt" / "orphan"
    orphan.mkdir(parents=True)
    fzf_stub.respond("Yes")  # type: ignore[attr-defined]
    tmpfile = tmp_path / "entries"
    tmpfile.write_text(f"p\t{orphan}\torphan\torphan\np\t/other\tother\tother\n")

    rc = main(["sessions", "action", "ctrl-d", "p", str(orphan), str(tmpfile)])
    assert rc == 0

    out = tmpfile.read_text()
    assert str(orphan) not in out
    assert not orphan.exists()


def test_cli_action_ctrl_d_orphan_dir_no_keeps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fzf_stub: object,
    make_repo: Callable[..., Path],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    make_repo("wt/realrepo")
    orphan = tmp_path / "wt" / "orphan"
    orphan.mkdir(parents=True)
    fzf_stub.respond("No")  # type: ignore[attr-defined]
    tmpfile = tmp_path / "entries"
    tmpfile.write_text(f"p\t{orphan}\torphan\torphan\n")

    rc = main(["sessions", "action", "ctrl-d", "p", str(orphan), str(tmpfile)])
    assert rc == 0

    assert orphan.exists()
    assert str(orphan) in tmpfile.read_text()


def test_cli_action_ctrl_d_non_orphan_non_worktree_displays_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    notes = tmp_path / "lonely" / "notes"
    notes.mkdir(parents=True)
    stub = tmux_stub()
    tmpfile = tmp_path / "entries"
    tmpfile.write_text(f"p\t{notes}\tnotes\tnotes\n")

    rc = main(["sessions", "action", "ctrl-d", "p", str(notes), str(tmpfile)])
    assert rc == 0

    assert notes.exists()
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(
        inv[:2] == ["tmux", "display-message"] and "ctrl-d: not a linked worktree" in inv for inv in invocations
    ), invocations


def test_cli_display_name_returns_derived_when_normalises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TWS_STRIP_PREFIXES", "")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    rc = main(["sessions", "display-name", f"{tmp_path}/with.dot", "~/with_dot"])
    assert rc == 0
    assert stdout.getvalue() == "~/with.dot"


def test_cli_display_name_falls_back_to_raw_on_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TWS_STRIP_PREFIXES", "")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    rc = main(["sessions", "display-name", f"{tmp_path}/foo", "manual_name"])
    assert rc == 0
    assert stdout.getvalue() == "manual_name"


def test_cli_manage_invokes_fzf_with_popup_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    """Default invocation calls fzf with popup args; stub Esc → exit 0."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TWS_PROJECTS_DIRS", str(projects_dir))
    monkeypatch.setenv("TWS_MAX_DEPTH", "4")
    monkeypatch.setenv("TWS_STRIP_PREFIXES", "")
    monkeypatch.setenv("TWS_MANUAL_SESSIONS", "")
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    monkeypatch.setenv("TWS_SCORE_HALF_LIFE", "14")
    monkeypatch.setenv("TWS_SCORE_PATH_BOOST", "1.0")
    monkeypatch.setenv("SCORE_FILE", str(tmp_path / "scores.tsv"))
    tmux_stub(sessions="")
    fzf_stub.esc()  # type: ignore[attr-defined]

    rc = main(["sessions", "manage"])
    assert rc == 0

    invocations = fzf_stub.invocations()  # type: ignore[attr-defined]
    assert invocations, "fzf was not invoked"
    flat = [token for inv in invocations for token in inv]
    assert "--tmux" in flat
    assert "Sessions > " in flat
    # fzf must search the clean column (3) and display the decorated column (4)
    # so session rows aren't penalised for the "(current)/(previous)" suffix
    # under --scheme=path.
    assert "--with-nth" in flat and flat[flat.index("--with-nth") + 1] == "4"
    assert "--nth" in flat and flat[flat.index("--nth") + 1] == "3"
