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
    --notes "Static assets referenced from the README. Not a versioned release." \
    --latest=false
fi

# Always re-assert --latest=false: `--latest=false` on `release create`
# only applies the first time, and an existing release created without
# it would still appear as "Latest" on the repo homepage and shadow any
# real versioned tag. Idempotent — a no-op if already demoted.
gh release edit "$TAG" --repo "$REPO" --latest=false

gh release upload "$TAG" "$GIF" --repo "$REPO" --clobber

echo
echo "Done. README link target:"
echo "  https://github.com/$REPO/releases/download/$TAG/readme.gif"
