#!/usr/bin/env bash
# Version-controlled entry point for the scheduled prospective workers (RESEARCH_ONLY).  usage: bootstrap.sh capture|refresh [worker args...]
#  1. read the approved release pin (`RELEASE.json`) from the DATA branch -- a control-plane file that only the owner/reviewer commits; capture workers cannot write it
#  2. refuse any pin that is not an ancestor of a reviewed branch (feat/sift-lab or main)
#  3. check out exactly that commit (detached), install hash-pinned dependencies only if missing, run the worker module
# The final stdout line is the ONLY thing the model needs to relay.
set -u
ROLE="${1:-}"; shift || true
cd "$(git rev-parse --show-toplevel)" || { echo "$ROLE failed reason=no_repo"; exit 3; }
git fetch -q origin feat/sift-lab main prospective-data 2>/dev/null
REL=$(git show origin/prospective-data:RELEASE.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['code_commit'])" 2>/dev/null)
[ -n "$REL" ] || { echo "$ROLE failed reason=no_release_pin"; exit 3; }
if ! git merge-base --is-ancestor "$REL" origin/feat/sift-lab 2>/dev/null && ! git merge-base --is-ancestor "$REL" origin/main 2>/dev/null; then
  echo "$ROLE failed reason=release_not_on_reviewed_branch release=$REL"; exit 3
fi
git checkout -q --detach "$REL" || { echo "$ROLE failed reason=checkout release=$REL"; exit 3; }
export RELEASE_SHA="$REL"
if ! python3 -c "import numpy, pandas, scipy, sklearn, pyarrow" 2>/dev/null; then
  python3 -m pip install -q --require-hashes --no-deps -r requirements-prospective.lock >/dev/null 2>&1
fi
python3 -c "import numpy, pandas, scipy" 2>/dev/null || { echo "$ROLE failed reason=dependencies"; exit 4; }
case "$ROLE" in
  capture) export CAPTURE_RUN_ID="${CAPTURE_RUN_ID:-capture-$(date -u +%Y%m%dT%H%M%SZ)}"; python3 -m alpha_engine.lab.worker capture --repo . "$@" | tail -1 ;;
  refresh) python3 -m alpha_engine.lab.worker refresh --repo . --work /tmp/work --data-dir /tmp/nflverse "$@" | tail -1 ;;
  *) echo "usage: bootstrap.sh capture|refresh"; exit 2 ;;
esac
exit "${PIPESTATUS[0]}"
