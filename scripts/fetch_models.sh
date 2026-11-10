#!/usr/bin/env bash
# Downloads the local open-weight models the pipeline needs, and checks their hashes.
#  - Kokoro-82M v1.0 (Apache-2.0), int8 ONNX export by thewh1teagle/kokoro-onnx: text-to-speech
#  - faster-whisper "small" (MIT) is fetched automatically by faster-whisper on first use.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models
base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  [ -f "models/$f" ] || curl -sSL -o "models/$f" "$base/$f"
done
sha256sum -c <<'SUMS'
6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb  models/kokoro-v1.0.int8.onnx
bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d  models/voices-v1.0.bin
SUMS
