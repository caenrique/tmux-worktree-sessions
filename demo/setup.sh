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
cat > "$ROOT/home/.bashrc" <<'EOF'
export PS1='\[\e[36m\]\$\[\e[0m\] '
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

# Pre-warm scores file so projects appear in a deterministic order.
mkdir -p "$ROOT/state"
cat > "$ROOT/state/scores.tsv" <<'EOF'
webapp	100	1700000000
api	50	1700000000
EOF

echo "fixture ready at $ROOT"
