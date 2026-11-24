#!/usr/bin/env bash
# Release helpers (Forgejo API). Env: GITHUB_SERVER_URL, GITHUB_REPOSITORY, and TOKEN or CURL_CONFIG.
#   release.sh set-version 1.2.3      stamp version into Cargo.toml (CI only, not committed)
#   release.sh release v1.2.3         print release id for tag, creating it if missing
#   release.sh upload <id> <file>...  attach files to a release
set -euo pipefail
api="${GITHUB_SERVER_URL:-}/api/v1/repos/${GITHUB_REPOSITORY:-}"
if [ -n "${CURL_CONFIG:-}" ]; then auth=(-K "$CURL_CONFIG"); else auth=(-H "Authorization: token ${TOKEN:-}"); fi
json_id() { node -pe 'JSON.parse(require("fs").readFileSync(0, "utf8")).id'; }

case "$1" in
  set-version)
    [[ "$2" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "bad version: $2" >&2; exit 2; }
    V=$2 perl -pi -e 's/^version = "[^"]*"/version = "$ENV{V}"/' Cargo.toml
    ;;
  release)
    if ! curl -sf "${auth[@]}" "$api/releases/tags/$2" | json_id 2>/dev/null; then
      prev=$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' "$2^" 2>/dev/null || true)
      body=$(git log --format='- %s' "${prev:+$prev..}$2")
      node -e 'const [t, b] = process.argv.slice(1); console.log(JSON.stringify({ tag_name: t, name: t, body: b }))' "$2" "$body" |
        curl -sf "${auth[@]}" -H 'Content-Type: application/json' -d @- "$api/releases" | json_id
    fi
    ;;
  upload)
    id=$2; shift 2
    for f in "$@"; do
      out=$(curl -sS --fail-with-body "${auth[@]}" -F "attachment=@$f" "$api/releases/$id/assets?name=$(basename "$f")") ||
        { echo "upload of $(basename "$f") failed: $out" >&2; exit 1; }
      echo "uploaded $(basename "$f")"
    done
    ;;
  *) echo "usage: $0 set-version|release|upload ..." >&2; exit 2 ;;
esac
