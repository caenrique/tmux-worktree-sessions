"""Tests for :mod:`tmux_worktree_sessions.sessions`.

Pure-layer cases for ``parse_manual_sessions``, ``list_projects``,
``build_entries``, and the action-row rewrites; CLI-layer cases for
the production action subcommands (``ctrl-x``, ``ctrl-r``) plus
``display-name`` and ``manage`` exercise ``main(...)`` end-to-end.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_worktree_sessions.__main__ import main
from tmux_worktree_sessions.icons import IconSet
from tmux_worktree_sessions.sessions import (
    apply_ctrl_r_session_rename,
    apply_ctrl_x,
    build_entries,
    expand_subfolder_worktrees,
    list_projects,
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


def test_expand_subfolder_worktrees_returns_children_with_dotgit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sub = repo / ".worktrees"
    sub.mkdir(parents=True)
    feature = sub / "feature"
    feature.mkdir()
    (feature / ".git").write_text("gitdir: /elsewhere\n")
    fix = sub / "fix"
    fix.mkdir()
    (fix / ".git").mkdir()

    result = expand_subfolder_worktrees(repo, worktrees_dir=".worktrees")

    assert set(result) == {feature, fix}


def test_expand_subfolder_worktrees_skips_children_without_dotgit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sub = repo / ".worktrees"
    sub.mkdir(parents=True)
    real = sub / "real"
    real.mkdir()
    (real / ".git").write_text("gitdir: /elsewhere\n")
    stale = sub / "stale"
    stale.mkdir()  # no .git

    result = expand_subfolder_worktrees(repo, worktrees_dir=".worktrees")

    assert result == [real]


def test_expand_subfolder_worktrees_missing_dir_returns_empty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert expand_subfolder_worktrees(repo, worktrees_dir=".worktrees") == []


def test_expand_subfolder_worktrees_honours_custom_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sub = repo / "trees"
    sub.mkdir(parents=True)
    feature = sub / "feature"
    feature.mkdir()
    (feature / ".git").write_text("gitdir: /elsewhere\n")

    assert expand_subfolder_worktrees(repo, worktrees_dir="trees") == [feature]
    # The same repo with a different worktrees_dir finds nothing.
    assert expand_subfolder_worktrees(repo, worktrees_dir=".worktrees") == []


def _list_projects_pairs(
    *,
    projects_dir: Path,
    home: str,
    manual: str = "",
    strip_prefixes: list[str] | None = None,
    max_depth: int = 4,
    worktrees_dir: str = ".worktrees",
) -> list[tuple[str, str]]:
    return [
        (name, str(path))
        for name, path in list_projects(
            [projects_dir],
            max_depth=max_depth,
            home=home,
            strip_prefixes=strip_prefixes or [],
            manual_spec=manual,
            worktrees_dir=worktrees_dir,
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


def test_list_projects_surfaces_subfolder_layout_worktrees(
    tmp_path: Path,
    make_repo: Callable[..., Path],
    worktree_add: Callable[..., None],
) -> None:
    """Subfolder-layout linked worktrees are pruned by ``fd``; ``list_projects``
    must still surface them by enumerating ``git worktree list`` per repo."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    repo = make_repo("projects/foo")
    feature = repo / ".worktrees" / "feature"
    worktree_add(repo, feature, "feature", new_branch=True)

    pairs = _list_projects_pairs(projects_dir=projects_dir, home=str(tmp_path))

    paths = [path for _, path in pairs]
    assert str(repo) in paths
    assert str(feature) in paths


