"""Pure-layer tests for :mod:`tmux_sessions.picker`.

Mirrors the bats coverage in ``tests/common.bats`` for
``_gen_branch_picker_entries``. Uses the ``make_repo`` fixture so the
underlying ``git.list_branches`` / ``git.resolve_remote`` calls run
against real tmpdir repos.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from tmux_sessions.picker import IconSet, gen_branch_picker_entries


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
