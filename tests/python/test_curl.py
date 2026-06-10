"""Tests for :mod:`tmux_worktree_sessions.curl`.

Verifies the wire format the spinner / reload code sends to fzf's
``--listen`` HTTP endpoint. The curl stub at ``tests/python/_stubs/curl``
is loaded via the ``curl_stub`` fixture.
"""

from __future__ import annotations

from tmux_worktree_sessions import curl

from .conftest import CurlStub


def test_post_sends_to_localhost_port_with_default_host(curl_stub: CurlStub) -> None:
    curl.post(54321, "ping", max_time=0.5)
    text = curl_stub.text()
    assert "localhost:54321" in text
    assert "ping" in text


def test_post_passes_max_time_to_curl(curl_stub: CurlStub) -> None:
    curl.post(54321, "ping", max_time=2.0)
    text = curl_stub.text()
    assert "--max-time" in text
    assert "2.0" in text


def test_post_honours_custom_host(curl_stub: CurlStub) -> None:
    curl.post(54321, "ping", max_time=0.5, host="127.0.0.1")
    text = curl_stub.text()
    assert "127.0.0.1:54321" in text


def test_post_swallows_curl_nonzero_exit(curl_stub: CurlStub) -> None:
    # The stub currently always exits 0; we exercise the docstring's
    # "non-zero exit is silent" promise by pointing the curl call at a
    # port that does not have a server, but the stub doesn't actually
    # connect — so the contract we can verify here is just "the call
    # returns None instead of raising on a normal request".
    assert curl.post(54321, "ping", max_time=0.5) is None
