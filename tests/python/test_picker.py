"""Pure-layer tests for :mod:`tmux_worktree_sessions.picker`.

Uses the ``make_repo`` fixture so the underlying ``git.list_branches``
and ``git.resolve_remote`` calls run against real tmpdir repos, and
the ``fzf_stub`` fixture so ``pick_branch`` drives a scripted ``fzf``
binary on PATH.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from tmux_worktree_sessions.picker import (
    BranchChoice,
    IconSet,
    gen_branch_picker_entries,
    pick_branch,
)

from .conftest import FzfStub


def test_iconset_sep_is_space_when_icons_present() -> None:
    icons = IconSet.from_style("ascii")
    assert icons.sep == " "


def test_iconset_sep_is_empty_in_none_style() -> None:
    icons = IconSet.from_style("none")
    assert icons.sep == ""


def test_iconset_unknown_style_falls_back_to_nerd() -> None:
    fallback = IconSet.from_style("totally-unknown")
    nerd = IconSet.from_style("nerd")
    assert fallback == nerd


def test_gen_branch_picker_entries_lists_new_sentinel_first(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    icons = IconSet.from_style("ascii")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    assert lines[0] == "[new]\t+ new branch"


def test_gen_branch_picker_entries_marks_remote_only_with_remote_icon(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "update-ref",
            "refs/remotes/origin/server",
            main_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    icons = IconSet.from_style("ascii")
    lines = list(gen_branch_picker_entries(repo, icons=icons))

    # remote-only branches have no worktree, so no styling, no path suffix
    assert any(line.endswith("\t@ origin/server") for line in lines)
    # main has the repo as its worktree (no session here) → bold + gray path
    assert any(line.startswith("main\t\x1b[1m- main\x1b[0m \x1b[") for line in lines)


def test_gen_branch_picker_entries_uses_local_icon_when_no_remote(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    icons = IconSet.from_style("ascii")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    branch_lines = [line for line in lines if not line.startswith("[new]\t")]
    # All branches use the local icon ('-'). Main has a worktree → its
    # icon is wrapped in bold; feature has none → plain. Either way the
    # icon character itself is present after the tab.
    assert all("- " in line.split("\t", 1)[1] for line in branch_lines)


def test_gen_branch_picker_entries_none_style_emits_no_separator(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    assert lines[0] == "[new]\tnew branch"
    # main has a worktree (the repo itself), so its line is bold-wrapped
    # and carries the gray worktree path.
    main_line = next(line for line in lines if line.startswith("main\t"))
    assert main_line.startswith("main\t\x1b[1mmain\x1b[0m ")
    assert str(repo) in main_line


def test_gen_branch_picker_entries_appends_worktree_path_in_gray(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    feature_path = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
    )

    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))

    feature_line = next(line for line in lines if line.startswith("feature\t"))
    # gray SGR + path + reset
    assert "\x1b[38;2;108;112;134m" in feature_line
    assert str(feature_path) in feature_line
    assert "\x1b[0m" in feature_line


def test_gen_branch_picker_entries_no_worktree_no_suffix(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    # `feature` has no worktree → its line has no gray suffix.
    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))

    feature_line = next(line for line in lines if line.startswith("feature\t"))
    assert feature_line == "feature\tfeature"


def test_gen_branch_picker_entries_session_branch_is_green(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    feature_path = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
    )
    icons = IconSet.from_style("none")
    lines = list(
        gen_branch_picker_entries(
            repo,
            icons=icons,
            session_paths=frozenset({feature_path}),
        )
    )
    feature_line = next(line for line in lines if line.startswith("feature\t"))
    # green SGR (matching session picker active sessions) wraps the label,
    # then a reset, then the gray worktree path.
    assert feature_line.startswith("feature\t\x1b[38;2;166;227;161mfeature\x1b[0m ")


def test_gen_branch_picker_entries_worktree_branch_is_bold_not_green(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    feature_path = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
    )
    icons = IconSet.from_style("none")
    # No session_paths → branch has worktree but no session, expect bold.
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    feature_line = next(line for line in lines if line.startswith("feature\t"))
    assert feature_line.startswith("feature\t\x1b[1mfeature\x1b[0m ")
    assert "\x1b[38;2;166;227;161m" not in feature_line  # not green


def test_gen_branch_picker_entries_plain_branch_has_no_label_styling(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    # `feature` has no worktree → no SGR styling on the label, no suffix.
    feature_line = next(line for line in lines if line.startswith("feature\t"))
    assert feature_line == "feature\tfeature"


def test_gen_branch_picker_entries_groups_sessions_then_worktrees_then_locals_then_remotes(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    """Ordering must surface what the user is most likely to act on:
    sessions first, then worktrees without sessions, then plain local
    branches, then remote-only branches."""
    repo = make_repo(
        "r",
        branches=("main", "session-branch", "worktree-branch", "plain-branch"),
        with_remote=True,
    )
    # session-branch: has a worktree AND we'll claim it has an open session
    sess_wt = tmp_path / "wt-session"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(sess_wt), "session-branch"],
        check=True,
        capture_output=True,
    )
    # worktree-branch: has a worktree but no session
    plain_wt = tmp_path / "wt-plain"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(plain_wt), "worktree-branch"],
        check=True,
        capture_output=True,
    )
    # remote-only branch: create a remote ref with no local counterpart
    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/server-only", main_sha],
        check=True,
        capture_output=True,
    )

    icons = IconSet.from_style("none")
    lines = list(
        gen_branch_picker_entries(
            repo,
            icons=icons,
            session_paths=frozenset({sess_wt, repo}),
        )
    )
    # drop the [new] sentinel; we only assert ordering across branch rows
    branches = [line.split("\t", 1)[0] for line in lines if not line.startswith("[new]\t")]

    sess_idx = branches.index("session-branch")
    main_idx = branches.index("main")  # main also has a session (repo path)
    wt_idx = branches.index("worktree-branch")
    plain_idx = branches.index("plain-branch")
    remote_idx = branches.index("origin/server-only")

    # sessions group is strictly before worktrees group, etc.
    assert max(sess_idx, main_idx) < wt_idx
    assert wt_idx < plain_idx
    assert plain_idx < remote_idx


def test_gen_branch_picker_entries_no_sessions_groups_worktrees_first(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    """With an empty session_paths set, branches with worktrees still
    sort ahead of branches without."""
    repo = make_repo("r", branches=("main", "feature", "untouched"))
    feature_path = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
    )

    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    branches = [line.split("\t", 1)[0] for line in lines if not line.startswith("[new]\t")]

    feature_idx = branches.index("feature")
    untouched_idx = branches.index("untouched")
    assert feature_idx < untouched_idx


def test_gen_branch_picker_entries_applies_strip_prefixes_to_path(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    # The main worktree's path begins with the parent tmp dir; stripping
    # that prefix should leave only the basename in the gray suffix.
    icons = IconSet.from_style("none")
    parent = str(repo.parent)
    lines = list(gen_branch_picker_entries(repo, icons=icons, strip_prefixes=[parent]))

    main_line = next(line for line in lines if line.startswith("main\t"))
    # original tmp path is gone, only the bare repo name remains
    assert parent not in main_line
    assert repo.name in main_line


# ── pick_branch ──────────────────────────────────────────────────────────────


def _make_fresh_fetch_head(repo: Path) -> None:
    """Touch FETCH_HEAD so ``fetch_is_stale`` returns False in tests."""
    common_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common = Path(common_dir)
    if not common.is_absolute():
        common = repo / common
    (common / "FETCH_HEAD").touch()


def _pick_branch_args(repo: Path) -> dict[str, object]:
    return {
        "icons": IconSet.from_style("ascii"),
        "fetch_reload_argv": ["/bin/true"],
        "listen_port": 12345,
        "now": 0.0,
        "fetch_window_secs": 900,
    }


def test_pick_branch_ctrl_bs_returns_back(
    make_repo: Callable[..., Path],
    fzf_stub: FzfStub,
) -> None:
    repo = make_repo("r", with_remote=True)
    _make_fresh_fetch_head(repo)
    fzf_stub.respond("ctrl-bs\n")
    result = pick_branch(repo, **_pick_branch_args(repo))  # type: ignore[arg-type]
    assert result == BranchChoice(kind="back")


def test_pick_branch_invokes_fzf_with_ansi_flag(
    make_repo: Callable[..., Path],
    fzf_stub: FzfStub,
) -> None:
    """The gray-path suffix on branches with worktrees uses SGR codes,
    so the picker must enable ANSI parsing. Otherwise the codes leak
    visibly into the rendered output."""
    repo = make_repo("r", with_remote=True)
    _make_fresh_fetch_head(repo)
    fzf_stub.esc()
    pick_branch(repo, **_pick_branch_args(repo))  # type: ignore[arg-type]

    flat = [token for inv in fzf_stub.invocations() for token in inv]
    assert "--ansi" in flat


def test_pick_branch_esc_returns_cancel(
    make_repo: Callable[..., Path],
    fzf_stub: FzfStub,
) -> None:
    repo = make_repo("r", with_remote=True)
    _make_fresh_fetch_head(repo)
    fzf_stub.esc()
    result = pick_branch(repo, **_pick_branch_args(repo))  # type: ignore[arg-type]
    assert result == BranchChoice(kind="cancel")


def test_pick_branch_existing_branch_returns_existing(
    make_repo: Callable[..., Path],
    fzf_stub: FzfStub,
) -> None:
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    _make_fresh_fetch_head(repo)
    fzf_stub.respond("\nfeature\t- feature")
    result = pick_branch(repo, **_pick_branch_args(repo))  # type: ignore[arg-type]
    assert result == BranchChoice(kind="existing", name="feature")


def test_pick_branch_new_then_name_returns_new(
    make_repo: Callable[..., Path],
    fzf_stub: FzfStub,
) -> None:
    repo = make_repo("r", with_remote=True)
    _make_fresh_fetch_head(repo)
    # First fzf call: pick "[new]". Empty key (Enter) followed by the
    # selected line (cut -f1 → "[new]").
    fzf_stub.respond("\n[new]\t+ new branch")
    # Second fzf call: --print-query --expect "ctrl-bs". Line 1 = query,
    # line 2 = the expect-key (empty here = Enter).
    fzf_stub.respond("shiny")
    result = pick_branch(repo, **_pick_branch_args(repo))  # type: ignore[arg-type]
    assert result == BranchChoice(kind="new", name="shiny")
