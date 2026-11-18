#!/usr/bin/env bash
# Stop and remove the aligner + nginx front (project rdfc2im-ut-front). Leaves the mine stack alone.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ALIGNER_SRC="${ALIGNER_SRC:-unused}" IMJS_DIR="${IMJS_DIR:-unused}" JBROWSE2_CONFIG="${JBROWSE2_CONFIG:-unused}"
docker compose -f "$HERE/docker-compose.yml" -p rdfc2im-ut-front down