def test_list_projects_sibling_layout_emits_each_worktree_once(
    tmp_path: Path,
    make_repo: Callable[..., Path],
    worktree_add: Callable[..., None],
) -> None:
    """Sibling-layout repos: ``fd`` finds every worktree directory directly
    via its own ``.git`` entry, so each appears as its own row exactly once
    without any extra enumeration."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    container = projects_dir / "repo"
    container.mkdir()
    repo = make_repo("projects/repo/main")
    feature = container / "feature"
    worktree_add(repo, feature, "feature", new_branch=True)

    pairs = _list_projects_pairs(projects_dir=projects_dir, home=str(tmp_path), max_depth=6)

    paths = [path for _, path in pairs]
    assert paths.count(str(repo)) == 1
    assert paths.count(str(feature)) == 1


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
    cli_env: Path,
    tmux_stub: Callable[..., object],
    entries_file: Callable[[str], Path],
) -> None:
    tmux_stub(sessions="alpha\t$3\t/p/alpha")
    tmpfile = entries_file("s\t3\talpha\talpha\np\t/p/other\tother\tother\nn\t\tnew session\tnew session\n")

    rc = main(["_internal", "session-action", "ctrl-x", "s", "3", str(tmpfile)])
    assert rc == 0

    assert tmpfile.read_text().splitlines() == [
        "p\t/p/other\tother\tother",
        "p\t/p/alpha\talpha\talpha",
        "n\t\tnew session\tnew session",
    ]


def test_cli_action_ctrl_x_non_session_is_noop(
    cli_env: Path,
    tmux_stub: Callable[..., object],
    entries_file: Callable[[str], Path],
) -> None:
    tmux_stub()
    before = "p\t/p/foo\tfoo\tfoo\n"
    tmpfile = entries_file(before)

    rc = main(["_internal", "session-action", "ctrl-x", "p", "/p/foo", str(tmpfile)])
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
    worktrees_dir: str = ".worktrees",
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
            worktrees_dir=worktrees_dir,
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
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
    entries_file: Callable[[str], Path],
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    stub = tmux_stub(sessions=f"alpha\t$3\t{plain}")
    fzf_stub.respond("shiny new")  # type: ignore[attr-defined]
    tmpfile = entries_file("s\t3\talpha\talpha\n")

    rc = main(["_internal", "session-action", "ctrl-r", "s", "3", str(tmpfile)])
    assert rc == 0

    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(inv[:4] == ["tmux", "rename-session", "-t", "$3"] and inv[4:] == ["shiny-new"] for inv in invocations), (
        invocations
    )


def test_cli_action_ctrl_r_project_non_worktree_displays_warning(
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    entries_file: Callable[[str], Path],
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    stub = tmux_stub()
    tmpfile = entries_file(f"p\t{plain}\tplain\tplain\n")

    rc = main(["_internal", "session-action", "ctrl-r", "p", str(plain), str(tmpfile)])
    assert rc == 0

    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(
        inv[:2] == ["tmux", "display-message"] and "ctrl-r: not a linked worktree" in inv for inv in invocations
    ), invocations


@pytest.mark.parametrize(
    ("name_arg", "expected"),
    [
        # tmux-stored name normalises back to the derived dotted form
        ("~/with_dot", "~/with.dot"),
        # tmux-stored name does NOT round-trip → emit the raw stored name
        ("manual_name", "manual_name"),
    ],
)
def test_cli_display_name(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    name_arg: str,
    expected: str,
) -> None:
    monkeypatch.setenv("TWS_STRIP_PREFIXES", "")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    path_arg = f"{tmp_path}/with.dot" if "with" in name_arg else f"{tmp_path}/foo"
    rc = main(["sessions", "display-name", path_arg, name_arg])
    assert rc == 0
    assert stdout.getvalue() == expected


def test_cli_worktree_manage_outside_repo_displays_message(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
) -> None:
    monkeypatch.setenv("TMUX_STUB_PANE_PATH", str(tmp_path))
    stub = tmux_stub()

    rc = main(["worktree", "manage"])

    assert rc == 0
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(inv[:2] == ["tmux", "display-message"] and "worktree: not a git repo" in inv for inv in invocations), (
        invocations
    )


def test_cli_worktree_manage_in_repo_invokes_branch_picker(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
    make_repo: Callable[..., Path],
    touch_fetch_head: Callable[[Path], None],
) -> None:
    """Standalone `worktree manage` resolves the pane's repo and drives
    `pick_branch`. Stubbed fzf returns Esc → exit 0 without any picks."""
    repo = make_repo("r", with_remote=True)
    touch_fetch_head(repo)  # don't spawn the stale-fetch background helper
    monkeypatch.setenv("TMUX_STUB_PANE_PATH", str(repo))
    tmux_stub()
    fzf_stub.esc()  # type: ignore[attr-defined]

    rc = main(["worktree", "manage"])
    assert rc == 0

    invocations = fzf_stub.invocations()  # type: ignore[attr-defined]
    assert invocations, "fzf was not invoked"
    flat = [token for inv in invocations for token in inv]
    assert "Branch > " in flat


def test_cli_manage_invokes_fzf_with_popup_args(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    """Default invocation calls fzf with popup args; stub Esc → exit 0."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TWS_PROJECTS_DIRS", str(projects_dir))
    tmux_stub(sessions="")
    fzf_stub.esc()  # type: ignore[attr-defined]

    rc = main(["sessions", "manage"])
    assert rc == 0

    invocations = fzf_stub.invocations()  # type: ignore[attr-defined]
    assert invocations, "fzf was not invoked"
    flat = [token for inv in invocations for token in inv]
    assert "--tmux" in flat
    assert "Sessions > " in flat
    # `--with-nth 4` shows the decorated column. We deliberately do NOT pair it
    # with `--nth`: fzf indexes `--nth` into the post-`--with-nth` view, so
    # `--nth 3` matches zero rows once the view collapses to a single field.
    assert "--with-nth" in flat and flat[flat.index("--with-nth") + 1] == "4"
    assert "--nth" not in flat
    # Preview must use single-quoted `'$'` (not `'\$'`) so the shell passes
    # `$<sid>` through to tmux. With backslash escaping, tmux rejects
    # `\$<sid>` with "can't find pane".
    preview_idx = flat.index("--preview")
    assert "'$'{2}" in flat[preview_idx + 1]
    assert "'\\$'" not in flat[preview_idx + 1]


