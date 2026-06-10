# tmux-worktree-sessions

![demo](https://github.com/caenrique/tmux-worktree-sessions/releases/download/demo-assets/readme.gif)

A tmux plugin that gives you a unified fuzzy picker for sessions and git worktrees. Open any project, switch between running sessions, create and delete worktrees, and rename branches — all from a single keyboard shortcut, ranked by how recently you used them.

🔍 fuzzy picker &nbsp;·&nbsp; 🌿 git worktrees &nbsp;·&nbsp; 📊 recency ranked &nbsp;·&nbsp; ⚡ one keypress

## ✨ What it does

Press the session key (default `Ctrl+Shift+S`) from anywhere in tmux to open a full-screen picker. The picker shows:

- **Running sessions** at the top, highlighted and sorted by most-recently-attached. The current session is pinned first; the previous session is pinned second; the rest follow newest→oldest, so the third entry is the one you used before the previous, and so on.
- **Projects** below — git repositories found under your configured project directories, sorted by recency score. Projects already open as sessions are hidden to avoid duplicates.

Selecting an entry switches to the session (or creates one if the project isn't open yet). Everything you need to manage your workspace — creating worktrees, renaming branches, deleting sessions — is a keypress away inside the picker.

## 📋 Requirements

- [python](https://www.python.org) ≥ 3.8 — the plugin's logic is a Python package; bash is just the TPM entry point
- [tmux](https://github.com/tmux/tmux) ≥ 3.2
- [git](https://git-scm.com)
- [fzf](https://github.com/junegunn/fzf) — picker UI, also used as `--listen` server for the live branch-list reload
- [fd](https://github.com/sharkdp/fd) — fast project discovery under `@tws-projects-dir`
- [curl](https://curl.se) — talks to fzf's `--listen` HTTP port to drive the fetch-and-reload animation in the branch picker

## 📦 Installation

### With TPM

Add to your `~/.config/tmux/tmux.conf`:

```tmux
set -g @plugin 'caenrique/tmux-worktree-sessions'
```

Then press `prefix + I` inside tmux to install.

### Manual

Clone the repository and source the entry point from your tmux config:

```tmux
run-shell '/path/to/tmux-worktree-sessions/tmux-worktree-sessions.tmux'
```

## ⚙️ Configuration

All options are set in `tmux.conf` with `set -g @option value`. Every option has a sensible default — you only need to set the ones you want to change.

| Option | Default — Description |
|---|---|
| `@tws-key` | `C-S-s` — Key binding to open the session picker |
| `@tws-worktree-key` | `C-S-w` — Key binding to open the worktree/branch picker for the current pane's repo |
| `@tws-projects-dir` | `$HOME/Projects` — Space-separated list of root directories to scan for git repos |
| `@tws-strip-prefixes` | *(none)* — Space-separated path prefixes to strip from display names |
| `@tws-manual-sessions` | *(none)* — Always-visible entries as space-separated `name:path` pairs |
| `@tws-scores-file` | `$HOME/.local/share/tws/scores.tsv` — Path to the recency score database |
| `@tws-max-depth` | `6` — How many directory levels deep to search for git repos |
| `@tws-default-branch` | `main` — Fallback branch name when the remote default can't be determined |
| `@tws-score-half-life` | `14` — Days until a session's recency score decays to half its value |
| `@tws-score-path-boost` | `1.0` — Multiplier for the path-similarity boost; `0` disables it entirely |
| `@tws-icon-style` | `nerd` — Icon set: `nerd` (requires a Nerd Font), `emoji`, `ascii`, or `none` |
| `@tws-worktrees-dir` | `.worktrees` — Sub-folder name used by the subfolder worktree layout |
| `@tws-default-worktree-layout` | `subfolder` — Layout used for new worktrees in repos without existing linked worktrees: `sibling` or `subfolder` |

### Example configuration

```tmux
set -g @plugin 'caenrique/tmux-worktree-sessions'

set -g @tws-key 'C-S-s'

# Scan multiple project roots
set -g @tws-projects-dir '$HOME/Projects $HOME/work'

# Strip these prefixes from display names so paths are shorter
set -g @tws-strip-prefixes '$HOME/Projects/github.com $HOME/Projects/gitlab.com'

# Always show these entries regardless of git discovery
set -g @tws-manual-sessions 'Notes:~/Notes dotfiles:~/.config'
```

### Status bar display names

The session picker derives display names from filesystem paths. To show those same short names in the tmux status bar (instead of raw paths with dots converted to underscores), drop `#{session_display_name}` into your `status-left` or `status-right`:

```tmux
set -g status-left '#{session_display_name} | %H:%M'
```

The placeholder is expanded once when the plugin is loaded by TPM, so make sure your `status-left` / `status-right` are set **before** the `run '~/.tmux/plugins/tpm/tpm'` line in your `tmux.conf`.

## 📖 Usage

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

Opened by pressing `Ctrl-W` in the session picker, or directly with `Ctrl+Shift+W` (`@tws-worktree-key`) from anywhere in tmux to skip straight to the picker for the current pane's repo. If the pane isn't inside a git repo, a flash message says so.

| Key | Action |
|---|---|
| `Enter` | Checkout the selected branch in a new worktree (or switch if already checked out) |
| `Ctrl-F` | Fetch all remotes and reload the branch list. Fetching also happens automatically when the last fetch is more than 15 minutes old |
| `Ctrl-Backspace` | Go back to the session picker |
| `Esc` | Close everything |

Selecting the `[new]` entry at the top of the list lets you type a new branch name, which is created from the repo's default remote branch.

## 🌳 Worktree layouts

The plugin supports two worktree layouts and picks the right one per repo by inspecting existing linked worktrees.

### Sibling layout

Used when the repo's main checkout sits inside a container directory (`repo/main/`) and linked worktrees are siblings of it.

```
~/Projects/github.com/org/myrepo/
├── main/       ← main worktree (checked out on the default branch)
├── feature-x/  ← linked worktree for branch "feature-x"
└── fix-123/    ← linked worktree for branch "fix-123"
```

### Subfolder layout

Used when the main checkout is the repo root itself (`repo/`). New worktrees are placed inside a dedicated sub-directory so they never spill outside the repo.

```
~/Projects/github.com/org/myrepo/
├── .git/             ← main worktree at the repo root
├── src/, README.md, …
└── .worktrees/
    ├── feature-x/   ← linked worktree for branch "feature-x"
    └── fix-123/     ← linked worktree for branch "fix-123"
```

Configure the sub-folder name with `@tws-worktrees-dir` (default `.worktrees`).

### Detection

For each repo the plugin looks at the existing linked worktrees:

- All siblings of the main checkout → **sibling layout**.
- All under `<main>/<worktrees-dir>/` → **subfolder layout**.
- No linked worktrees yet, but the main checkout's basename matches its current branch (e.g. `repo/main/` on branch `main`) → **sibling layout** (the canonical sibling shape — future worktrees land at `repo/<branch>/`).
- A mix, or none of the above → fall back to `@tws-default-worktree-layout` (default `subfolder`, so a freshly cloned repo never creates worktrees outside its own directory).

`Ctrl-W` creates a new worktree in the right place; `Ctrl-R` renames within the same layout.

## 🛠️  Development

The dev environment is driven by [devenv](https://devenv.sh/) and uses
`uv` for Python deps. After installing [Nix](https://nixos.org/download)
and devenv:

```sh
devenv shell    # enter the dev shell (uv sync runs automatically)
devenv test     # run every check (what CI runs)
```

Inside the dev shell, the package exposes a `tws` console script for
ad-hoc debugging — equivalent to `python3 -m tmux_worktree_sessions`:

```sh
tws sessions manage      # run the picker outside a TPM-managed tmux
tws --help
```

See [BUILD.md](BUILD.md) for the full guide — task list, dependency
management, lint setup, test layout, and CI details.

## 🔗 See also

- [tmux-sessionizer](https://github.com/ThePrimeagen/tmux-sessionizer)
- [tmux-fzf](https://github.com/sainnhe/tmux-fzf)
- [tmux-project](https://github.com/sei40kr/tmux-project)

---

*This plugin was built with the help of [Claude](https://claude.ai).*
