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