# ── End-to-end ``sessions manage`` enter-on-row flows ─────────────────────────
#
# Drive the full picker dispatcher with a stubbed fzf so the
# ``run_session_picker`` → ``_dispatch_session_selection`` → bump+switch
# path is exercised. fzf's ``--expect`` mode prints two lines: line 1 is
# the expect-key (empty for Enter), line 2 is the selected row's TSV.


def test_cli_manage_enter_on_project_creates_session_and_bumps_score(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    """Enter on a ``p`` row: tmux starts the session and the score file
    records the bump. Exercises ``bump_score_and_switch`` end-to-end."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TWS_PROJECTS_DIRS", str(projects_dir))
    stub = tmux_stub(sessions="", new_id="$42")
    # Picker returns Enter (empty key) on a project row.
    fzf_stub.respond("\np\t/p/foo\tfoo\tfoo")  # type: ignore[attr-defined]

    rc = main(["sessions", "manage"])
    assert rc == 0

    assert cli_env.is_file()
    assert "foo" in cli_env.read_text()  # score row written
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(call[1:2] == ["new-session"] for call in invocations), invocations
    assert any(call[:4] == ["tmux", "switch-client", "-t", "$42"] for call in invocations), invocations


def test_cli_manage_enter_on_session_switches_client(
    cli_env: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    """Enter on an ``s`` row maps directly to ``tmux switch-client -t $sid``."""
    stub = tmux_stub(sessions="alpha\t$3\t/p/alpha")
    fzf_stub.respond("\ns\t3\talpha\talpha")  # type: ignore[attr-defined]

    rc = main(["sessions", "manage"])
    assert rc == 0

    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(call[:4] == ["tmux", "switch-client", "-t", "$3"] for call in invocations), invocations


def test_cli_manage_enter_on_new_sentinel_prompts_for_name_and_creates(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
) -> None:
    """Enter on the ``n`` sentinel calls ``prompt_new_session_name``
    (a second fzf call) then bumps + switches into the typed name."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TWS_PROJECTS_DIRS", str(projects_dir))
    stub = tmux_stub(sessions="", new_id="$77")
    # Call 1: picker → Enter on the new-session sentinel.
    fzf_stub.respond("\nn\t\tnew session\tnew session")  # type: ignore[attr-defined]
    # Call 2: name prompt → returns the typed query then a blank expect-key
    # line (fzf prints two lines under ``--print-query --expect ctrl-bs``).
    fzf_stub.respond("shiny\n")  # type: ignore[attr-defined]

    rc = main(["sessions", "manage"])
    assert rc == 0

    assert "shiny" in cli_env.read_text()
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(call[1:6] == ["new-session", "-c", str(tmp_path), "-s", "shiny"] for call in invocations), invocations


