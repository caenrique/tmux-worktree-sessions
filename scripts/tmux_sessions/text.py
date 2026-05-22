"""Pure text utilities for tmux-sessions.

This module is the **pure layer** — it never touches ``os.environ``,
``sys.stdin``/``stdout``, ``argparse``, the wall clock, or files. The
CLI layer in ``tmux_sessions.__main__`` resolves those concerns and
calls the functions below with explicit parameters.
"""

from __future__ import annotations

import re

_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_WHITESPACE_RE = re.compile(r"\s")


def strip_ansi(s: str) -> str:
    """Remove SGR (``CSI ... m``) ANSI escape sequences from ``s``."""
    return _ANSI_SGR_RE.sub("", s)


def sanitize_name(s: str) -> str:
    """Trim leading/trailing whitespace and replace each internal whitespace char with ``-``."""
    return _WHITESPACE_RE.sub("-", s.strip())


def format_session_name(path: str, *, home: str, strip_prefixes: list[str]) -> str:
    """Derive a short tmux session name from a filesystem path.

    Transformations, in order:
        1. Strip the first matching prefix in ``strip_prefixes``. A leading
           ``~`` in a prefix is expanded to ``home``. Caller controls
           ordering — list longer prefixes first to match longest-first.
        2. Abbreviate ``home`` to ``~`` if ``path`` is exactly ``home`` or
           sits beneath it.
    """
    for raw_prefix in strip_prefixes:
        prefix = home + raw_prefix[1:] if raw_prefix.startswith("~") else raw_prefix
        needle = prefix + "/"
        if path.startswith(needle):
            path = path[len(needle) :]
            break

    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path
