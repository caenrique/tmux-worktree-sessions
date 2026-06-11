"""Pure helpers for the session picker CLI layer.

Functions here take all inputs as explicit parameters; the CLI layer in
``tmux_worktree_sessions.__main__`` resolves env vars, the filesystem, and stdout.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from . import git, score, text, tmux
from .icons import IconSet

# Catppuccin Mocha colours used to highlight session rows in
# build_entries and the ctrl-r session-rename action.
GREEN = "\033[38;2;166;227;161m"
YELLOW = "\033[38;2;249;226;175m"
RESET = "\033[0m"


def parse_manual_sessions(spec: str, *, home: str) -> list[tuple[str, Path]]:
    """Parse ``TWS_MANUAL_SESSIONS`` into ``(name, path)`` pairs.

    ``spec`` is whitespace-separated ``name:path`` tokens. A leading
    ``~`` in a path is expanded to ``home``. Tokens without a ``:`` are
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


def expand_subfolder_worktrees(repo: Path, *, worktrees_dir: str) -> list[Path]:
    """Return subfolder-layout linked worktrees of ``repo`` via filesystem stat.

    For each child of ``<repo>/<worktrees_dir>/`` that is a directory and
    contains a ``.git`` entry (file or directory), the child path is
    returned. The output is empty when the worktrees directory does not
    exist, is not a directory, or is unreadable. No git subprocess is
    invoked — this is the hot path that runs once per discovered repo
    when the picker opens, so it stays purely filesystem-bound.
    """
    sub = repo / worktrees_dir
    try:
        children = list(sub.iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []
    return [child for child in children if child.is_dir() and (child / ".git").exists()]


def list_projects(
    roots: list[Path],
    *,
    max_depth: int,
    home: str,
    strip_prefixes: list[str],
    manual_spec: str,
    worktrees_dir: str,
) -> Iterator[tuple[str, Path]]:
    """Yield ``(display_name, path)`` for every git worktree, then manual sessions.

    Sibling-layout worktrees are surfaced by ``fd`` directly (each has
    its own ``.git`` entry at top level). Subfolder-layout linked
    worktrees, which ``fd --prune`` skips, are synthesized from the
    filesystem via :func:`expand_subfolder_worktrees`. The whole flow
    avoids per-repo git subprocesses so the picker opens fast even with
    many repos. Manual sessions are appended verbatim afterwards.
    """
    for project in git.list_git_projects(roots, max_depth=max_depth):
        name = text.format_session_name(str(project), home=home, strip_prefixes=strip_prefixes)
        yield name, project
        for wt_path in expand_subfolder_worktrees(project, worktrees_dir=worktrees_dir):
            wt_name = text.format_session_name(str(wt_path), home=home, strip_prefixes=strip_prefixes)
            yield wt_name, wt_path
    yield from parse_manual_sessions(manual_spec, home=home)


def apply_ctrl_x(
    lines: list[str],
    *,
    sid: str,
    sess_path: str,
    icons: IconSet,
) -> list[str]:
    """Replace the session row matching ``sid`` with a project row.

    The new project row is inserted directly before the ``n`` sentinel
    so the "new session" entry stays at the bottom of the picker; if no
    sentinel is present, the row is appended to the end.
    """
    clean_name = ""
    for line in lines:
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0] == "s" and fields[1] == sid:
            clean_name = fields[2]
            break

    if not clean_name:
        return list(lines)

    new_row = f"p\t{sess_path}\t{clean_name}\t{icons.project}{icons.sep}{clean_name}"

    result: list[str] = []
    saved: str | None = new_row
    for line in lines:
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] == "s" and fields[1] == sid:
            continue
        if line.startswith("n\t") and saved is not None:
            result.append(saved)
            saved = None
        result.append(line)

    if saved is not None:
        result.append(saved)

    return result


def apply_ctrl_r_session_rename(
    lines: list[str],
    *,
    sid: str,
    new_name: str,
    icons: IconSet,
) -> list[str]:
    """Rewrite the search and display columns of the matching session row.

    When a row's first two columns are ``s`` and ``sid``, overwrite
    column 3 with ``new_name`` and column 4 with the green-coloured
    icon+name display so the picker reflects the rename without needing
    a full ``build_entries`` rebuild.
    """
    new_display = f"{GREEN}{icons.session}{icons.sep}{new_name}{RESET}"
    result: list[str] = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) >= 4 and fields[0] == "s" and fields[1] == sid:
            fields[2] = new_name
            fields[3] = new_display
            result.append("\t".join(fields))
        else:
            result.append(line)
    return result


