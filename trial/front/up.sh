#!/usr/bin/env bash
# Start (or refresh) the aligner + nginx front: compose project rdfc2im-ut-front.
# Also starts the BlueGenes jar on :15011 when nothing listens there (BG_START=script, empty to skip).
# Port 15001 must be free: stop any bare jar on it first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONT_HOME="${FRONT_HOME:-${HOME:-/tmp}/.cache/rdfc2im-front}"
IMJS_VERSION=4.0.0
IMJS_TGZ_SHA256=18d0e131720bf916855248e2ca62cabe9b467a08c68da30e26458d577457ca09
IMJS_FILE_SHA256=21f4ebf045bb7cf447a9ea1f82efc57f91208f1ba125afc52f7a198acb3fb8db
export ALIGNER_SRC="${ALIGNER_SRC:-/Users/gos/claude_projects/update_intermine_planning/repos/sequence-alignment-service}"
export IMJS_DIR="$FRONT_HOME/imjs"

[ -f "$ALIGNER_SRC/Dockerfile" ] || { echo "ALIGNER_SRC=$ALIGNER_SRC has no Dockerfile" >&2; exit 1; }
mkdir -p "$IMJS_DIR"
sha() { sha256sum "$1" | cut -d' ' -f1; }
if [ ! -f "$IMJS_DIR/im.min.js" ] || [ "$(sha "$IMJS_DIR/im.min.js")" != "$IMJS_FILE_SHA256" ]; then
  tgz="$FRONT_HOME/imjs-$IMJS_VERSION.tgz"
  curl -fsSL -o "$tgz" "https://registry.npmjs.org/imjs/-/imjs-$IMJS_VERSION.tgz"
  [ "$(sha "$tgz")" = "$IMJS_TGZ_SHA256" ] || { echo "imjs tarball checksum mismatch" >&2; exit 1; }
  tar xzf "$tgz" -O package/dist/im.min.js > "$IMJS_DIR/im.min.js"
  [ "$(sha "$IMJS_DIR/im.min.js")" = "$IMJS_FILE_SHA256" ] || { echo "im.min.js checksum mismatch" >&2; exit 1; }
fi
chmod -R a+rX "$FRONT_HOME"
# BlueGenes jar on 15011 (the front proxies to it). Started detached (setsid nohup) so it
# outlives this shell; skipped when something already listens there or BG_START is empty.
BG_START="${BG_START-/home/agent/taskhomes/im-bg-serve/start-15011.sh}"
if [ -n "$BG_START" ] && ! lsof -ti tcp:15011 -sTCP:LISTEN >/dev/null 2>&1; then
  setsid nohup "$BG_START" >/dev/null 2>&1 </dev/null &
  for i in $(seq 1 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:15011/ || true)" = 200 ] && break; sleep 2
  done
fi
# JBrowse 2 (served at /jbrowse2/): the image is built once from the repos/jbrowse2 checkout
# (REBUILD_JBROWSE2=1 forces it), and its config is generated from the mine when the mine is up;
# a mine that is down leaves the last generated config in place (gen-jbrowse-config.sh).
if [ -n "${REBUILD_JBROWSE2:-}" ] || ! docker image inspect rdfc2im-jbrowse2:latest >/dev/null 2>&1; then
  bash "$HERE/build-jbrowse2.sh"
fi
bash "$HERE/gen-jbrowse-config.sh"
export JBROWSE2_CONFIG="$FRONT_HOME/jbrowse2/config.json"
# A broken nginx.conf must not take :15001 down: test it in a throwaway container first
# (the upstreams are IP addresses, so nothing has to be running for `nginx -t`).
docker run --rm --network host -v "$HERE/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t
docker compose -f "$HERE/docker-compose.yml" -p rdfc2im-ut-front up -d --build
# compose leaves a running nginx alone when only the file's content changed: reload it
docker exec rdfc2im-ut-front-nginx nginx -s reload
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:15001/vendor/imjs/im.min.js || true)
  [ "$code" = 200 ] && break; sleep 1
done
echo "front: /vendor/imjs/im.min.js -> $code; /jbrowse2/ ->" \
     "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:15001/jbrowse2/ || true); BlueGenes upstream:" \
     "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:15011/ || true) (200 expected)"
