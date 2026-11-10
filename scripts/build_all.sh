#!/usr/bin/env bash
# Full rebuild of the committed example and of results.md:
# pipeline run -> export to examples/ -> mutation check -> results.md (runs all tests).
# On a shared machine, wrap it once:  flock /path/to/lock scripts/build_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
set +e
$PY -m vidpipe run examples/how-to-read-an-invoice/brief.json
status=$?
set -e
[ "$status" -eq 0 ] || { echo "example video is BLOCKED by QC (exit $status): not exported"; exit "$status"; }
$PY -m vidpipe export runs/how-to-read-an-invoice examples/how-to-read-an-invoice
$PY scripts/mutation_check.py
$PY scripts/make_results.py
scripts/make_preview.sh
