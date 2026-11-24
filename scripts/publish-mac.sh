#!/usr/bin/env bash
# Build the macOS plugins (universal: arm64 + x86_64, ad-hoc signed) for a release tag on this Mac and
# attach the zip to that Forgejo release.
#   scripts/publish-mac.sh               newest v* tag on origin
#   scripts/publish-mac.sh --after v1.2  wait (up to 30 min) for CI to tag a newer version first
# Auth: FORGEJO_TOKEN if set, else the git credential stored for the origin host.
set -euo pipefail
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
repo=$(git rev-parse --show-toplevel)
cd "$repo"

latest_tag() { git ls-remote --tags --refs origin 'v*' | sed 's#.*refs/tags/##' | sort -V | tail -1; }

tag=$(latest_tag)
if [ "${1:-}" = --after ]; then
  for _ in $(seq 60); do
    tag=$(latest_tag)
    [ "$tag" != "$2" ] && break
    sleep 30
  done
  [ "$tag" = "$2" ] && { echo "no new tag after $2, giving up"; exit 1; }
fi
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "bad tag: $tag"; exit 1; }
echo "publishing macOS build for $tag"

# Forgejo API address from origin (https://host/owner/repo.git).
url=$(git remote get-url origin)
host=$(echo "$url" | sed -E 's#^https?://([^/]+)/.*#\1#')
export GITHUB_SERVER_URL="https://$host"
export GITHUB_REPOSITORY=$(echo "$url" | sed -E 's#^https?://[^/]+/##; s#\.git$##')

# Credentials go in a private curl config file, never on the command line.
tmp=$(mktemp -d)
trap 'git worktree remove --force "$tmp/src" 2>/dev/null || true; rm -rf "$tmp"' EXIT
umask 077
if [ -n "${FORGEJO_TOKEN:-}" ]; then
  echo "header = \"Authorization: token $FORGEJO_TOKEN\"" > "$tmp/curl.cfg"
else
  cred=$(printf 'protocol=https\nhost=%s\n\n' "$host" | git credential fill)
  user=$(echo "$cred" | sed -n 's/^username=//p')
  pass=$(echo "$cred" | sed -n 's/^password=//p')
  echo "user = \"$user:$pass\"" > "$tmp/curl.cfg"
fi
export CURL_CONFIG="$tmp/curl.cfg"

# Wait for CI to create the release so we never race it into a duplicate.
api="$GITHUB_SERVER_URL/api/v1/repos/$GITHUB_REPOSITORY"
for _ in $(seq 20); do
  rel=$(curl -sf -K "$CURL_CONFIG" "$api/releases/tags/$tag" || true)
  [ -n "$rel" ] && break
  sleep 30
done
[ -n "$rel" ] || { echo "release $tag not found"; exit 1; }
if echo "$rel" | grep -q 'macos-universal\.zip"'; then echo "$tag already has a macOS zip"; exit 0; fi

git fetch -q origin main "refs/tags/$tag:refs/tags/$tag"
# Only build tags CI cut from main; refuses a tag pushed elsewhere by someone with tag rights.
git merge-base --is-ancestor "$tag^{commit}" FETCH_HEAD || { echo "$tag is not on origin/main"; exit 1; }
git worktree add -q --detach "$tmp/src" "$tag"
cd "$tmp/src"
export CARGO_TARGET_DIR="$repo/target" # reuse the normal build cache
bash scripts/release.sh set-version "${tag#v}"
rustup target add aarch64-apple-darwin x86_64-apple-darwin >/dev/null
cargo xtask bundle-universal sosig_maxxer --release
out="$tmp/sosig-maxxer-${tag#v}-macos-universal.zip"
(
  cd "$CARGO_TARGET_DIR/bundled"
  for b in "Sosig Maxxer.vst3" "Sosig Maxxer.clap"; do codesign --force --deep -s - "$b"; done
  zip -qry "$out" "Sosig Maxxer.vst3" "Sosig Maxxer.clap"
)
id=$(bash scripts/release.sh release "$tag")
bash scripts/release.sh upload "$id" "$out"
osascript -e "display notification \"$(basename "$out") uploaded to $tag\" with title \"Sosig Maxxer\"" 2>/dev/null || true
