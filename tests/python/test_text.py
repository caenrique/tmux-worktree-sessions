"""Pure-layer tests for :mod:`tmux_sessions.text`."""

from __future__ import annotations

from tmux_sessions.text import format_session_name, sanitize_name, strip_ansi


def test_strip_ansi_removes_single_sgr_escape() -> None:
    assert strip_ansi("\x1b[31mhello\x1b[0m") == "hello"


def test_strip_ansi_removes_multiple_escapes_preserving_inner_text() -> None:
    assert strip_ansi("\x1b[1;38;2;100;200;50mfoo\x1b[0m \x1b[33mbar\x1b[0m") == "foo bar"


def test_strip_ansi_no_op_on_plain_text() -> None:
    assert strip_ansi("plain text 123") == "plain text 123"


def test_sanitize_name_trims_leading_and_trailing_whitespace() -> None:
    assert sanitize_name("   hello   ") == "hello"


def test_sanitize_name_replaces_internal_spaces_with_dashes() -> None:
    assert sanitize_name("my new branch") == "my-new-branch"


def test_sanitize_name_empty_input_returns_empty() -> None:
    assert sanitize_name("") == ""


def test_sanitize_name_all_whitespace_returns_empty() -> None:
    assert sanitize_name("      ") == ""


HOME = "/home/u"


def test_format_session_name_no_prefix_replaces_home_with_tilde() -> None:
    assert format_session_name(f"{HOME}/Projects/foo", home=HOME, strip_prefixes=[]) == "~/Projects/foo"


def test_format_session_name_strips_a_configured_prefix() -> None:
    assert (
        format_session_name(
            f"{HOME}/Projects/github.com/org/repo",
            home=HOME,
            strip_prefixes=[f"{HOME}/Projects"],
        )
        == "github.com/org/repo"
    )


def test_format_session_name_uses_first_listed_prefix_that_matches() -> None:
    assert (
        format_session_name(
            f"{HOME}/Projects/github.com/org/repo",
            home=HOME,
            strip_prefixes=[f"{HOME}/Projects/github.com", f"{HOME}/Projects"],
        )
        == "org/repo"
    )


def test_format_session_name_expands_literal_home_inside_a_configured_prefix() -> None:
    assert (
        format_session_name(
            f"{HOME}/Projects/foo",
            home=HOME,
            strip_prefixes=["~/Projects"],
        )
        == "foo"
    )


def test_format_session_name_no_matching_prefix_falls_back_to_tilde() -> None:
    assert (
        format_session_name(
            f"{HOME}/anywhere",
            home=HOME,
            strip_prefixes=["/nonexistent"],
        )
        == "~/anywhere"
    )


def test_format_session_name_path_equal_to_home_becomes_tilde() -> None:
    assert format_session_name(HOME, home=HOME, strip_prefixes=[]) == "~"
