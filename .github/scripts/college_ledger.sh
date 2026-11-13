#!/usr/bin/env bash
# Durable, append-only call ledger for the college direct-API probe, kept on branch `college-direct-ledger` (counts, hashes, safe summaries; never response data).
#   college_ledger.sh fetch DIR            -> DIR/ledger.json (absent on first use) and DIR/parent (tip sha or empty). Fails closed on any error other than "branch absent".
#   college_ledger.sh push  DIR MSG [F...] -> commits DIR/ledger.json (+ files F, given relative to DIR) on top of DIR/parent and pushes WITHOUT force:
#                                            a concurrent or rewritten ledger makes the push fail instead of being overwritten.
set -euo pipefail
BR=college-direct-ledger; cmd=$1; dir=$2; mkdir -p "$dir"
case "$cmd" in
  fetch)
    set +e; git ls-remote --exit-code --heads origin "$BR" >/dev/null; rc=$?; set -e
    if [ "$rc" = 0 ]; then
      git fetch -q --no-tags origin "+refs/heads/$BR:refs/remotes/origin/$BR"
      git rev-parse "refs/remotes/origin/$BR" > "$dir/parent"
      git show "refs/remotes/origin/$BR:ledger.json" > "$dir/ledger.json"
    elif [ "$rc" = 2 ]; then
      echo "ledger branch absent: first use" >&2; : > "$dir/parent"; rm -f "$dir/ledger.json"
    else
      echo "::error::cannot read the ledger branch (git ls-remote exit $rc): refusing to assume an empty ledger"; exit 1
    fi ;;
  push)
    msg=$3; shift 3; parent=$(cat "$dir/parent")
    export GIT_INDEX_FILE="$dir/.index" GIT_AUTHOR_NAME=github-actions GIT_AUTHOR_EMAIL=actions@users.noreply.github.com
    export GIT_COMMITTER_NAME=github-actions GIT_COMMITTER_EMAIL=actions@users.noreply.github.com
    rm -f "$GIT_INDEX_FILE"; if [ -n "$parent" ]; then git read-tree "$parent"; else git read-tree --empty; fi
    for f in ledger.json "$@"; do
      case "$f" in *..*|/*) echo "::error::bad path $f"; exit 1;; esac
      git update-index --add --cacheinfo "100644,$(git hash-object -w "$dir/$f"),$f"
    done
    tree=$(git write-tree)
    commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "$msg")
    git push -q origin "$commit:refs/heads/$BR"
    echo "$commit" > "$dir/parent"; echo "ledger pushed: $commit" ;;
  *) echo "usage: $0 fetch|push DIR ..." >&2; exit 2 ;;
esac
