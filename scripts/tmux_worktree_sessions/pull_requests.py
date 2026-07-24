"""Optional GitHub pull-request discovery via the ``gh`` CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PullRequest:
    """Display metadata for an open pull request."""

    title: str
    author: str
    days_open: int


def is_available() -> bool:
    """Return whether the optional ``gh`` executable is on PATH."""
    return shutil.which("gh") is not None


def list_open(repo: Path, *, now: float) -> dict[str, PullRequest]:
    """Return open pull requests keyed by their head branch name.

    Missing authentication, non-GitHub remotes, malformed output, and
    other ``gh`` failures are intentionally treated as an empty result:
    pull-request integration must never prevent ordinary branch checkout.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "headRefName,title,author,createdAt",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except OSError:
        return {}
    if result.returncode != 0:
        return {}
    try:
        rows: Any = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    if not isinstance(rows, list):
        return {}

    pull_requests: dict[str, PullRequest] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        branch = row.get("headRefName")
        title = row.get("title")
        created_at = row.get("createdAt")
        author_value = row.get("author")
        if not isinstance(branch, str) or not isinstance(title, str) or not isinstance(created_at, str):
            continue
        author = author_value.get("login") if isinstance(author_value, dict) else ""
        if not isinstance(author, str):
            author = ""
        try:
            opened = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        days_open = max(0, int((now - opened.timestamp()) // 86400))
        pull_requests[branch] = PullRequest(
            title=" ".join(title.split()),
            author=" ".join(author.split()),
            days_open=days_open,
        )
    return pull_requests
