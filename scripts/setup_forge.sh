#!/usr/bin/env bash
# Fetch the Solidity our tick math is differential-tested against.
#
# These are plain shallow clones rather than git submodules, and vetting/forge/lib
# is gitignored: the reference implementation is a build input, not part of this
# repository's history. The commits are pinned in ops/forge_deps.txt so a vector
# regenerated next month comes from the same code as one generated today.
set -euo pipefail

cd "$(dirname "$0")/.."
LIB="vetting/forge/lib"
PINS="ops/forge_deps.txt"

if ! command -v forge >/dev/null 2>&1; then
  echo "forge not found — install foundry from https://getfoundry.sh"
  echo "(skipping Solidity setup; 'make test' still runs against the committed vectors)"
  exit 0
fi

mkdir -p "$LIB"

fetch() {
  local name="$1" repo="$2" pin
  pin="$(awk -v n="$name" '$1 == n { print $2 }' "$PINS" 2>/dev/null || true)"

  if [ -d "$LIB/$name/.git" ]; then
    if [ -n "$pin" ] && [ "$(git -C "$LIB/$name" rev-parse HEAD)" = "$pin" ]; then
      echo "  $name already at pinned commit"
      return
    fi
    rm -rf "${LIB:?}/$name"
  fi

  echo "  cloning $name"
  if [ -n "$pin" ]; then
    # A shallow clone cannot check out an arbitrary commit, so fetch that one
    # object directly. Falls back to the default branch if the pin has been
    # garbage-collected upstream, which is loud rather than silent.
    git init -q "$LIB/$name"
    git -C "$LIB/$name" remote add origin "https://github.com/$repo.git"
    if git -C "$LIB/$name" fetch -q --depth 1 origin "$pin" 2>/dev/null; then
      git -C "$LIB/$name" checkout -q FETCH_HEAD
    else
      echo "    pinned commit $pin unavailable; falling back to default branch"
      git -C "$LIB/$name" fetch -q --depth 1 origin HEAD
      git -C "$LIB/$name" checkout -q FETCH_HEAD
    fi
  else
    git clone -q --depth 1 "https://github.com/$repo.git" "$LIB/$name"
  fi
}

echo "solidity reference sources:"
fetch forge-std     foundry-rs/forge-std
fetch v3-core       Uniswap/v3-core
fetch v3-periphery  Uniswap/v3-periphery

forge build --root vetting/forge
