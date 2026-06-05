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

    assert any(line.endswith("\t@ origin/server") for line in lines)
    assert any(line.endswith("\t- main") for line in lines)


def test_gen_branch_picker_entries_uses_local_icon_when_no_remote(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    icons = IconSet.from_style("ascii")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    branch_lines = [line for line in lines if not line.startswith("[new]\t")]
    assert all("\t- " in line for line in branch_lines)


def test_gen_branch_picker_entries_none_style_emits_no_separator(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    icons = IconSet.from_style("none")
    lines = list(gen_branch_picker_entries(repo, icons=icons))
    assert lines[0] == "[new]\tnew branch"
    assert any(line == "main\tmain" for line in lines)


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
