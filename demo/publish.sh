#!/usr/bin/env bash
# Publish demo/readme.gif as a GitHub release asset on a non-versioned
# tag, so the README can link to a stable URL without committing the
# binary into the repo. Idempotent: re-running replaces the asset.
#
# Requires: `gh` authenticated against github.com.

set -euo pipefail

REPO=caenrique/tmux-worktree-sessions
TAG=demo-assets
GIF=/tmp/tws-demo/readme.gif

if [ ! -f "$GIF" ]; then
  echo "Render the GIF first: bash demo/setup.sh && vhs demo/readme.tape" >&2
  exit 1
fi

# Use the public GitHub host explicitly — the user may have GH_HOST
# pointed at an enterprise instance.
unset GH_HOST

if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" --repo "$REPO" \
    --title "Demo assets" \
    --notes "Static assets referenced from the README. Not a versioned release."
fi

# Always re-assert make_latest=false via the API. `gh release edit
# --latest=false` is unreliable (the CLI sends nothing for the false
# case in current gh versions), and the release would otherwise appear
# as "Latest" on the repo homepage and shadow real versioned tags. The
# REST field is a string "true"|"false"|"legacy", so use `-f` (raw
# string), not `-F` (typed bool).
RELEASE_ID=$(gh api "repos/$REPO/releases/tags/$TAG" --jq .id)
gh api -X PATCH "repos/$REPO/releases/$RELEASE_ID" -f make_latest=false >/dev/null

gh release upload "$TAG" "$GIF" --repo "$REPO" --clobber

echo
echo "Done. README link target:"
echo "  https://github.com/$REPO/releases/download/$TAG/readme.gif"
