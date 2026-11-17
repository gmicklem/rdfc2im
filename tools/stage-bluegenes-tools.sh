#!/bin/sh
# Make the patched BlueGenes tool set (RCSB v1->v2, MSA same-origin, JBrowse 2 tool) and optionally
# install it into a tool store. A thin wrapper; the logic and its documentation are in
# rdfc2im/bgtools.py. Usage:
#   tools/stage-bluegenes-tools.sh --jbrowse2-src DIR --out DIR [--install-to TOOLS_DIR] [--build WORKDIR]
# Run from the checkout root (the default --src-cache is cached_raw_data/bluegenes-tools/data).
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-python3}
cd "$here"
exec "$PY" -m rdfc2im.bgtools "$@"
