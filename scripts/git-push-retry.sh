#!/usr/bin/env bash
# Retry `git push` until it succeeds (or 30 attempts).
# Plane wifi loses GitHub connections constantly; this just keeps trying.
#
# Usage: bash scripts/git-push-retry.sh [git push args...]

set -u
max=30
n=0
delay=5
while (( n < max )); do
  n=$((n + 1))
  echo "[attempt $n/$max] git push $*"
  if git push "$@"; then
    echo "pushed"
    exit 0
  fi
  echo "push failed; sleeping ${delay}s"
  sleep "$delay"
  # back off slightly each retry, cap at 30s
  delay=$(( delay < 30 ? delay + 2 : 30 ))
done
echo "gave up after $max attempts"
exit 1
