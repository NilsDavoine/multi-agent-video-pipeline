#!/usr/bin/env bash
# docs/preview.gif: the whole example video as an animated GIF for the README
# (640x360, 10 fps, 128-colour palette, no sound; about 2 MB).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs
ffmpeg -v error -y -i examples/how-to-read-an-invoice/final.mp4 \
  -vf "fps=10,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 docs/preview.gif
ls -l docs/preview.gif