def _format_session_display(
    sess_path: Path,
    name: str,
    *,
    home: str,
    strip_prefixes: list[str],
) -> str:
    """Pick the display name for a tmux session row.

    Fall back to the stored session name when the derived form does not
    round-trip through tmux's dot→underscore substitution, since that
    means the user renamed the session by hand.
    """
    derived = text.format_session_name(str(sess_path), home=home, strip_prefixes=strip_prefixes)
    return derived if derived.replace(".", "_") == name else name


def build_entries(
    *,
    home: str,
    strip_prefixes: list[str],
    projects_roots: list[Path],
    max_depth: int,
    manual_spec: str,
    icons: IconSet,
    score_entries: list[tuple[str, float, float]],
    now: float,
    half_life_secs: float,
    path_boost: float,
    worktrees_dir: str,
) -> Iterator[str]:
    """Yield the unified 4-column TSV the session picker consumes.

    Output columns are ``type<TAB>key<TAB>search<TAB>display``: ``s`` for
    running sessions, ``p`` for project rows, ``n`` for the new-session
    sentinel. The current session is pinned first (yellow + ``(current)``),
    the previous session second (green + ``(previous)``), remaining
    sessions follow in ``session_last_attached`` descending order, then
    project rows sorted by recency score, then the sentinel.

    All tmux state (current/previous session, pane path, session list)
    is queried via :mod:`tmux_worktree_sessions.tmux` — these are external state
    queries with no caller-supplied parameters, so they belong in the
    pure layer per the migration plan.
    """
    sessions = tmux.list_sessions()
    current = tmux.current_session_name()
    previous = tmux.previous_session_name()
    pane_path = tmux.pane_current_path()

    by_name: dict[str, tmux.Session] = {s.name: s for s in sessions}

    # Pin current session first (yellow, "(current)"), then previous
    # session second (green, "(previous)"). Both are skipped silently
    # when their tmux record is missing.
    if current and current in by_name:
        s = by_name[current]
        display = _format_session_display(s.path, s.name, home=home, strip_prefixes=strip_prefixes)
        yield (f"s\t{s.sid}\t{display}\t{YELLOW}{icons.session}{icons.sep}{display} (current){RESET}")

    if previous and previous != current and previous in by_name:
        s = by_name[previous]
        display = _format_session_display(s.path, s.name, home=home, strip_prefixes=strip_prefixes)
        yield (f"s\t{s.sid}\t{display}\t{GREEN}{icons.session}{icons.sep}{display} (previous){RESET}")

    # Remaining sessions ordered by last_attached desc; never-attached
    # sessions report 0 and sink to the bottom of this block.
    remaining = [s for s in sessions if s.name != current and s.name != previous]
    remaining.sort(key=lambda s: s.last_attached, reverse=True)
    for s in remaining:
        display = _format_session_display(s.path, s.name, home=home, strip_prefixes=strip_prefixes)
        yield f"s\t{s.sid}\t{display}\t{GREEN}{icons.session}{icons.sep}{display}{RESET}"

    # Projects not yet open as sessions, sorted by recency score.
    open_names = {s.name for s in sessions}
    project_rows: list[str] = []
    for name, project_path in list_projects(
        projects_roots,
        max_depth=max_depth,
        home=home,
        strip_prefixes=strip_prefixes,
        manual_spec=manual_spec,
        worktrees_dir=worktrees_dir,
    ):
        if name.replace(".", "_") in open_names:
            continue
        project_rows.append(f"{name}\t{project_path}\t{project_path}")

    scores = score.current_scores(score_entries, now=now, half_life_secs=half_life_secs)
    ranked = score.sort_rows(
        project_rows,
        boost_path=pane_path,
        scores=scores,
        path_boost=path_boost,
    )
    for row in ranked:
        cols = row.split("\t")
        if len(cols) < 2:
            continue
        row_name, row_path = cols[0], cols[1]
        yield f"p\t{row_path}\t{row_name}\t{icons.project}{icons.sep}{row_name}"

    yield f"n\t\tnew session\t{icons.new}{icons.sep}new session"
