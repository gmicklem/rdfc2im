#!/usr/bin/env bash
# Generate the JBrowse 2 config for the demo mine: $FRONT_HOME/jbrowse2/config.json, which the
# jbrowse2 container serves as /config.json (mounted read-only). The config lists the mine's
# tracks, read from <mine>/service/jbrowse/config/<taxon>/trackList.json, so the mine must be up.
# When it is not, the last generated config stays; with none yet, the config committed in
# repos/jbrowse2 (public mines only) is copied so the container can start.
#
#   gen-jbrowse-config.sh              # MINE_URL, TAXON and JBROWSE2_SRC from the environment
#
# MINE_URL is what the BROWSER uses to reach the mine's web service (it is written into the
# config's adapters), not what this sandbox uses: the demo mine's port 18090 is published 1:1,
# so the same http://localhost:18090/humanmine works from the Mac.
set -euo pipefail
FRONT_HOME="${FRONT_HOME:-${HOME:-/tmp}/.cache/rdfc2im-front}"
JBROWSE2_SRC="${JBROWSE2_SRC:-/Users/gos/claude_projects/update_intermine_planning/repos/jbrowse2}"
MINE_URL="${MINE_URL:-http://localhost:18090/humanmine}"
TAXON="${TAXON:-9606}"
OUT="$FRONT_HOME/jbrowse2/config.json"
mkdir -p "$FRONT_HOME/jbrowse2"
tmp="$OUT.new"
if node "$JBROWSE2_SRC/config/generate.mjs" "$MINE_URL" "$TAXON" -o "$tmp"; then
  # written in place (not mv): the container bind-mounts this file, and a new inode would not show
  cat "$tmp" > "$OUT"
  rm -f "$tmp"
  chmod a+r "$OUT"
  echo "jbrowse2 config: generated from $MINE_URL (taxon $TAXON) -> $OUT"
else
  rm -f "$tmp"
  if [ -f "$OUT" ]; then
    echo "jbrowse2 config: mine not reachable at $MINE_URL; keeping the last generated $OUT" >&2
  else
    cat "$JBROWSE2_SRC/docker/config.json" > "$OUT"
    chmod a+r "$OUT"
    echo "jbrowse2 config: mine not reachable at $MINE_URL; using the committed public-mines config as a placeholder; re-run $0 once the mine is up" >&2
  fi
fi
