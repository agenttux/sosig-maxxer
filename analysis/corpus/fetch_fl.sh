#!/usr/bin/env bash
# Copy a curated set of FL Studio factory samples into analysis/corpus/local/ (gitignored).
# Image-Line content: used for local measurement only, never committed or shipped.
set -euo pipefail
src="${FL_PACKS:-/Applications/FL Studio 2026.app/Contents/Resources/FL/Data/Patches/Packs}"
dst="$(cd "$(dirname "$0")" && pwd)/local"
[ -d "$src" ] || { echo "FL packs not found at $src (set FL_PACKS)" >&2; exit 1; }
mkdir -p "$dst"

# category|subdir|count (first N wavs, sorted, for reproducibility)
while IFS='|' read -r cat dir n; do
  mkdir -p "$dst/$cat"
  find "$src/$dir" -maxdepth 1 -type f -iname '*.wav' | sort | head -n "$n" |
    while IFS= read -r f; do cp "$f" "$dst/$cat/"; done
done <<'EOF'
kick|Drums/Kicks|6
kick|Drums (ModeAudio)/Kicks|4
snare|Drums/Snares|4
hats|Drums/Hats|4
bass|Instruments/Bass|8
keys|Instruments/Keyboard|4
guitar|Instruments/Guitar|2
vocal|Vocals|10
loop|Loops|15
EOF

# Bass/keys/guitar packs keep samples in subfolders: top up from one level down.
for cat in bass keys guitar; do
  have=$(find "$dst/$cat" -type f | wc -l)
  if [ "$have" -lt 4 ]; then
    case $cat in bass) dir=Instruments/Bass;; keys) dir=Instruments/Keyboard;; guitar) dir=Instruments/Guitar;; esac
    find "$src/$dir" -mindepth 2 -type f -iname '*.wav' | sort | awk 'NR%7==1' | head -n 6 |
      while IFS= read -r f; do cp "$f" "$dst/$cat/"; done
  fi
done

python3 - "$dst" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
items = []
for dp, _, fs in sorted(os.walk(root)):
    for f in sorted(fs):
        if f.lower().endswith(".wav"):
            p = os.path.join(dp, f)
            items.append({"path": os.path.relpath(p, root), "category": os.path.relpath(dp, root),
                          "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()})
json.dump(items, open(os.path.join(root, "manifest.json"), "w"), indent=1)
print(f"{len(items)} files -> {root}")
PY
