#!/usr/bin/env bash
# SessionStart hook: fetch the latest changes from the remote before any work begins.
# Fast-forward only; never merges, rebases, or discards local work.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
[ -n "$(git remote)" ] || { echo "[sync] No git remote configured yet; skipped fetch."; exit 0; }

git fetch --all --prune --quiet 2>/dev/null || { echo "[sync] git fetch failed (offline?). Run 'git pull --ff-only' manually before starting work."; exit 0; }

branch=$(git rev-parse --abbrev-ref HEAD)
if ! git rev-parse '@{u}' >/dev/null 2>&1; then
  echo "[sync] Fetched. Branch '$branch' has no upstream; nothing to pull."
  exit 0
fi

behind=$(git rev-list --count HEAD..@{u})
ahead=$(git rev-list --count @{u}..HEAD)
if [ "$behind" -eq 0 ]; then
  echo "[sync] '$branch' is up to date with upstream (ahead by $ahead)."
elif [ -n "$(git status --porcelain)" ]; then
  echo "[sync] WARNING: '$branch' is $behind commit(s) behind upstream but has uncommitted changes, so it was NOT pulled. Commit or stash, then run 'git pull --rebase'."
elif git pull --ff-only --quiet 2>/dev/null; then
  echo "[sync] Pulled $behind new commit(s) into '$branch'. Latest: $(git log -1 --oneline)"
else
  echo "[sync] WARNING: '$branch' has diverged from upstream ($ahead ahead, $behind behind). Run 'git pull --rebase' and resolve conflicts before starting work."
fi
exit 0
