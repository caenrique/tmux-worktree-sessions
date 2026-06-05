"""Pure helpers for the session picker CLI layer.

Functions here take all inputs as explicit parameters; the CLI layer in
``tmux_sessions.__main__`` resolves env vars, the filesystem, and stdout.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from . import git, text


def parse_manual_sessions(spec: str, *, home: str) -> list[tuple[str, Path]]:
    """Parse ``TMUX_SESSIONS_MANUAL_SESSIONS`` into ``(name, path)`` pairs.

    ``spec`` is whitespace-separated ``name:path`` tokens. A leading ``~``
    in a path is expanded to ``home`` to mirror the bash
    ``${path/#\\~/$HOME}`` substitution. Tokens without a ``:`` are
    skipped.
    """
    pairs: list[tuple[str, Path]] = []
    for token in spec.split():
        if ":" not in token:
            continue
        name, _, raw_path = token.partition(":")
        if raw_path.startswith("~"):
            raw_path = home + raw_path[1:]
        pairs.append((name, Path(raw_path)))
    return pairs


def list_projects(
    roots: list[Path],
    *,
    max_depth: int,
    home: str,
    strip_prefixes: list[str],
    manual_spec: str,
) -> Iterator[tuple[str, Path]]:
    """Yield ``(display_name, path)`` for every git project, then manual sessions.

    Git projects are discovered via :func:`git.list_git_projects` and
    rendered through :func:`text.format_session_name` so the bash and
    Python layers agree on the displayed prefix-stripped name. Manual
    sessions are appended verbatim after the discovered projects.
    """
    for project in git.list_git_projects(roots, max_depth=max_depth):
        name = text.format_session_name(str(project), home=home, strip_prefixes=strip_prefixes)
        yield name, project
    yield from parse_manual_sessions(manual_spec, home=home)


def is_orphaned_worktree(path: Path, *, container: Path) -> bool:
    """Return True when ``container`` holds a sibling of ``path`` with ``.git``.

    A directory looks like an orphaned worktree when at least one of its
    siblings is a real git repo (``.git`` present as file or directory).
    The sibling search excludes ``path`` itself; non-directory entries
    and unreadable containers return False.
    """
    try:
        children = list(container.iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return False
    for sibling in children:
        if not sibling.is_dir():
            continue
        if sibling == path:
            continue
        if (sibling / ".git").exists():
            return True
    return False
