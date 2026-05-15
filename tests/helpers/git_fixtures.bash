# Real-git fixture helpers: set up tmpdir repos with controllable branches,
# remotes, and worktrees for tests that exercise the plugin's git interactions.

# mkrepo PATH [--branches "main feature/x"] [--remote] [--no-initial-commit]
#
# Initialises a git repo at PATH with sensible defaults:
#   - main branch with one initial commit (override with --no-initial-commit)
#   - additional branches if --branches is passed
#   - if --remote is passed, creates a sibling bare "origin" repo, sets it as
#     the remote, pushes, and runs `git remote set-head origin main`
mkrepo() {
  local path="$1"; shift
  local branches="main"
  local with_remote=false
  local with_commit=true
  while (( $# )); do
    case "$1" in
      --branches) branches="$2"; shift 2 ;;
      --remote)   with_remote=true; shift ;;
      --no-initial-commit) with_commit=false; shift ;;
      *) shift ;;
    esac
  done

  mkdir -p "$path"
  git -C "$path" init -q -b main
  git -C "$path" config user.email "test@example.com"
  git -C "$path" config user.name "Test"
  git -C "$path" config commit.gpgsign false

  if $with_commit; then
    : > "$path/README"
    git -C "$path" add README
    git -C "$path" commit -q -m "init"
  fi

  local b
  for b in $branches; do
    [[ "$b" == "main" ]] && continue
    git -C "$path" branch "$b"
  done

  if $with_remote && $with_commit; then
    local origin="${path}.git"
    rm -rf "$origin"
    git init -q --bare -b main "$origin"
    git -C "$path" remote add origin "$origin"
    git -C "$path" push -q --all origin
    git -C "$path" remote set-head origin main >/dev/null
  fi
}

# mkworktree REPO BRANCH PATH
mkworktree() {
  local repo="$1" branch="$2" path="$3"
  if git -C "$repo" rev-parse --verify "$branch" >/dev/null 2>&1; then
    git -C "$repo" worktree add -q "$path" "$branch"
  else
    git -C "$repo" worktree add -q -b "$branch" "$path"
  fi
}

# seed_score_file NAME SCORE [TS]
# Append one row to the score file. TS defaults to now.
seed_score_file() {
  local name="$1" score="$2" ts="${3:-$(date +%s)}"
  mkdir -p "$(dirname "$TMUX_SESSIONS_SCORES_FILE")"
  printf '%s\t%s\t%s\n' "$name" "$score" "$ts" >> "$TMUX_SESSIONS_SCORES_FILE"
}
