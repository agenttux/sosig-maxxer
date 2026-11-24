#!/usr/bin/env bash
# Download 8 CC BY 4.0 songs (Kevin MacLeod, incompetech.com; ~49 MB) into analysis/corpus/local/songs/
# (gitignored) and cut three 3.5 s clips from each (at 25/50/75%) for compare.py. Local use only.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dst="$here/local/songs"
mkdir -p "$dst"
for t in "Funkorama" "Hitman" "Volatile Reaction" "Local Forecast - Elevator" "Galactic Rap" "Werq" \
         "Five Armies" "Ether Vox"; do
  [ -f "$dst/$t.mp3" ] || curl -sSfL -o "$dst/$t.mp3" \
    "https://incompetech.com/music/royalty-free/mp3-royaltyfree/${t// /%20}.mp3"
done
echo "Songs by Kevin MacLeod (incompetech.com), CC BY 4.0. Local measurement only." > "$dst/CREDITS.txt"
cd "$here/.."
"${PYTHON:-../.venv/bin/python}" -c "
import glob, soundfile as sf, corpus
for p in sorted(glob.glob('corpus/local/songs/*.mp3')):
    x = corpus.read(p); n, L = x.shape[1], int(3.5 * 48000)
    for k, pos in enumerate((0.25, 0.5, 0.75)):
        s = int(pos * n); sf.write(p[:-4] + f'_{k}.wav', x[:, s:s + L].T, 48000, subtype='FLOAT')
"
echo "clips in $dst"
