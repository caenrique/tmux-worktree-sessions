"""Tests for :mod:`tmux_worktree_sessions.fzf`.

Exercises the ``run`` wrapper plus the cancellation helper. The fzf
stub at ``tests/python/_stubs/fzf`` is loaded via the ``fzf_stub``
fixture and lets each test queue canned ``stdout`` / ``returncode``
responses.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from tmux_worktree_sessions import fzf

from .conftest import FzfStub


def test_run_returns_stdout_and_returncode(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("alpha\nbeta", exit_code=0)
    result = fzf.run("--prompt", "P > ")
    assert result.returncode == 0
    assert result.stdout.startswith("alpha")
    assert result.cancelled is False


def test_run_cancelled_property_matches_exit_130(fzf_stub: FzfStub) -> None:
    fzf_stub.esc()
    result = fzf.run("--prompt", "P > ")
    assert result.cancelled is True
    assert result.returncode == fzf.EXIT_CANCELLED


def test_run_passes_text_input_through_stdin(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("Yes", exit_code=0)
    fzf.run("--prompt", "ok? ", input="No\nYes")
    seen = fzf_stub.stdin_log.read_text()
    assert "No" in seen and "Yes" in seen


def test_run_passes_binary_stdin_through_to_fzf(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("first\n", exit_code=0)
    payload = tmp_path / "rows.txt"
    payload.write_bytes(b"first\nsecond\n")
    with payload.open("rb") as f:
        fzf.run("--prompt", "P > ", stdin=f)
    seen = fzf_stub.stdin_log.read_text()
    assert "first" in seen and "second" in seen


def test_run_rejects_both_input_and_stdin(fzf_stub: FzfStub) -> None:
    payload = io.BytesIO(b"x")
    with pytest.raises(ValueError, match="either input= or stdin="):
        fzf.run("--prompt", "P > ", input="y", stdin=payload)


def test_inline_flags_are_a_subset_of_popup_flags() -> None:
    # The popup flag tuple wraps INLINE_FLAGS verbatim plus the popup
    # framing options — keeping that contract makes "popup is inline +
    # window chrome" obvious to callers.
    for flag in fzf.INLINE_FLAGS:
        assert flag in fzf.POPUP_FLAGS
    assert "--tmux" in fzf.POPUP_FLAGS


def test_prompt_returns_typed_query(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("alpha\n", exit_code=0)
    result = fzf.prompt(prompt_label="P > ", header="enter:ok  ctrl-bs:cancel")
    assert result.cancelled is False
    assert result.query == "alpha"
    assert result.cancel_key == ""


def test_prompt_with_initial_passes_query_flag(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("alpha\n", exit_code=0)
    fzf.prompt(prompt_label="P > ", header="ok", initial="alpha")
    last_call = fzf_stub.invocations()[-1]
    assert "--query" in last_call
    assert "alpha" in last_call


def test_prompt_without_initial_omits_query_flag(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("\n", exit_code=0)
    fzf.prompt(prompt_label="P > ", header="ok")
    last_call = fzf_stub.invocations()[-1]
    assert "--query" not in last_call


def test_prompt_esc_marks_cancelled_without_cancel_key(fzf_stub: FzfStub) -> None:
    fzf_stub.esc()
    result = fzf.prompt(prompt_label="P > ", header="ok")
    assert result.cancelled is True
    assert result.cancel_key == ""


def test_prompt_cancel_key_is_distinct_from_esc(fzf_stub: FzfStub) -> None:
    # fzf prints the query on line 0 and the expect-key on line 1 when
    # the user presses ctrl-bs; that path should mark cancelled with
    # the key recorded so callers can distinguish from Esc.
    fzf_stub.respond("\nctrl-bs", exit_code=0)
    result = fzf.prompt(prompt_label="P > ", header="ok")
    assert result.cancelled is True
    assert result.cancel_key == "ctrl-bs"


def test_prompt_inline_uses_inline_flags(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("alpha\n", exit_code=0)
    fzf.prompt(prompt_label="P > ", header="ok", popup=False)
    last_call = fzf_stub.invocations()[-1]
    # POPUP_FLAGS adds --tmux; inline mode must NOT include it.
    assert "--tmux" not in last_call


def test_prompt_popup_uses_popup_flags(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("alpha\n", exit_code=0)
    fzf.prompt(prompt_label="P > ", header="ok", popup=True)
    last_call = fzf_stub.invocations()[-1]
    assert "--tmux" in last_call


def test_confirm_returns_true_on_yes(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("Yes\n", exit_code=0)
    assert fzf.confirm(prompt_label="ok? ", header="really?") is True


def test_confirm_returns_false_on_no(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("No\n", exit_code=0)
    assert fzf.confirm(prompt_label="ok? ", header="really?") is False


def test_confirm_returns_false_on_esc(fzf_stub: FzfStub) -> None:
    fzf_stub.esc()
    assert fzf.confirm(prompt_label="ok? ", header="really?") is False


def test_confirm_pipes_no_then_yes_choices(fzf_stub: FzfStub) -> None:
    fzf_stub.respond("No\n", exit_code=0)
    fzf.confirm(prompt_label="ok? ", header="really?")
    seen = fzf_stub.stdin_log.read_text()
    no_pos = seen.find("No")
    yes_pos = seen.find("Yes")
    assert no_pos != -1 and yes_pos != -1
    assert no_pos < yes_pos


def test_picker_run_returns_selection(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("\nrow-1\trest", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"row-1\trest\nrow-2\tother\n")
    p = fzf.Picker(prompt_label="Pick > ", header="enter:ok", expect="ctrl-w")
    with payload.open("rb") as f:
        selection = p.run(stdin=f)
    assert selection.cancelled is False
    assert selection.key == ""  # plain Enter
    assert selection.line == "row-1\trest"


def test_picker_run_records_expect_key(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("ctrl-w\nrow-1\tx", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"row-1\tx\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok", expect="ctrl-w,ctrl-bs")
    with payload.open("rb") as f:
        selection = p.run(stdin=f)
    assert selection.key == "ctrl-w"
    assert selection.line == "row-1\tx"


def test_picker_run_marks_cancelled_on_esc(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.esc()
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"row-1\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok")
    with payload.open("rb") as f:
        selection = p.run(stdin=f)
    assert selection.cancelled is True


def test_picker_argv_includes_listen_when_set(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("\nfirst", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"first\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok", listen_port=51234)
    with payload.open("rb") as f:
        p.run(stdin=f)
    last_call = fzf_stub.invocations()[-1]
    assert "--listen" in last_call
    assert "51234" in last_call


def test_picker_argv_omits_listen_by_default(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("\nfirst", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"first\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok")
    with payload.open("rb") as f:
        p.run(stdin=f)
    assert "--listen" not in fzf_stub.invocations()[-1]


def test_picker_bind_chains_appends_to_argv(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("\nfirst", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"first\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok").bind("?:toggle-preview").bind("ctrl-r:execute-silent(echo)")
    with payload.open("rb") as f:
        p.run(stdin=f)
    last_call = fzf_stub.invocations()[-1]
    assert "?:toggle-preview" in last_call
    assert "ctrl-r:execute-silent(echo)" in last_call
    # Both binds must arrive as separate `--bind` flags.
    assert last_call.count("--bind") >= 2


def test_picker_preview_window_only_set_when_provided(fzf_stub: FzfStub, tmp_path: Path) -> None:
    fzf_stub.respond("\nfirst", exit_code=0)
    payload = tmp_path / "rows.tsv"
    payload.write_bytes(b"first\n")
    p = fzf.Picker(prompt_label="Pick > ", header="ok")
    with payload.open("rb") as f:
        p.run(stdin=f)
    last_call = fzf_stub.invocations()[-1]
    assert "--preview" not in last_call
    assert "--preview-window" not in last_call
