# tmux-sessions

A tmux plugin that gives you a unified fuzzy picker for sessions and git worktrees. Open any project, switch between running sessions, create and delete worktrees, and rename branches — all from a single keyboard shortcut, ranked by how recently you used them.

## What it does

Press the session key (default `Ctrl+Shift+S`) from anywhere in tmux to open a full-screen picker. The picker shows:

- **Running sessions** at the top, highlighted and sorted by recency. The current session is pinned first; the previous session is pinned second.
- **Projects** below — git repositories found under your configured project directories, also sorted by recency. Projects already open as sessions are hidden to avoid duplicates.

Selecting an entry switches to the session (or creates one if the project isn't open yet). Everything you need to manage your workspace — creating worktrees, renaming branches, deleting sessions — is a keypress away inside the picker.

## Requirements

- [tmux](https://github.com/tmux/tmux) ≥ 3.2
- [git](https://git-scm.com)
- [fzf](https://github.com/junegunn/fzf)
- [python](https://www.python.org) ≥ 3.8 *(for recency-score sorting)*
- [fd](https://github.com/sharkdp/fd) *(optional — falls back to `find` if not installed)*
- [curl](https://curl.se) *(for the live fetch-and-reload animation in the branch picker)*

## Installation

### With TPM

Add to your `~/.config/tmux/tmux.conf`:

```tmux
set -g @plugin 'caenrique/tmux-sessions'
```

Then press `prefix + I` inside tmux to install.

### Manual

Clone the repository and source the entry point from your tmux config:

```tmux
run-shell '/path/to/tmux-sessions/tmux-sessions.tmux'
```

## Configuration

All options are set in `tmux.conf` with `set -g @option value`. Every option has a sensible default — you only need to set the ones you want to change.

| Option | Default — Description |
|---|---|
| `@tmux-sessions-key` | `C-S-s` — Key binding to open the session picker |
| `@tmux-sessions-projects-dir` | `$HOME/Projects` — Space-separated list of root directories to scan for git repos |
| `@tmux-sessions-strip-prefixes` | *(none)* — Space-separated path prefixes to strip from display names |
| `@tmux-sessions-manual-sessions` | *(none)* — Always-visible entries as space-separated `name:path` pairs |
| `@tmux-sessions-scores-file` | `$HOME/.local/share/tmux-sessions/scores.tsv` — Path to the recency score database |
| `@tmux-sessions-max-depth` | `6` — How many directory levels deep to search for git repos |
| `@tmux-sessions-default-branch` | `main` — Fallback branch name when the remote default can't be determined |
| `@tmux-sessions-score-half-life` | `14` — Days until a session's recency score decays to half its value |
| `@tmux-sessions-score-path-boost` | `1.0` — Multiplier for the path-similarity boost; `0` disables it entirely |
| `@tmux-sessions-icon-style` | `nerd` — Icon set: `nerd` (requires a Nerd Font), `emoji`, `ascii`, or `none` |

### Example configuration

```tmux
set -g @plugin 'caenrique/tmux-sessions'

set -g @tmux-sessions-key 'C-S-s'

# Scan multiple project roots
set -g @tmux-sessions-projects-dir '$HOME/Projects $HOME/work'

# Strip these prefixes from display names so paths are shorter
set -g @tmux-sessions-strip-prefixes '$HOME/Projects/github.com $HOME/Projects/gitlab.com'

# Always show these entries regardless of git discovery
set -g @tmux-sessions-manual-sessions 'Notes:~/Notes dotfiles:~/.config'
```

### Status bar display names

The session picker derives display names from filesystem paths. If you want the tmux status bar to show the same short names (instead of raw paths with dots converted to underscores), add this to your `tmux.conf`:

```tmux
set -g status-left '#(~/.config/tmux/plugins/tmux-sessions/scripts/sessions.sh --display-name "#{session_path}" "#{session_name}")'
```

## Usage

### Session picker

Open with the configured key (default `Ctrl+Shift+S`).

| Key | Action |
|---|---|
| `Enter` | Switch to the selected session; create one if the entry is a project |
| `Ctrl-W` | Open the branch/worktree picker for the selected repo |
| `Ctrl-D` | Kill the session **and** delete its linked git worktree. On orphaned directories, prompts for confirmation before deleting |
| `Ctrl-X` | Kill the session only; the entry stays visible as a project |
| `Ctrl-R` | Rename: for linked worktrees, renames the git branch and moves the directory; for plain sessions, renames the tmux session |
| `?` | Toggle the preview pane (shows session window contents or a directory listing) |
| `Ctrl-Backspace` / `Esc` | Close the picker |

### Branch / worktree picker

Opened by pressing `Ctrl-W` in the session picker.

| Key | Action |
|---|---|
| `Enter` | Checkout the selected branch in a new worktree (or switch if already checked out) |
| `Ctrl-F` | Fetch all remotes and reload the branch list. Fetching also happens automatically when the last fetch is more than 15 minutes old |
| `Ctrl-Backspace` | Go back to the session picker |
| `Esc` | Close everything |

Selecting the `[new]` entry at the top of the list lets you type a new branch name, which is created from the repo's default remote branch.

## Worktree layout

The plugin is designed around a sibling-directory worktree layout. Given a repo `~/Projects/github.com/org/myrepo`, the expected layout is:

```
~/Projects/github.com/org/myrepo/
├── main/        ← main worktree (checked out on the default branch)
├── feature-x/  ← linked worktree for branch "feature-x"
└── fix-123/    ← linked worktree for branch "fix-123"
```

When you create a worktree via `Ctrl-W`, the new directory is placed as a sibling of the existing worktrees. Rename (`Ctrl-R`) moves the directory and updates the git linkage automatically.

## Development

Tests live in `tests/` and run under [bats-core](https://github.com/bats-core/bats-core); shell scripts are linted with [shellcheck](https://www.shellcheck.net/). The Makefile wraps both:

```sh
brew install bats-core shellcheck
make check       # lint + test (default target)
make test        # bats only
make lint        # shellcheck only
```

Both run on Linux (and bats also on macOS) in CI on every push and pull request. Code changes should keep the suite green and address any shellcheck warnings on touched files.

## Recency ranking

The picker ranks entries by how recently and frequently you've opened them. Each time you switch to a session, its score increases by 1. Scores decay with a configurable half-life (default: 14 days), so sessions you haven't touched in a while gradually sink below more active ones.

Entries whose path shares a longer prefix with your current working directory also get a boost (configurable via `@tmux-sessions-score-path-boost`, default `1.0`). At the default values, a same-repo worktree picked at least once in the last month will rank above an unrelated project picked last week, while a project you've picked multiple times this week always stays at the top.

## See also

| | tmux-sessions | [tmux-sessionizer](https://github.com/ThePrimeagen/tmux-sessionizer) | [tmux-fzf](https://github.com/sainnhe/tmux-fzf) | [tmux-project](https://github.com/sei40kr/tmux-project) |
|---|---|---|---|---|
| Session switching | ✓ | ✓ | ✓ | ✓ |
| Project discovery | ✓ | ✓ | — | ✓ |
| Recency ranking | ✓ | — | — | — |
| Git worktree management | ✓ | — | — | — |
| Branch picker | ✓ | — | — | — |
| Window/pane management | — | — | ✓ | — |

**tmux-sessionizer** is the go-to if you want something minimal and scriptable. **tmux-fzf** is a better fit if you also need window and pane management. **tmux-project** is similar in scope to tmux-sessions but without worktree support. Choose this plugin if your workflow revolves around git worktrees and you want everything — project discovery, session switching, and branch management — in one picker.

---

*This plugin was built with the help of [Claude](https://claude.ai).*
