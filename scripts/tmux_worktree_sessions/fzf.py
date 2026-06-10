"""fzf subprocess wrappers for tmux-worktree-sessions.

Mirrors the structure of :mod:`tmux_worktree_sessions.git` and
:mod:`tmux_worktree_sessions.tmux`: every spawn of an ``fzf`` process in
the codebase goes through this module.

The high-level helpers below hide the boilerplate flag soup — callers
say "ask the user for a name" or "open the session picker", not "build
a list of 25 fzf flags". The low-level :func:`run` escape hatch stays
exported for cases that genuinely need bespoke flag composition.

Style tuples:

* :data:`INLINE_FLAGS` — base style for inline prompts (rename, confirm)
  that run inside an outer fzf ``execute`` callback.
* :data:`POPUP_FLAGS` — adds the ``--tmux`` popup flag and
  ``--scheme=path`` for top-level pickers.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import IO

INLINE_FLAGS: tuple[str, ...] = (
    "--reverse",
    "--no-scrollbar",
    "--no-info",
    "--no-separator",
    "--no-border",
    "--color",
    "header:#6c7086",
)

POPUP_FLAGS: tuple[str, ...] = (
    "--tmux",
    "bottom,100%,100%",
    "--scheme=path",
    *INLINE_FLAGS,
)

# fzf's documented exit code when the user cancels with Esc / ctrl-c.
EXIT_CANCELLED = 130

# Standard ctrl-bs cancel header used across all single-line prompts so
# the keybind hint stays consistent.
_DEFAULT_CANCEL_KEY = "ctrl-bs"


@dataclass(frozen=True)
class FzfResult:
    """Outcome of one ``fzf`` invocation.

    ``stdout`` is the captured text, ``returncode`` matches fzf's exit
    status. ``cancelled`` is the canonical "user pressed Esc" check —
    callers should consult it before parsing ``stdout``.
    """

    returncode: int
    stdout: str

    @property
    def cancelled(self) -> bool:
        return self.returncode == EXIT_CANCELLED


@dataclass(frozen=True)
class PromptResult:
    """Outcome of a single-line :func:`prompt` call.

    ``query`` is the text the user typed (or ``""`` on cancel).
    ``cancelled`` is True when the user pressed Esc or the cancel key.
    ``cancel_key`` distinguishes the two: empty for Esc / no cancel,
    the literal key name (e.g. ``"ctrl-bs"``) when the user pressed
    the configured cancel binding. Callers that need different
    behaviour for "abort" vs "go back" can check ``cancel_key``.
    """

    query: str
    cancelled: bool
    cancel_key: str = ""


@dataclass(frozen=True)
class PickerSelection:
    """One row picked by :meth:`Picker.run`.

    ``key`` is the special key fzf records via ``--expect`` (empty
    string for plain Enter). ``line`` is the raw selected row before
    any TSV parsing. ``cancelled`` is True when the user pressed Esc
    and there is no selection to act on.
    """

    key: str
    line: str
    cancelled: bool


def run(
    *args: str,
    input: str | None = None,
    stdin: IO[bytes] | None = None,
) -> FzfResult:
    """Invoke ``fzf`` with ``args``; return the captured result.

    Low-level escape hatch. Most callers should use :func:`prompt`,
    :func:`confirm`, or :class:`Picker` instead — they hide the
    repeating flag soup and surface a typed result.

    Pass ``input`` for text-mode stdin (used by inline prompts that pipe
    a fixed list like ``"No\\nYes"``) or ``stdin`` for an already-open
    binary file handle. Exactly one or neither should be supplied —
    passing both is a programming error.
    """
    if input is not None and stdin is not None:
        raise ValueError("fzf.run: pass either input= or stdin=, not both")
    result = subprocess.run(
        ["fzf", *args],
        input=input,
        stdin=stdin,
        capture_output=True,
        text=True,
    )
    return FzfResult(returncode=result.returncode, stdout=result.stdout)


def prompt(
    *,
    prompt_label: str,
    header: str,
    initial: str = "",
    popup: bool = True,
) -> PromptResult:
    """Drive a free-text single-line fzf prompt; return the typed query.

    Used wherever the plugin asks the user to type a name (rename,
    new-session, new-branch). The helper owns:

    * the boilerplate flag set (``--print-query``, ``--no-select-1``,
      ``--expect ctrl-bs`` — all the same in every call site),
    * choosing :data:`INLINE_FLAGS` vs :data:`POPUP_FLAGS` based on the
      ``popup`` argument,
    * mapping Esc, ctrl-bs, and empty input to ``cancelled=True``.

    Callers only supply the prompt label, the header text, and the
    optional prefilled ``initial`` query.
    """
    base = POPUP_FLAGS if popup else INLINE_FLAGS
    args: list[str] = [
        *base,
        "--print-query",
        "--no-select-1",
        "--prompt",
        prompt_label,
        "--header",
        header,
        "--expect",
        _DEFAULT_CANCEL_KEY,
    ]
    if initial:
        args.extend(["--query", initial])

    result = run(*args, input="")
    if result.cancelled:
        return PromptResult(query="", cancelled=True)

    out_lines = result.stdout.split("\n")
    query = out_lines[0] if out_lines else ""
    key = out_lines[1] if len(out_lines) > 1 else ""
    if key == _DEFAULT_CANCEL_KEY:
        return PromptResult(query="", cancelled=True, cancel_key=key)
    return PromptResult(query=query, cancelled=False)


def confirm(
    *,
    prompt_label: str,
    header: str,
    yes_label: str = "Yes",
    no_label: str = "No",
    popup: bool = False,
) -> bool:
    """Drive an inline No/Yes fzf prompt; return True only on Yes.

    Used for one-tap confirmations (orphan-dir delete). ``no_label``
    is listed first so the destructive choice never lands under a
    stray Enter. Esc, ctrl-c, or any non-zero exit count as No.
    """
    base = POPUP_FLAGS if popup else INLINE_FLAGS
    result = run(
        *base,
        "--no-sort",
        "--prompt",
        prompt_label,
        "--header",
        header,
        input=f"{no_label}\n{yes_label}",
    )
    return result.returncode == 0 and result.stdout.strip() == yes_label


@dataclass
class Picker:
    """High-level fzf picker for a stream of TSV rows.

    The session-picker and branch-picker each instantiate one of these
    instead of hand-rolling 25-flag :func:`run` calls. The dataclass
    fields cover every attribute that actually varies between the two
    pickers; the constant flag soup (``--ansi``, ``--delimiter \\t``,
    :data:`POPUP_FLAGS`) is supplied internally.

    Set ``with_nth`` to the column number fzf should display (the rest
    of the TSV stays available to ``--bind`` placeholders like ``{1}``).
    Pass ``expect`` as a comma-separated key list (e.g.
    ``"ctrl-w,ctrl-bs"``) to receive the pressed key on stdout. Add
    binds via :meth:`bind` and ``--listen`` support via the
    ``listen_port`` field.
    """

    prompt_label: str
    header: str
    with_nth: str = "1"
    expect: str = ""
    listen_port: int | None = None
    binds: list[str] = field(default_factory=list)
    preview: str | None = None
    preview_window: str | None = None
    extra_flags: tuple[str, ...] = ()

    def bind(self, expression: str) -> Picker:
        """Append ``expression`` to ``--bind`` and return ``self``.

        ``expression`` is the full fzf bind expression
        (e.g. ``"ctrl-d:execute(...)+reload(cat ...)"``). Returning
        ``self`` lets call sites chain ``.bind(...).bind(...)``.
        """
        self.binds.append(expression)
        return self

    def _argv(self) -> list[str]:
        argv: list[str] = [
            *POPUP_FLAGS,
            "--ansi",
            "--delimiter",
            "\t",
            "--with-nth",
            self.with_nth,
            "--prompt",
            self.prompt_label,
            "--header",
            self.header,
        ]
        if self.expect:
            argv.extend(["--expect", self.expect])
        if self.listen_port is not None:
            argv.extend(["--listen", str(self.listen_port)])
        if self.preview is not None:
            argv.extend(["--preview", self.preview])
        if self.preview_window is not None:
            argv.extend(["--preview-window", self.preview_window])
        for expression in self.binds:
            argv.extend(["--bind", expression])
        argv.extend(self.extra_flags)
        return argv

    def run(self, *, stdin: IO[bytes]) -> PickerSelection:
        """Open the picker reading TSV rows from ``stdin``.

        ``stdin`` is the binary handle already streaming the entry
        list — typically a tempfile written by the caller. Returns a
        :class:`PickerSelection` with the pressed expect-key (empty for
        Enter) and the raw selected line.
        """
        result = run(*self._argv(), stdin=stdin)
        if result.cancelled or not result.stdout:
            return PickerSelection(key="", line="", cancelled=True)
        out_lines = result.stdout.split("\n")
        # When ``--expect`` is set, fzf prints the key on line 0 and the
        # selected line on line 1. Without it, line 0 is the selection.
        if self.expect:
            key = out_lines[0] if out_lines else ""
            line = out_lines[1] if len(out_lines) > 1 else ""
        else:
            key = ""
            line = out_lines[0] if out_lines else ""
        return PickerSelection(key=key, line=line, cancelled=False)