def test_cli_worktree_manage_existing_branch_creates_worktree_and_switches(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
    make_repo: Callable[..., Path],
    touch_fetch_head: Callable[[Path], None],
) -> None:
    """Picking an existing branch in the worktree picker creates a real
    linked worktree and switches into it. Covers ``open_worktree_picker``,
    ``_add_worktree_for_choice``, and ``bump_score_and_switch``."""
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    touch_fetch_head(repo)
    monkeypatch.setenv("TMUX_STUB_PANE_PATH", str(repo))
    stub = tmux_stub(sessions="", new_id="$88")
    # pick_branch's picker returns Enter on the "feature" row. Field 0 is
    # the branch name; the rest of the line is ignored by the dispatcher.
    fzf_stub.respond("\nfeature\trest")  # type: ignore[attr-defined]

    rc = main(["worktree", "manage"])
    assert rc == 0

    # Worktree was created under the configured subfolder layout.
    assert (repo / ".worktrees" / "feature").is_dir()
    invocations = stub.invocations()  # type: ignore[attr-defined]
    assert any(call[1:2] == ["new-session"] for call in invocations), invocations
    assert any(call[:4] == ["tmux", "switch-client", "-t", "$88"] for call in invocations), invocations


def test_cli_action_ctrl_r_worktree_renames_branch_and_rebuilds_tmpfile(
    monkeypatch: pytest.MonkeyPatch,
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., object],
    fzf_stub: object,
    make_repo: Callable[..., Path],
    worktree_add: Callable[..., None],
    entries_file: Callable[[str], Path],
) -> None:
    """ctrl-r on a project row that IS a linked worktree renames the
    branch + directory + repairs git, then rewrites the tmpfile from
    ``build_session_entries_iter``. Covers ``_rename_worktree_action``."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setenv("TWS_PROJECTS_DIRS", str(projects_dir))
    repo = make_repo("projects/repo", with_remote=True)
    feature_path = repo / ".worktrees" / "feature"
    worktree_add(repo, feature_path, "feature", new_branch=True)
    tmux_stub()
    fzf_stub.respond("renamed\n")  # type: ignore[attr-defined]
    tmpfile = entries_file(f"p\t{feature_path}\tfeature\tfeature\n")

    rc = main(["_internal", "session-action", "ctrl-r", "p", str(feature_path), str(tmpfile)])
    assert rc == 0

    # The branch+directory was actually renamed on disk.
    assert not feature_path.exists()
    assert (repo / ".worktrees" / "renamed").is_dir()
    # The tmpfile was rebuilt — the old row is gone.
    assert "feature" not in tmpfile.read_text() or "renamed" in tmpfile.read_text()


# ── Dispatcher edge cases ─────────────────────────────────────────────────────


def test_main_no_command_returns_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    """``main([])`` lands on a parser with no handler → prints usage, exits 1."""
    rc = main([])
    assert rc == 1
    assert "usage" in capsys.readouterr().err.lower()
