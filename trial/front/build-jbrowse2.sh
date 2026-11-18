#!/usr/bin/env bash
# Build the JBrowse 2 image (rdfc2im-jbrowse2:latest) from the repos/jbrowse2 checkout, unmodified.
#
# repos/jbrowse2/Dockerfile downloads the jbrowse-web release (curl, https) and builds the plugin
# (npm ci). Behind the sandbox's TLS-inspecting proxy both fail ("self-signed certificate in
# certificate chain") because the build containers do not trust the proxy's CA. So this script
# builds from a copy of the committed tree (git archive HEAD) whose Dockerfile gets the host's CA
# bundle added after each FROM line. Nothing in the checkout changes. On a machine without a
# TLS-inspecting proxy, `docker build` in the checkout works as it stands.
#
#   build-jbrowse2.sh [--smoke]     --smoke also runs docker/smoke-test.sh from the patched copy
#
# Env: JBROWSE2_SRC (default repos/jbrowse2 next to the planning checkout), FRONT_HOME, IMAGE.
set -euo pipefail
FRONT_HOME="${FRONT_HOME:-${HOME:-/tmp}/.cache/rdfc2im-front}"
JBROWSE2_SRC="${JBROWSE2_SRC:-/Users/gos/claude_projects/update_intermine_planning/repos/jbrowse2}"
IMAGE="${IMAGE:-rdfc2im-jbrowse2:latest}"
CA_BUNDLE="${BUILD_CA_BUNDLE-${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}}"   # empty: no CA injection
WORK="$FRONT_HOME/jbrowse2-build"

[ -f "$JBROWSE2_SRC/Dockerfile" ] || { echo "JBROWSE2_SRC=$JBROWSE2_SRC has no Dockerfile" >&2; exit 1; }
rm -rf "$WORK"
mkdir -p "$WORK"
git -C "$JBROWSE2_SRC" archive HEAD | tar -x -C "$WORK"
BUILD_ARGS=()
if [ -n "${https_proxy:-}" ]; then
  BUILD_ARGS+=(--build-arg "https_proxy=$https_proxy" --build-arg "http_proxy=${http_proxy:-$https_proxy}")
fi
if [ -n "$CA_BUNDLE" ] && [ -f "$CA_BUNDLE" ]; then
  cat "$CA_BUNDLE" > "$WORK/ca.crt"
  python3 -I - "$WORK/Dockerfile" <<'PY'
import re, sys
p = sys.argv[1]
text = open(p).read()
env = "ENV SSL_CERT_FILE=/ca.crt CURL_CA_BUNDLE=/ca.crt NODE_EXTRA_CA_CERTS=/ca.crt"
new, n = re.subn(r"^(FROM [^\n]+\n)", r"\1COPY ca.crt /ca.crt\n" + env + "\n", text, flags=re.M)
if n < 2:
    sys.exit(f"{p}: expected several FROM lines, patched {n}")
open(p, "w").write(new)
PY
fi
docker build "${BUILD_ARGS[@]}" -t "$IMAGE" "$WORK"
echo "built $IMAGE"
if [ "${1:-}" = "--smoke" ]; then
  # the smoke test builds its own image (cached by now) from its parent directory
  bash "$WORK/docker/smoke-test.sh"
fi
