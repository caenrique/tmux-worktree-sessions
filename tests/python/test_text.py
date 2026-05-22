"""Pure-layer tests mirroring the bats `strip_ansi` cases."""

from __future__ import annotations

from tmux_sessions.text import strip_ansi


def test_strip_ansi_removes_single_sgr_escape() -> None:
    assert strip_ansi("\x1b[31mhello\x1b[0m") == "hello"


def test_strip_ansi_removes_multiple_escapes_preserving_inner_text() -> None:
    assert strip_ansi("\x1b[1;38;2;100;200;50mfoo\x1b[0m \x1b[33mbar\x1b[0m") == "foo bar"


def test_strip_ansi_no_op_on_plain_text() -> None:
    assert strip_ansi("plain text 123") == "plain text 123"
