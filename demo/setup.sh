#!/usr/bin/env bash
# Provision a throwaway projects fixture for the README demo.
#
# Layout (sibling-dir style, what the plugin expects):
#   /tmp/tws-demo/Projects/webapp/main   (git repo, branches: main, feature/login)
#   /tmp/tws-demo/Projects/api/main      (git repo, branch: main)
#
# Idempotent: wipes /tmp/tws-demo on every run.

set -euo pipefail

ROOT=/tmp/tws-demo
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

rm -rf "$ROOT"
mkdir -p "$ROOT/Projects" "$ROOT/home"

# Stable-path symlink so demo/readme.tape can reference the plugin
# checkout without baking in a user-specific absolute path.
ln -snf "$REPO" "$ROOT/repo"

# Minimal rc files for shells launched with HOME pointing here.
# The outer VHS shell uses bash (loads .bashrc), and the inner shells
# spawned by the new tmux session also use bash via demo/tmux.conf's
# `default-shell`. Empty .zshrc/.zshenv prevent any zsh fallback from
# trying to source the user's vendor profile that doesn't exist here.
# Pin fzf to Catppuccin Mocha so the picker renders the same in CI as
# it does locally. Without this, fzf falls back to its built-in palette
# in CI (which has no FZF_DEFAULT_OPTS set), but a developer running the
# demo locally would see their personal theme instead.
cat > "$ROOT/home/.bashrc" <<'EOF'
export PS1='\[\e[36m\]\$\[\e[0m\] '
export FZF_DEFAULT_OPTS='--color=bg+:#313244,bg:#1e1e2e,spinner:#f5e0dc,hl:#f38ba8,fg:#cdd6f4,header:#f38ba8,info:#cba6f7,pointer:#f5e0dc,marker:#b4befe,fg+:#cdd6f4,prompt:#cba6f7,hl+:#f38ba8,border:#89b4fa'
EOF
: > "$ROOT/home/.zshrc"
: > "$ROOT/home/.zshenv"
: > "$ROOT/home/.profile"

mkrepo() {
  local path=$1
  shift
  mkdir -p "$path"
  git -C "$path" init -q -b main
  git -C "$path" config user.email "demo@example.com"
  git -C "$path" config user.name "Demo"
  echo "# $(basename "$(dirname "$path")")" > "$path/README.md"
  git -C "$path" add README.md
  git -C "$path" commit -q -m "initial commit"
  for branch in "$@"; do
    git -C "$path" branch "$branch" >/dev/null
  done
}

mkrepo "$ROOT/Projects/webapp/main" feature/login feature/signup
mkrepo "$ROOT/Projects/api/main"
mkrepo "$ROOT/Projects/mobile-app/main"
mkrepo "$ROOT/Projects/design-system/main"
mkrepo "$ROOT/Projects/analytics/main"
mkrepo "$ROOT/Projects/payments-service/main"
mkrepo "$ROOT/Projects/internal-docs/main"
mkrepo "$ROOT/Projects/infra/main"

# Pre-warm scores file so projects appear in a stable, recognizable
# order in the picker (highest base wins; same ts means recency tie).
mkdir -p "$ROOT/state"
cat > "$ROOT/state/scores.tsv" <<'EOF'
webapp	100	1700000000
api	90	1700000000
mobile-app	80	1700000000
design-system	70	1700000000
analytics	60	1700000000
payments-service	50	1700000000
internal-docs	40	1700000000
infra	30	1700000000
EOF

echo "fixture ready at $ROOT"
