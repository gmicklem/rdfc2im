#!/usr/bin/env bash
# Full build: RDF Portal -> a running, fully-configured demonstration HumanMine.
#
# Encodes, as one script, the sequence LOAD-TRIAL.md records happening by hand over many
# sessions: the rdfc2im pipeline per source, the InterMine mine build, postprocessing, Solr,
# BlueGenes, and the demo templates. This is the paper's #1 Future Work item ("Script the whole
# build"). See RESTART.md and STATUS.md's "Where this stands" for the wider project context.
#
# Usage:
#   tools/full-build.sh [options]
#
# Options:
#   --dry-run           Print every command instead of running it. Always start here.
#   --from PHASE        Start at PHASE instead of the beginning (see --list-phases).
#   --only PHASE        Run exactly one phase, then stop.
#   --list-phases       Print the phase names, in order, and exit.
#   --sources "a b c"   Space-separated source list (default: the 9-source demo panel).
#   --genes FILE        Gene-panel file for --genes-scoped sources (default: demo panel).
#   --taxon LIST        Comma-separated NCBI taxon ids, passed to rdfc2im --taxon (default: 9606).
#   --skip-templates    Don't apply curation/demo_public_templates.sql.
#   --use-cached-data   Restore the fetched raw data (SPARQL results, the Reactome download) from
#                       cached_raw_data/ instead of fetching it again. Every file is checked
#                       against its md5 first, and a cache fetched for a different gene panel,
#                       taxon or source scope is refused. Without this option the data is fetched
#                       and then saved there, so the next build can reuse it.
#                       Network is still used for what is not cached: the upstream clones in
#                       $UPSTREAM_CACHE are made when missing (and left alone when present, no pull).
#   --offline           --use-cached-data plus a guarantee of no network request in the data
#                       phases (fetch_inputs, rdfc2im_pipeline, rdfc2im_project): a SPARQL request
#                       raises OfflineError naming the endpoint, a gene-symbol lookup missing from
#                       the cache names the file, a missing upstream clone is an error. Implies
#                       --use-cached-data. Also on when the caller exports RDFC2IM_OFFLINE=1.
#   --cache-dir DIR     Where that cache lives (default: cached_raw_data/ in this repo).
#   --reactome-levels L  "default" (the lowest-level UniProt2Reactome.txt Reactome publishes -
#                       leaf pathways only) or "all" (UniProt2Reactome_All_Levels.txt: every
#                       ancestor pathway also gets its descendants' proteins/genes, matching how
#                       reactome.org itself presents a pathway). Default: default.
#   --intermine-src DIR  Build the mine from the InterMine checkout DIR instead of the published
#                       5.0.x artefacts: the Gradle plugin, the org.intermine:* jars, the bio
#                       sources and the bio-webapp/intermine-webapp wars all come from DIR, at its
#                       version (gradle/libs.versions.toml). DIR is only read: phase
#                       publish_intermine copies it to $TRIAL_HOME/intermine-src and publishes its
#                       builds into the private Maven repo $TRIAL_HOME/m2-intermine, and every
#                       Gradle call then resolves mavenLocal() there (-Dmaven.repo.local), never
#                       from a shared ~/.m2. The humanmine checkout gets DIR's version, DIR's
#                       Gradle wrapper (config/lib/install_intermine.py DEFAULT_GRADLE_VERSION) and
#                       the deployer edits of DIR's docs/UPGRADING-build.md, each one logged as
#                       "deployer edit". RDF Portal data, BlueGenes and everything else are as
#                       without the option.
#   --stack-name NAME   Run a second, independent Compose stack beside the default one: containers
#                       and volumes are named rdfc2im-NAME-* (RDFC2IM_PREFIX), the Compose project
#                       is rdfc2im-NAME (COMPOSE_PROJECT_NAME), and the host ports default to
#                       25432/18983/18090/15000 (PG/Solr/mine/BlueGenes) instead of
#                       15432/8983/8090/5000 - each still overridable by its own variable. Use
#                       its own TRIAL_HOME and HOME too (the mine's ~/.intermine/humanmine.properties
#                       carries the ports). check_prereqs refuses to start if a port is already
#                       published by a container that is not this stack's.
#   -h, --help          This text.
#
# Every side-effecting external command (gradle, docker, psql, curl) is emitted through `run`,
# which is a no-op printer under --dry-run - so --dry-run is a real dry run of the *exact*
# command sequence, not a separate code path that could drift from what actually executes.
#
# Environment (all overridable; defaults match this project's own trial setup):
#   LOG_DIR           Where build-<run-id>.{log,status,timing.tsv} go. Default: .build-logs/ in
#                     this repo (gitignored), so a host or second terminal sharing the checkout
#                     can run tools/watch-build.sh without any setup.
#   TRIAL_HOME        Scratch directory for the humanmine/humanmine-bio-sources checkouts and
#                     gradle build outputs. Not the rdfc2im repo - keep build noise separate.
#                     Default: ~/intermine-build/trial_home (matches .trial-home if present).
#   UPSTREAM_CACHE    Where tools/make-inputs.sh clones rdf-config/intermine/humanmine/
#                     humanmine-bio-sources from. Default: in/.upstream (see that script).
#   JAVA8_HOME        A JDK 8 install. Gradle 4.9 (this mine's build tooling) cannot start a
#                     daemon under anything newer - confirmed live, see LOAD-TRIAL.md's hgnc
#                     section. No default; the script fails fast in phase_check_prereqs if unset
#                     and not discoverable.
#   GRADLE49          Path to a Gradle 4.9 launcher (the mine checkout's own ./gradlew is used
#                     when present, matching every invocation recorded in LOAD-TRIAL.md; this is
#                     a fallback only).
#   COMPOSE           Docker Compose invocation. Default: "docker compose" (this project's own
#                     trial stack was built and proven against Docker specifically, not podman -
#                     see STATUS/handoff notes on this sandbox's environment).
#   PG_PORT, BG_PORT, SOLR_PORT, MINE_PORT   Host ports for the four published services.
#                     Defaults match trial/docker-compose.yml: 15432, 5000, 8983, 8090 (with
#                     --stack-name: 25432, 15000, 18983, 18090). MINE_PORT is also the port Tomcat
#                     listens on inside its container and the one in webapp.baseurl, because the
#                     webapp fetches its own query.xsd from webapp.baseurl. A SOLR_PORT other than
#                     8983 is written into the mine's two Solr URLs (keyword_search.properties,
#                     objectstoresummary.config.properties), so postprocess indexes into this
#                     stack's Solr and not another stack's.
#   RDFC2IM_PREFIX    Container and volume name prefix (default rdfc2im; see --stack-name).
#   COMPOSE_PROJECT_NAME  Passed through to Compose when set (default: unset, so the project is
#                     `trial`, the compose file's directory).
#   BIND_ADDR         Host address the compose stack's ports are published on. Default 127.0.0.1
#                     (matches the tracked trial/docker-compose.yml - reach it via `ssh -L`, see
#                     LOAD-TRIAL.md "Connecting"). Set to 0.0.0.0 only if you know your sandbox's
#                     access model needs it (e.g. `sbx ports` rather than SSH) - this writes a
#                     LOCAL, untracked compose override, never the shared tracked file.
#   INTERMINE_JAVA_HOME  JDK for building the --intermine-src checkout (default: JAVA8_HOME).
#   MINE_TITLE        Display name baked into the webapp and BlueGenes. Default matches the demo
#                     panel; override for a differently-scoped build.
#
# phase_resolve_bluegenes_deps was a reasoned reconstruction (LOAD-TRIAL.md recorded only the
# *result* of resolving BlueGenes' Clojure dependencies - "178 jars" - not the exact command) -
# now confirmed live (2026-09-21, outside this script, before any real build attempt): the
# throwaway-project approach below, run standalone with Gradle 4.9 / JDK 8, resolves
# org.intermine:bluegenes:1.4.5 from Clojars + Maven Central to exactly 178 jars, matching
# LOAD-TRIAL.md's number exactly. No longer a guess.
set -euo pipefail

# ============================================================== configuration
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"

TRIAL_HOME=${TRIAL_HOME:-}
if [ -z "$TRIAL_HOME" ] && [ -f "$HERE/.trial-home" ]; then TRIAL_HOME=$(cat "$HERE/.trial-home"); fi
TRIAL_HOME=${TRIAL_HOME:-"$HOME/intermine-build/trial_home"}
UPSTREAM_CACHE=${UPSTREAM_CACHE:-"$HERE/in/.upstream"}
JAVA8_HOME=${JAVA8_HOME:-}
GRADLE49=${GRADLE49:-gradle}
COMPOSE=${COMPOSE:-"docker compose"}
STACK_NAME=${STACK_NAME:-}
INTERMINE_SRC=${INTERMINE_SRC:-}
# With --intermine-src on the 6.0 line (Gradle 8) the mine's build files are the converted ones of
# this branch of the HumanMine fork (see _upgrade_mine_build), not upstream master's.
HUMANMINE_60_URL=${HUMANMINE_60_URL:-https://github.com/gmicklem/humanmine.git}
HUMANMINE_60_REF=${HUMANMINE_60_REF:-maint-2026}
BIND_ADDR=${BIND_ADDR:-127.0.0.1}
MINE_TITLE=${MINE_TITLE:-"rdfc2im: 113 gene food/drug-metabolism panel"}

# The demo panel this project actually built and verified this session (STATUS.md Table 2 /
# LOAD-TRIAL.md). Each source's scope mode decides which rdfc2im CLI flags it gets in
# phase_rdfc2im_pipeline - see that function. Override with --sources for a different build.
SOURCES=${SOURCES:-"go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed"}
GENE_PANEL=${GENE_PANEL:-"$HERE/curation/demo_gene_panel.txt"}
TAXON=${TAXON:-9606}
SKIP_TEMPLATES=0
USE_CACHED_DATA=0
OFFLINE=0
[ "${RDFC2IM_OFFLINE:-}" = 1 ] && { OFFLINE=1; USE_CACHED_DATA=1; }
RAW_CACHE_DIR=${RAW_CACHE_DIR:-"$HERE/cached_raw_data"}
REACTOME_LEVELS=${REACTOME_LEVELS:-default}
DRY_RUN=0
LIST_PHASES=0
FROM_PHASE=""
ONLY_PHASE=""

# Scope mode per source: full (no restriction), panel (--genes), pmid (--pmids from citing
# sources' own already-fetched data), none (not gene/organism-shaped - ontologies, pubmed itself
# takes --pmids separately). Matches STATUS.md Table 2 / LOAD-TRIAL.md exactly - do not add a
# source here without also adding its scope mode, or it silently gets a full, unscoped fetch.
declare -A SCOPE_MODE=(
  [go]=none [hpo]=none [mp]=none [uberon]=none [mesh]=none [homologene]=none [expressionatlas]=none
  [ncbigene]=panel [reactome]=full
  [hgnc]=panel [ensembl]=panel [uniprot]=panel [clinvar]=panel [gwascatalog]=panel
  [pubmed]=pmid
)

# In the repository (gitignored), not under $TRIAL_HOME: TRIAL_HOME is usually inside a sandbox's or
# build machine's private home, and the repository is the one directory a person watching from
# another machine or a host terminal shares with the build - `tools/watch-build.sh` there just works.
LOG_DIR=${LOG_DIR:-"$HERE/.build-logs"}
RUN_ID=${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
LOGFILE="$LOG_DIR/build-$RUN_ID.log"
TIMING_TSV="$LOG_DIR/build-$RUN_ID.timing.tsv"
STATUS_FILE="$LOG_DIR/build-$RUN_ID.status"   # one line, current phase - `watch cat` this for a live view

PHASES=(check_prereqs fetch_inputs rdfc2im_pipeline rdfc2im_project build_humanmine_items
        build_reactome_source prepare_mine_checkout stage_src_data start_databases build_dbmodel
        integrate_sources postprocess build_webapp resolve_bluegenes_deps stage_artifacts
        start_mine_stack apply_templates verify)

# ============================================================== logging & timing
# Every log line goes to both the terminal and $LOGFILE, timestamped, so `tail -f "$LOGFILE"`
# from another shell is a live view of a build in progress, and the file survives after the
# terminal is gone. $TIMING_TSV gets one row per phase (phase, start, end, seconds) for exactly
# the "learn about bottlenecks" use case - `sort -t$'\t' -k4 -rn "$TIMING_TSV"` after a run ranks
# phases by wall-clock cost.
_ts() { date -u +%H:%M:%S; }

log() { printf '%s [%s] %s\n' "$(_ts)" "${CURRENT_PHASE:-main}" "$*" | tee -a "$LOGFILE" >&2; }

die() { log "FATAL: $*"; exit 1; }

# Wraps every side-effecting command. Under --dry-run this only logs; otherwise it logs then
# execs, with the command's own stdout/stderr still tee'd into $LOGFILE so gradle/docker output
# is part of the same live-tailable log, not lost to a separate stream.
run() {
  log "+ $*"
  if [ "$DRY_RUN" -eq 1 ]; then return 0; fi
  "$@" 2>&1 | tee -a "$LOGFILE"
  return "${PIPESTATUS[0]}"
}

# Like `run`, but for a command that must run in a directory an earlier (possibly dry-run-skipped)
# step creates. Plain `( cd "$dir" && run ... )` still executes the real `cd` under --dry-run,
# which fails when that directory doesn't exist yet - found by actually dry-running this script,
# not by inspection. The whole cd-and-run is a no-op together under --dry-run instead.
run_in() {
  local dir=$1; shift
  log "+ (cd $dir && $*)"
  if [ "$DRY_RUN" -eq 1 ]; then return 0; fi
  ( cd "$dir" && "$@" ) 2>&1 | tee -a "$LOGFILE"
  return "${PIPESTATUS[0]}"
}

phase_start() {
  CURRENT_PHASE=$1
  PHASE_T0=$(date +%s)
  echo "$CURRENT_PHASE" > "$STATUS_FILE" 2>/dev/null || true
  log "===== START ====="
}

phase_end() {
  local dt=$(( $(date +%s) - PHASE_T0 ))
  log "===== DONE (${dt}s) ====="
  printf '%s\t%s\t%s\t%s\n' "$CURRENT_PHASE" "$(_ts)" "$dt" "$RUN_ID" >> "$TIMING_TSV"
}

# ============================================================== arg parsing
# The header comment, from Usage to the end of the Environment list.
usage() { awk 'NR > 1 && /^# phase_resolve_bluegenes_deps/ { exit } NR > 1' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --from) FROM_PHASE=$2; shift ;;
    --only) ONLY_PHASE=$2; shift ;;
    --list-phases) LIST_PHASES=1 ;;
    --sources) SOURCES=$2; shift ;;
    --genes) GENE_PANEL=$2; shift ;;
    --taxon) TAXON=$2; shift ;;
    --skip-templates) SKIP_TEMPLATES=1 ;;
    --use-cached-data) USE_CACHED_DATA=1 ;;
    --offline) OFFLINE=1; USE_CACHED_DATA=1 ;;
    --cache-dir) RAW_CACHE_DIR=$2; shift ;;
    --reactome-levels) REACTOME_LEVELS=$2; shift ;;
    --stack-name) STACK_NAME=$2; shift ;;
    --intermine-src) INTERMINE_SRC=$2; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

case "$REACTOME_LEVELS" in
  default|all) ;;
  *) echo "unknown --reactome-levels '$REACTOME_LEVELS' - must be 'default' or 'all'" >&2; exit 2 ;;
esac

# Stack identity and host ports. Set after argument parsing because --stack-name changes the
# defaults: a named stack gets its own container/volume names, its own Compose project and its own
# ports, so it can run beside the default stack without touching it.
if [ -n "$STACK_NAME" ]; then
  case "$STACK_NAME" in *[!a-z0-9-]*|'') echo "--stack-name must be lower-case letters, digits and '-'" >&2; exit 2 ;; esac
  RDFC2IM_PREFIX=${RDFC2IM_PREFIX:-"rdfc2im-$STACK_NAME"}
  COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-"rdfc2im-$STACK_NAME"}
  PG_PORT=${PG_PORT:-25432}; BG_PORT=${BG_PORT:-15000}; SOLR_PORT=${SOLR_PORT:-18983}; MINE_PORT=${MINE_PORT:-18090}
fi
RDFC2IM_PREFIX=${RDFC2IM_PREFIX:-rdfc2im}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-}
PG_PORT=${PG_PORT:-15432}
BG_PORT=${BG_PORT:-5000}
SOLR_PORT=${SOLR_PORT:-8983}
MINE_PORT=${MINE_PORT:-8090}
PG_CONTAINER="$RDFC2IM_PREFIX-postgres"
SOLR_CONTAINER="$RDFC2IM_PREFIX-solr"
MINE_CONTAINER="$RDFC2IM_PREFIX-mine"
# Every compose call gets the stack's names and ports explicitly (trial/docker-compose.yml reads
# them, with the default stack's values as its own defaults).
COMPOSE_ENV=(env PG_PORT="$PG_PORT" SOLR_PORT="$SOLR_PORT" MINE_PORT="$MINE_PORT" BG_PORT="$BG_PORT"
             RDFC2IM_PREFIX="$RDFC2IM_PREFIX")
[ -n "$COMPOSE_PROJECT_NAME" ] && COMPOSE_ENV+=(COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME")

# --intermine-src: versions read from the checkout, never guessed. IM_VERSION is what every
# org.intermine module of that tree publishes (the version catalog; intermine/build.gradle on trees
# from before the catalog), IM_GRADLE_VERSION the Gradle its own wrappers use. Without the option
# the mine keeps its own pins (imVersion/bioVersion 5.0.+, Gradle 4.9) and IM_VERSION stays empty.
IM_VERSION=""; IM_GRADLE_VERSION=""; IM_GRADLE_SHA256=""; IM_LINE=""
if [ -n "$INTERMINE_SRC" ]; then
  INTERMINE_SRC=$(cd "$INTERMINE_SRC" 2>/dev/null && pwd) || { echo "--intermine-src: no such directory" >&2; exit 2; }
  [ -f "$INTERMINE_SRC/config/lib/install_intermine.py" ] ||
    { echo "--intermine-src $INTERMINE_SRC: not an InterMine checkout (no config/lib/install_intermine.py)" >&2; exit 2; }
  if [ -f "$INTERMINE_SRC/gradle/libs.versions.toml" ]; then
    IM_VERSION=$(sed -n 's/^intermine *= *"\([^"]*\)".*/\1/p' "$INTERMINE_SRC/gradle/libs.versions.toml" | head -1)
  fi
  if [ -z "$IM_VERSION" ]; then
    IM_VERSION=$(sed -n "s/^ *version *=\{0,1\} *['\"]\([0-9][^'\"]*\)['\"].*/\1/p" "$INTERMINE_SRC/intermine/build.gradle" | head -1)
  fi
  [ -n "$IM_VERSION" ] || { echo "--intermine-src: cannot read the InterMine version from $INTERMINE_SRC" >&2; exit 2; }
  im_plugin_version=$(sed -n "s/^version *=\{0,1\} *['\"]\([^'\"]*\)['\"].*/\1/p" "$INTERMINE_SRC/plugin/build.gradle" | head -1)
  if [ -n "$im_plugin_version" ] && [ "$im_plugin_version" != "$IM_VERSION" ]; then
    # The mine has one imVersion for both the plugin and the intermine-* jars.
    echo "--intermine-src: plugin version $im_plugin_version differs from the catalog's $IM_VERSION" >&2; exit 2
  fi
  IM_GRADLE_VERSION=$(sed -n 's/^DEFAULT_GRADLE_VERSION *= *"\([^"]*\)".*/\1/p' "$INTERMINE_SRC/config/lib/install_intermine.py")
  [ -n "$IM_GRADLE_VERSION" ] || { echo "--intermine-src: no DEFAULT_GRADLE_VERSION in config/lib/install_intermine.py" >&2; exit 2; }
  IM_GRADLE_SHA256=$(grep -A1 "\"gradle-$IM_GRADLE_VERSION-bin.zip\":" "$INTERMINE_SRC/config/lib/install_intermine.py" |
                     sed -n 's/.*"\([0-9a-f]\{64\}\)".*/\1/p' | head -1)
  # The InterMine line, from the Gradle the checkout's own wrappers use: 8.x is the 6.0 line
  # (maint-2026: plugin composes the war, mines need converted build files), anything older keeps
  # the 5.x behaviour (6.9.4 is the 5.1.1 line).
  if [ "${IM_GRADLE_VERSION%%.*}" -ge 8 ]; then IM_LINE="6.0"; else IM_LINE="5.x"; fi
fi

# Where the --intermine-src artefacts go, and the Gradle arguments that make every build below
# resolve (and install) org.intermine:* there: mavenLocal() honours -Dmaven.repo.local, so the
# humanmine build files keep their repositories unchanged, and nothing can come from (or go to)
# a shared ~/.m2 by accident. INTERMINE_TREE is the InterMine source tree this script reads files
# from (default.intermine.production.properties, bio/sources/reactome): the upstream clone, or
# with --intermine-src the copy publish_intermine built from.
IM_M2="$TRIAL_HOME/m2-intermine"
IM_GRADLE_ARGS=()
INTERMINE_TREE="$UPSTREAM_CACHE/intermine"
INTERMINE_JAVA_HOME=${INTERMINE_JAVA_HOME:-}
if [ -n "$INTERMINE_SRC" ]; then
  IM_GRADLE_ARGS=(-Dmaven.repo.local="$IM_M2")
  INTERMINE_TREE="$TRIAL_HOME/intermine-src"
  # The build of the checkout's own artefacts runs before the mine's first Gradle call.
  PHASES=("${PHASES[@]/#fetch_inputs/fetch_inputs publish_intermine}")
  read -r -a PHASES <<< "${PHASES[*]}"
fi
if [ "$LIST_PHASES" -eq 1 ]; then printf '%s\n' "${PHASES[@]}"; exit 0; fi

mkdir -p "$LOG_DIR"
: > "$TIMING_TSV" 2>/dev/null || true
log "full-build.sh starting - run id $RUN_ID, log $LOGFILE, dry_run=$DRY_RUN"
log "sources: $SOURCES"
log "trial home: $TRIAL_HOME"
log "raw-data cache: $RAW_CACHE_DIR (use_cached_data=$USE_CACHED_DATA offline=$OFFLINE)"
if [ -n "$INTERMINE_SRC" ]; then
  log "intermine-src: $INTERMINE_SRC (InterMine $IM_VERSION, $IM_LINE line, mine Gradle $IM_GRADLE_VERSION${IM_GRADLE_SHA256:+, sha256 ${IM_GRADLE_SHA256:0:12}...})"
else
  log "intermine: published artefacts (the mine's own imVersion/bioVersion pins)"
fi
log "stack: containers $RDFC2IM_PREFIX-*, compose project ${COMPOSE_PROJECT_NAME:-trial (default)}, ports pg=$PG_PORT solr=$SOLR_PORT mine=$MINE_PORT bluegenes=$BG_PORT"

GRADLE_ENV=()   # populated by phase_check_prereqs; every ./gradlew call below is prefixed with it

# ============================================================== phases
phase_check_prereqs() {
  for bin in python3 docker git curl unzip; do  # psql runs inside the postgres container, not on the host
    command -v "$bin" >/dev/null 2>&1 || die "missing required tool: $bin"
  done
  $COMPOSE version >/dev/null 2>&1 || die "'$COMPOSE' does not run - is Docker Compose installed?"
  if [ -z "$JAVA8_HOME" ]; then
    for cand in /usr/lib/jvm/java-8-openjdk-* /usr/lib/jvm/java-1.8.0*; do
      [ -d "$cand" ] && JAVA8_HOME=$cand && break
    done
  fi
  [ -n "$JAVA8_HOME" ] && [ -x "$JAVA8_HOME/bin/java" ] || die \
    "JAVA8_HOME not set and no JDK 8 found under /usr/lib/jvm - Gradle 4.9 cannot start a daemon
     under a newer JDK (confirmed live, LOAD-TRIAL.md's hgnc section). Install one and set
     JAVA8_HOME, e.g.: apt-get install -y openjdk-8-jdk && export JAVA8_HOME=/usr/lib/jvm/java-8-openjdk-\$(dpkg --print-architecture)"
  GRADLE_ENV=(env "JAVA_HOME=$JAVA8_HOME")
  log "JAVA8_HOME=$JAVA8_HOME"
  [ -f "$GENE_PANEL" ] || die "gene panel file not found: $GENE_PANEL"
  # A misspelled --sources entry falling through to SCOPE_MODE's ${...:-none} default would
  # silently fetch that source completely unscoped instead of erroring - exactly the kind of
  # mistake that would only surface hours later as an unexpectedly huge ClinVar/UniProt pull.
  # Fail fast, before any real work starts, on any name not in SCOPE_MODE at all.
  for src in $SOURCES; do
    [ -v "SCOPE_MODE[$src]" ] || die "unknown source '$src' - not in SCOPE_MODE (tools/full-build.sh); " \
      "known sources: ${!SCOPE_MODE[*]}"
  done
  # The host-side Gradle tasks reach Postgres and Solr through localhost:$PG_PORT/$SOLR_PORT. If a
  # port is already published by ANOTHER stack's container, builddb would drop and recreate that
  # stack's database (and postprocess re-index its Solr) - so a port held by anything but this
  # stack's own container is fatal, before any work starts. Read-only (docker ps), so it runs under
  # --dry-run too; a docker daemon that cannot answer is treated as "no conflict".
  local port_svc port svc holder
  for port_svc in "$PG_PORT:postgres" "$SOLR_PORT:solr" "$MINE_PORT:mine" "$BG_PORT:bluegenes"; do
    port=${port_svc%%:*}; svc=${port_svc#*:}
    holder=$(docker ps --filter "publish=$port" --format '{{.Names}}' 2>/dev/null | grep -vx "$RDFC2IM_PREFIX-$svc" | head -1 || true)
    [ -z "$holder" ] || die "host port $port (for $svc) is already published by container '$holder', which is not" \
      "this stack's ($RDFC2IM_PREFIX-$svc) - use --stack-name or set the *_PORT variables"
  done
  mkdir -p "$TRIAL_HOME"
  # rdfc2im.yaml's src_data_dir (/micklem/data/rdfc2im - a real Micklem-lab deployment path,
  # deliberately not rewritten to somewhere sandbox-local; see phase_stage_src_data) lives under
  # a root-owned path on a fresh sandbox. One-time, idempotent: only touches it if not already
  # ours.
  if [ ! -w /micklem ] 2>/dev/null || [ ! -e /micklem ]; then
    run sudo mkdir -p /micklem
    run sudo chown "$(id -u):$(id -g)" /micklem
  fi
  # Gradle 4.9's daemon default heap (1024m) is not enough for InterMine's
  # ParallelBatchingFetcher, which spawns a worker thread per available CPU core, each doing its
  # own DataTracker.prefetchIds() - confirmed live: "OutOfMemoryError: GC overhead limit
  # exceeded" in a worker thread on the very first source's load. The exception is in a
  # background thread, not main, so the daemon doesn't fail cleanly - it spins in a GC
  # death-spiral, burning CPU with no forward progress, rather than exiting. GRADLE_USER_HOME's
  # own gradle.properties (default ~/.gradle) applies to every daemon Gradle starts from here,
  # across both the humanmine and humanmine-bio-sources checkouts.
  # file.encoding=UTF-8: the daemon's own default (US-ASCII) comes from this sandbox having no
  # LANG/LC_ALL set at all, which Java's platform-default-charset detection falls back to
  # US-ASCII for. Harmless for plain ASCII data, but confirmed live to actively corrupt real
  # data: reactome's own UniProt2Reactome.txt has non-ASCII bytes (Greek letters in pathway
  # names, normal UTF-8), and BioFileConverter reads files via a platform-default-charset
  # Reader (no explicit UTF-8) - under US-ASCII those bytes get mis-decoded, and one specific
  # mis-decode produced a literal NUL byte, which Postgres's COPY then rejected outright:
  # "invalid byte sequence for encoding UTF8: 0x00".
  local gradle_props="$HOME/.gradle/gradle.properties"
  if ! grep -q "^org.gradle.jvmargs" "$gradle_props" 2>/dev/null; then
    write_file "$gradle_props" "org.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8"
  fi
  log "prerequisites OK"
}

activate_venv() {
  [ -f "$HERE/.venv/bin/activate" ] || die "no .venv at $HERE/.venv - create one with pyyaml+lxml first"
  # shellcheck disable=SC1091
  source "$HERE/.venv/bin/activate"
}

phase_fetch_inputs() {
  # rdf-config, intermine, humanmine, humanmine-bio-sources, the live HumanMine model, and
  # HumanMine's own genomic_priorities.properties - see tools/make-inputs.sh's own header. The
  # four clones stay in $UPSTREAM_CACHE (git is their cache); the live model goes through the
  # checksummed raw-data cache like everything else fetched.
  activate_venv   # `rdfc2im cache` needs pyyaml/lxml
  local mdir="$TRIAL_HOME/live-model"
  if [ "$USE_CACHED_DATA" -eq 1 ]; then
    run python3 -m rdfc2im cache restore humanmine-model "$mdir" --cache-dir "$RAW_CACHE_DIR"
    # The clones are not part of the cache: --use-cached-data clones a missing one and leaves a present
    # one alone (CACHED=1); --offline (OFFLINE=1) makes a missing one an error.
    if [ "$OFFLINE" -eq 1 ]; then
      run env OFFLINE=1 CACHED=1 MODEL_DIR="$mdir" CACHE="$UPSTREAM_CACHE" sh tools/make-inputs.sh
    else
      run env CACHED=1 MODEL_DIR="$mdir" CACHE="$UPSTREAM_CACHE" sh tools/make-inputs.sh
    fi
  else
    run env CACHE="$UPSTREAM_CACHE" sh tools/make-inputs.sh
    run mkdir -p "$mdir"
    run cp in/humanmine_model.xml in/humanmine_model.json "$mdir/"
    run python3 -m rdfc2im cache save humanmine-model "$mdir" --cache-dir "$RAW_CACHE_DIR"
  fi
}

# --intermine-src only. Builds the checkout's artefacts and publishes them into the private Maven
# repo $IM_M2, which every later Gradle call resolves mavenLocal() from (IM_GRADLE_ARGS). DIR itself
# is never built in or written to: it is copied (sources only, no build output, verified file by
# file - see tools/copy_tree.py for why not cp/tar) to $TRIAL_HOME/intermine-src, afresh each run.
# The steps are those of the checkout's own config/lib/install_intermine.py (and of the planning
# repo's scripts/gate-intermine.sh): its property generation writes gradle.properties and
# gradle-wrapper.properties from the *.in templates (and ~/.intermine test properties, which the
# builds expect; HOME is the build's, not a shared one), then `publishToMavenLocal` runs in each
# module of its install list, with the gate's Gradle flags.
phase_publish_intermine() {
  local src="$TRIAL_HOME/intermine-src"
  local jdk=${INTERMINE_JAVA_HOME:-$JAVA8_HOME}
  run python3 tools/copy_tree.py "$INTERMINE_SRC" "$src" \
    --exclude .git --exclude build --exclude .gradle --exclude .gate-logs --exclude __pycache__
  log "intermine-src: $(git -C "$INTERMINE_SRC" log -1 --format='%h %s' 2>/dev/null || echo 'not a git checkout')$(
    git -C "$INTERMINE_SRC" diff --quiet HEAD 2>/dev/null || echo ' (with uncommitted changes)')"
  run mkdir -p "$IM_M2"
  # PSQL_*: install_intermine.py requires them; they only go into the test properties.
  run_in "$src" env PSQL_HOST="${PSQL_HOST:-localhost}" PSQL_USER="${PSQL_USER:-test}" PSQL_PWD="${PSQL_PWD:-test}" \
    python3 -c 'import sys; sys.path.insert(0, "config/lib"); import install_intermine as m
m.IntermineBuilder.gradle_install_modules = lambda self, clean=False: None  # publishing is done below
sys.argv = ["install_intermine.py"]; m.main()'
  local modules
  modules=$(sed -n '/def gradle_install_modules/,/^ *]/p' "$INTERMINE_SRC/config/lib/install_intermine.py" | grep -o '"[^"]*"' | tr -d '"')
  [ -n "$modules" ] || die "no module list in $INTERMINE_SRC/config/lib/install_intermine.py (gradle_install_modules)"
  log "publishing $(echo $modules) at $IM_VERSION into $IM_M2"
  local m
  for m in $modules; do
    run_in "$src/$m" env JAVA_HOME="$jdk" LANG=C.UTF-8 LC_ALL=C.UTF-8 ./gradlew -Dorg.gradle.jvmargs=-Xmx4g \
      --max-workers=4 --no-daemon --stacktrace "${IM_GRADLE_ARGS[@]}" publishToMavenLocal
  done
  if [ "$DRY_RUN" -eq 0 ]; then
    # What the mine needs from the repo, checked here rather than as a resolution failure later.
    local need
    for need in "plugin/$IM_VERSION/plugin-$IM_VERSION.jar" \
                "intermine-webapp/$IM_VERSION/intermine-webapp-$IM_VERSION-classes.jar" \
                "bio-webapp/$IM_VERSION/bio-webapp-$IM_VERSION.war" \
                "bio-model/$IM_VERSION/bio-model-$IM_VERSION.jar" \
                "bio-source-reactome/$IM_VERSION/bio-source-reactome-$IM_VERSION.jar"; do
      [ -f "$IM_M2/org/intermine/$need" ] || die "publish_intermine: $IM_M2/org/intermine/$need was not published"
    done
    log "published $(find "$IM_M2/org/intermine" -mindepth 1 -maxdepth 1 -type d | wc -l) org.intermine artefacts at $IM_VERSION into $IM_M2"
  fi
}

# Emits the rdfc2im scope flags for one source, per SCOPE_MODE. Kept as one function so the
# per-source scoping rule lives in exactly one place, matching this project's own "general fix,
# not a special case" preference (see RESTART.md's process notes).
scope_flags_for() {
  local src=$1
  case "${SCOPE_MODE[$src]:-none}" in
    full)  printf -- '--taxon %s' "$TAXON" ;;
    panel) printf -- '--taxon %s --genes @%s' "$TAXON" "$GENE_PANEL" ;;
    pmid)  printf -- '' ;;  # pubmed's --pmids needs other sources' PMIDs already loaded; see integrate_sources
    none)  printf -- '' ;;
  esac
}

# What a cached fetch must have been fetched FOR, as `--meta k=v` words for `rdfc2im cache`. On
# restore every one must match what was recorded at save time, so data fetched for another gene
# panel, taxon or scope is refused rather than silently building the wrong mine. No values here
# contain whitespace, so the caller can word-split the result.
cache_meta_for() {
  local src=$1
  printf -- '--meta scope=%s --meta taxon=%s --meta limit=0' "${SCOPE_MODE[$src]:-none}" "$TAXON"
  case "${SCOPE_MODE[$src]:-none}" in
    panel) printf -- ' --meta genes_md5=%s' "$(md5sum "$GENE_PANEL" | cut -d' ' -f1)" ;;
    pmid)  [ -f "$TRIAL_HOME/cited_pmids.txt" ] &&
             printf -- ' --meta pmids_md5=%s' "$(md5sum "$TRIAL_HOME/cited_pmids.txt" | cut -d' ' -f1)" ;;
  esac
  return 0
}

# The gene-symbol -> id lookups `translate --genes` makes (scope.resolve_gene_ids) are cached as the
# raw-data group gene-id-lookup, restored into / saved from $LOOKUP_DIR (the dir translate uses:
# $RDFC2IM_RESOLVER_CACHE, else out/_resolver). Only these sources resolve symbols.
LOOKUP_DIR=${RDFC2IM_RESOLVER_CACHE:-"$HERE/out/_resolver"}
uses_lookup() { local s; for s in $SOURCES; do case " ncbigene hgnc clinvar ensembl gwascatalog " in *" $s "*) return 0 ;; esac; done; return 1; }
lookup_meta() { printf -- '--meta taxon=%s --meta genes_md5=%s' "$TAXON" "$(md5sum "$GENE_PANEL" | cut -d' ' -f1)"; }

phase_rdfc2im_pipeline() {
  activate_venv
  if [ "$USE_CACHED_DATA" -eq 1 ]; then
    if [ "$OFFLINE" -eq 1 ]; then
      export RDFC2IM_OFFLINE=1   # any network request now fails, naming what the cache lacks
    else
      unset RDFC2IM_OFFLINE
    fi
    if uses_lookup; then
      # shellcheck disable=SC2046
      run python3 -m rdfc2im cache restore gene-id-lookup "$LOOKUP_DIR" --cache-dir "$RAW_CACHE_DIR" $(lookup_meta)
    fi
  else
    export RDFC2IM_RESOLVER_REFRESH=1   # a fetch run asks the network afresh, then saves the answers
  fi
  for src in $SOURCES; do
    local flags; flags=$(scope_flags_for "$src")
    log "-- $src (scope=${SCOPE_MODE[$src]:-none}) --"
    run python3 -m rdfc2im translate --source "$src" $flags
    local pmid_file="$TRIAL_HOME/cited_pmids.txt"
    if [ "$src" = "pubmed" ]; then
      # PMID-scoped to the union of PMIDs the panel's own already-loaded data cites (hgnc's
      # main_reference, uniprot's main_citation, gwascatalog, reactome) - see LOAD-TRIAL.md's
      # pubmed section. Requires those sources' items to already exist on disk. Derived from the
      # other sources' items, so it is regenerated - not cached - and its checksum is what ties
      # the cached pubmed data to the PMID set it was fetched for.
      #
      # -a forces text mode: without it, grep inside this `bash -c` context (unlike an interactive
      # shell) mis-detects these UTF-8 items XML files as binary and reports "binary file matches"
      # with zero actual matches - confirmed live, silently produced an empty cited_pmids.txt, which
      # made cli.py's `if pmids and pmid_field` (falsy on []) fall through to an unrestricted,
      # LIMIT-0 fetch of all of PubMed instead of the intended PMID-scoped one.
      run bash -c "grep -ahoE '\"[0-9]{4,9}\"' out/{hgnc,uniprot,gwascatalog,reactome}/items/*.xml 2>/dev/null \
                    | tr -d '\"' | sort -u > '$pmid_file'"
    fi
    local meta; meta=$(cache_meta_for "$src")
    if [ "$USE_CACHED_DATA" -eq 1 ]; then
      # shellcheck disable=SC2086  # $meta is deliberately word-split into --meta k=v arguments
      run python3 -m rdfc2im cache restore "$src" "out/$src/raw" --cache-dir "$RAW_CACHE_DIR" $meta
    else
      if [ "$src" = "pubmed" ]; then
        run python3 -m rdfc2im fetch --source pubmed --limit 0 --force --pmids "@$pmid_file"
      else
        run python3 -m rdfc2im fetch --source "$src" --limit 0 --force $flags
      fi
      # shellcheck disable=SC2086
      run python3 -m rdfc2im cache save "$src" "out/$src/raw" --cache-dir "$RAW_CACHE_DIR" $meta
    fi
    run python3 -m rdfc2im tsv --source "$src"
    run python3 -m rdfc2im items --source "$src"
  done
  if [ "$USE_CACHED_DATA" -eq 0 ] && uses_lookup; then
    # shellcheck disable=SC2046
    run python3 -m rdfc2im cache save gene-id-lookup "$LOOKUP_DIR" --cache-dir "$RAW_CACHE_DIR" $(lookup_meta)
  fi
}

phase_rdfc2im_project() {
  source "$HERE/.venv/bin/activate"
  # Scope the mine to $SOURCES, exactly as the fetch was. Without --source, `project` takes every
  # out/<dir> that has a columns.tsv - and those are derived files that outlive the build that made
  # them, so stale translate output from sources nobody asked for ended up in project.xml and
  # :dbmodel:integrate died loading one of them (confirmed live: humanmine-expressionatlas).
  local src_flags=(); for s in $SOURCES; do src_flags+=(--source "$s"); done
  run python3 -m rdfc2im project "${src_flags[@]}"
  # `check` needs out/_mine/project.xml (rdfc2im check -> check_project(..., out/_mine, ...)), which
  # `project` above is what creates - USAGE.md's own documented order is project -> check -> docs.
  # Originally called at the end of phase_rdfc2im_pipeline, before project.xml existed - confirmed
  # live: "check: no project.xml - run `rdfc2im project` first", exit 2. --dry-run never runs `check`
  # for real, so this ordering bug survived every prior dry-run test.
  run python3 -m rdfc2im check
  run make fork-sync
}

phase_build_humanmine_items() {
  local bio="$TRIAL_HOME/humanmine-bio-sources"
  [ -d "$bio" ] || run cp -r "$UPSTREAM_CACHE/humanmine-bio-sources" "$bio"
  # The dead JCenter/Bintray plugin in bio-source-humanmine-static fails Gradle's config phase
  # for every sibling project (confirmed live, LOAD-TRIAL.md). Not needed for this source list.
  if grep -q "^[^#]*bio-source-humanmine-static" "$bio/settings.gradle" 2>/dev/null; then
    run sed -i.bak "s/^\(.*bio-source-humanmine-static.*\)$/\/\/ \1  # disabled by full-build.sh: dead JCenter plugin/" \
        "$bio/settings.gradle"
  fi
  # With --intermine-src the subproject is a copy under TRIAL_HOME, because the move to the
  # checkout's Gradle edits its build.gradle and this repository's own copy must stay as it is.
  local items_dir="$HERE/humanmine-items"
  if [ -n "$INTERMINE_SRC" ]; then
    items_dir="$TRIAL_HOME/humanmine-items"
    run python3 tools/copy_tree.py "$HERE/humanmine-items" "$items_dir" --exclude build
  fi
  if ! grep -q "bio-source-humanmine-items" "$bio/settings.gradle" 2>/dev/null; then
    # An absolute path, not a relative guess up from $bio: the original '../../../humanmine-items'
    # assumed TRIAL_HOME sits a fixed depth alongside the rdfc2im checkout as a sibling directory.
    # Confirmed live that assumption doesn't hold here (TRIAL_HOME under ~/intermine-build/, the
    # checkout under /Users/gos/git/rdfc2im/ - unrelated trees): it resolved to
    # /home/agent/humanmine-items, which doesn't exist - "Basedir ... does not exist", Gradle
    # initConfig FAILED. $HERE is already known precisely, so use it directly instead of guessing.
    run bash -c "cat >> '$bio/settings.gradle' <<GRADLE

include ':bio-source-humanmine-items'
project(':bio-source-humanmine-items').projectDir = new File('$items_dir')
GRADLE"
  fi
  local install_task=install
  if [ -n "$INTERMINE_SRC" ]; then
    # A checkout whose TRIAL_HOME was first built without --intermine-src points at $HERE's copy.
    if [ "$DRY_RUN" -eq 1 ] || ! grep -qF "projectDir = new File('$items_dir')" "$bio/settings.gradle"; then
      log "edit: humanmine-bio-sources/settings.gradle: humanmine-items projectDir -> $items_dir"
      run sed -i "s|^\(project(':bio-source-humanmine-items').projectDir = \).*|\1new File('$items_dir')|" "$bio/settings.gradle"
    fi
    # The checkout's version, resolved from the private repo (IM_GRADLE_ARGS), and the checkout's
    # Gradle: this build applies the InterMine plugin too, and a plugin compiled by a newer Gradle
    # does not load in 4.9 (confirmed live with the 5.1.1 plugin built by Gradle 7.6.6: mergeModels
    # failed with NoClassDefFoundError groovy/ant/AntBuilder - Groovy 3 moved AntBuilder from
    # groovy.util to groovy.ant, and Gradle 4.9 ships Groovy 2.4).
    _upgrade_bio_sources_build "$bio" "$items_dir"
    # Gradle < 7 keeps the `maven` plugin (see _upgrade_bio_sources_build), whose task is `install`
    [ "${IM_GRADLE_VERSION%%.*}" -ge 7 ] && install_task=publishToMavenLocal
  fi
  run_in "$bio" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" ":bio-source-humanmine-items:$install_task"
}

# Builds and installs org.intermine:bio-source-reactome:5.0.8 (with --intermine-src: the checkout's
# version, into its private repo) into the local Maven repo, in one
# of two modes - the same project, built twice, because of a genuine chicken-and-egg:
#
#   converter-only  ReactomeConverter alone. Needed BEFORE :dbmodel:builddb, because
#                   addSourceDependencies resolves bio-source-<type> for every source in
#                   project.xml, and before integrate_sources, which actually runs the converter.
#                   ReactomeConverter itself only uses the generic Item API, so it compiles with
#                   no mine-specific classes - which is why this mode works this early.
#   with-postprocess  Adds ReactomePostProcess, which imports org.intermine.model.bio.Pathway.
#                   Confirmed live: Pathway is NOT in the stock bio-model jar (Gene and Protein
#                   are) - it is contributed by reactome_additions.xml, so it exists only in the
#                   mine's OWN generated dbmodel.jar, which does not exist until builddb has run.
#                   Hence the second build, from phase_postprocess.
#
# group/version match exactly what IntegratePlugin.groovy resolves for a project.xml
# <source type="reactome"> entry with no explicit version="..." attribute: "bio-source-" + type,
# at bioVersion (5.0.8, confirmed live - the same version already resolved and cached for
# bio-model/intermine-integrate elsewhere in this build). With --intermine-src the mine's bioVersion
# is exactly IM_VERSION, so the jar, bio-core, bio-model and intermine-integrate all are too.
_install_reactome_jar() {
  local mode=$1
  local jar_version=${IM_VERSION:-5.0.8} bio_version=${IM_VERSION:-5.0.8} im_version=${IM_VERSION:-5.0.+}
  local build="$TRIAL_HOME/reactome-source"
  local dbmodel_jar="$TRIAL_HOME/humanmine/dbmodel/build/libs/dbmodel.jar"
  local src_java="java { srcDirs = ['src/main/java']; exclude '**/postprocess/**' }"
  local extra_dep=""
  if [ "$mode" = "with-postprocess" ]; then
    src_java="java { srcDirs = ['src/main/java'] }"
    extra_dep="    compile files('$dbmodel_jar')"
  fi
  write_file "$build/build.gradle" "$(cat <<GRADLE
apply plugin: 'java'
apply plugin: 'maven'

group = 'org.intermine'
version = '$jar_version'
sourceCompatibility = 1.8
targetCompatibility = 1.8

repositories {
    mavenLocal()
    mavenCentral()
}

sourceSets {
    main {
        $src_java
        resources { srcDirs = ['src/main/resources'] }
    }
}

processResources {
    from('.') { include('*.properties') }
}

dependencies {
    // bio-core provides org.intermine.bio.util.*/BioFileConverter - not in reactome's own
    // build.gradle dependencies block (confirmed live: compileJava failed without it, "package
    // org.intermine.bio.util does not exist") because intermine/bio's real root build.gradle
    // applies it to every bio/sources/* subproject via its own subprojects{} block; this
    // standalone build has no such parent, so it's declared explicitly here instead.
    compile group: 'org.intermine', name: 'bio-core', version: '$bio_version', transitive: false
    compile group: 'org.intermine', name: 'bio-model', version: '$bio_version', transitive: false
    compile group: 'org.intermine', name: 'intermine-integrate', version: '$im_version'
    runtime fileTree(dir: 'libs', include: '*.jar')
$extra_dep
}
GRADLE
)"
  write_file "$build/settings.gradle" "rootProject.name = 'bio-source-reactome'"
  run_in "$build" "${GRADLE_ENV[@]}" "$GRADLE49" "${IM_GRADLE_ARGS[@]}" install
}

phase_build_reactome_source() {
  # Stock reactome (type="reactome", org.intermine:bio-source-reactome) - our own
  # humanmine-reactome only maps Pathway.description, no participants (unmapped/pruned
  # pathwayComponent link - sources.yaml's own note), so without this alongside source Pathway
  # never connects to any Protein or Gene. Its jar is equally dead on JCenter/Maven Central
  # (confirmed: 403 / 404) but unlike the ~39 sources dropped in phase_prepare_mine_checkout,
  # this one is worth building from the local source make-inputs.sh already cloned
  # (in/.upstream/intermine/bio/sources/reactome) - same "isolated standalone build, not the
  # whole dead-JCenter-riddled intermine/bio umbrella" trick as bio-source-humanmine-items.
  local src="$INTERMINE_TREE/bio/sources/reactome"
  # A dry run never made the --intermine-src copy; show the plan against the checkout itself.
  if [ "$DRY_RUN" -eq 1 ] && [ -n "$INTERMINE_SRC" ] && [ ! -d "$src" ]; then src="$INTERMINE_SRC/bio/sources/reactome"; fi
  local build="$TRIAL_HOME/reactome-source"
  [ -d "$build" ] || run mkdir -p "$build"
  run cp -r "$src/src" "$build/src"
  # The caching antlr jar the converter needs: bio/sources/reactome/libs up to the 5.x trees, the
  # InterMine core's intermine/libs since im-jqz.6 (maint-2026).
  local antlr_jar="$(dirname "$(dirname "$(dirname "$src")")")/intermine/libs/antlr-2.7.6-caching.jar"
  run mkdir -p "$build/libs"
  if [ -d "$src/libs" ]; then
    run bash -c "cp '$src'/libs/*.jar '$build/libs/'"
  elif [ -f "$antlr_jar" ]; then
    run cp "$antlr_jar" "$build/libs/"
  else
    die "reactome source: no caching antlr jar - neither $src/libs nor $antlr_jar exists"
  fi
  run cp "$src/reactome.properties" "$build/reactome.properties"
  # group/version match exactly what IntegratePlugin.groovy resolves for a project.xml
  # <source type="reactome"> entry with no explicit version="..." attribute: "bio-source-" +
  # type, at bioVersion (5.0.8, confirmed live - the same version already resolved and cached
  # for bio-model/intermine-integrate elsewhere in this build).
  _install_reactome_jar converter-only

  # Data: reactome's own project.xml entry expects a plain UniProt-to-pathway mapping file
  # under src.data.dir (a directory, not a single named file - have.file.custom.tgt processes
  # whatever it finds there). ReactomeConverter.java confirms the exact 6-column tab-delimited
  # shape (accession, pathway id, url, pathway name, evidence code, organism name) this is -
  # Reactome's own public UniProt2Reactome mapping, not a full BioPAX dump. Fetched once, not
  # re-fetched on a --from resume - confirmed live: ~325k rows total, ~55k human, a few seconds
  # to download, not worth repeating.
  # REACTOME_LEVELS picks which of Reactome's own two published files: "default" is
  # UniProt2Reactome.txt (leaf pathways only - a protein appears only against the specific
  # pathway it participates in); "all" is UniProt2Reactome_All_Levels.txt (every ancestor
  # pathway too, matching how reactome.org's own website presents a pathway's contents - a
  # top-level pathway like "Metabolism" then has real Gene.pathways/Pathway.proteins rows, at
  # the cost of a much bigger file and heavier Gene.pathways fan-out). The loader's own fileset
  # scan (FileConverterTask) processes every file it finds under src.data.dir, so the two must
  # never coexist there - `rm -f` before writing whichever one this run wants.
  local fname="UniProt2Reactome.txt"
  [ "$REACTOME_LEVELS" = "all" ] && fname="UniProt2Reactome_All_Levels.txt"
  local other_fname="UniProt2Reactome_All_Levels.txt"
  [ "$REACTOME_LEVELS" = "all" ] && other_fname="UniProt2Reactome.txt"
  local dest_dir="/micklem/data/reactome/current"
  run mkdir -p "$dest_dir"
  # Clear the OTHER level's file unconditionally (rm -f is a no-op if it never existed) - never
  # the one this run wants, which stays as a resume optimisation (see below). Deterministic on the
  # two filenames rather than a glob over dest_dir's real contents, so it appears in --dry-run's
  # plan the same way whether or not an earlier run actually left one (mkdir above is also only a
  # `run` no-op under --dry-run, so dest_dir may not even exist yet to glob).
  run rm -f "$dest_dir/$other_fname"
  source "$HERE/.venv/bin/activate"   # `rdfc2im cache` below needs pyyaml/lxml (imported by the CLI)
  if [ "$USE_CACHED_DATA" -eq 1 ]; then
    run python3 -m rdfc2im cache restore reactome-uniprot-map "$dest_dir" --cache-dir "$RAW_CACHE_DIR" \
      --meta levels="$REACTOME_LEVELS"
  else
    # Fetched once, not re-fetched on a --from resume: confirmed live, ~325k rows (default) / much
    # larger (all-levels), a few seconds to tens of seconds to download, not worth repeating.
    if [ "$DRY_RUN" -eq 1 ] || [ ! -s "$dest_dir/$fname" ]; then
      run curl -fsSL -o "$dest_dir/$fname" "https://reactome.org/download/current/$fname"
    fi
    run python3 -m rdfc2im cache save reactome-uniprot-map "$dest_dir" --cache-dir "$RAW_CACHE_DIR" \
      --meta levels="$REACTOME_LEVELS" --meta url="https://reactome.org/download/current/$fname"
  fi
}

# Writes $2 to file $1, or just logs the intent under --dry-run - a real dry run must not touch
# $HOME or the working tree. `run cmd > file` does NOT achieve this on its own: bash opens a
# bare redirect on the *caller's* command line before `run` is even invoked, so the file gets
# created (or the write attempted) regardless of DRY_RUN - found by dry-running this script, not
# by inspection. Route every generated-file write through this instead of a bare `>`.
write_file() {
  local dest=$1 content=$2
  log "+ write $dest ($(printf '%s' "$content" | wc -l) lines)"
  [ "$DRY_RUN" -eq 1 ] && return 0
  mkdir -p "$(dirname "$dest")"
  printf '%s\n' "$content" > "$dest"
}

# COMPOSE_FILES: computed globally, not inside phase_start_databases, and unconditionally (not
# gated on DRY_RUN) - both phase_start_databases and phase_start_mine_stack need it, and a
# `--from`/`--only` resume can run either one without the other having run first in THIS
# invocation. A phase-local variable set in one phase and read in another breaks the moment a
# resume skips the setter - confirmed live: `--from stage_artifacts` hit start_mine_stack with
# an empty COMPOSE_FILES (never set this run), so `docker compose up` ran with no -f flags at
# all and failed "no configuration file provided: not found". BIND_ADDR/PG_PORT/etc are plain
# config, known from script start regardless of resume point, so this has everything it needs
# without depending on any phase having already run.
COMPOSE_FILES=(-f trial/docker-compose.yml)
if [ "$BIND_ADDR" != "127.0.0.1" ]; then
  write_file "trial/docker-compose.local.yml" "$(cat <<YML
# Untracked, sandbox-local override generated by full-build.sh (BIND_ADDR=$BIND_ADDR).
# Never commit this - the tracked trial/docker-compose.yml deliberately binds 127.0.0.1
# and expects ssh -L; this is for sandboxes that publish ports a different way instead.
#
# !override (not a plain list): Compose merges \`ports:\` across -f files by concatenating,
# not replacing - confirmed live, every service ended up with BOTH the base file's 127.0.0.1
# binding AND this one simultaneously, and since 0.0.0.0 already covers 127.0.0.1, the second
# bind failed with "address already in use" ("docker compose ... up" died before any container
# actually started). \`!override\` (Compose spec's sequence-merge tag) replaces the list instead.
services:
  postgres: {ports: !override ["$BIND_ADDR:$PG_PORT:5432"]}
  solr:     {ports: !override ["$BIND_ADDR:$SOLR_PORT:8983"]}
  mine:     {ports: !override ["$BIND_ADDR:$MINE_PORT:$MINE_PORT"]}
  bluegenes: {ports: !override ["$BIND_ADDR:$BG_PORT:5000"]}
YML
)"
  COMPOSE_FILES+=(-f "trial/docker-compose.local.yml")
fi

# One deployer edit to a copied mine build file: a sed edit that is applied (and logged as
# "deployer edit", with the file and what it is for) only when it changes the file, so a re-run
# is a no-op and the log of a fresh run lists exactly the edits a deployer has to make by hand.
# These are the edits of the --intermine-src checkout's docs/UPGRADING-build.md.
deployer_edit() {
  local file=$1 what=$2; shift 2
  if [ "$DRY_RUN" -eq 0 ]; then
    [ -f "$file" ] || die "deployer edit: no $file"
    sed "$@" "$file" | cmp -s - "$file" && return 0
  fi
  log "deployer edit: ${file#"$TRIAL_HOME"/}: $what"
  run sed -i "$@" "$file"
}

# --intermine-src only: what `./gradlew wrapper --gradle-version $IM_GRADLE_VERSION` does to the
# Gradle checkout $1, without needing its old Gradle to configure the build first - the InterMine
# checkout's own wrapper jar and launcher script, and a properties file naming the checkout's Gradle
# (and its checksum, when the checkout's install_intermine.py knows it).
_switch_gradle_wrapper() {
  local dir=$1
  local wrapper_props="$dir/gradle/wrapper/gradle-wrapper.properties"
  local url="https://services.gradle.org/distributions/gradle-$IM_GRADLE_VERSION-bin.zip"
  deployer_edit "$wrapper_props" "Gradle wrapper -> $IM_GRADLE_VERSION" \
    -e "s|^distributionUrl=.*|distributionUrl=$url|"
  if [ -n "$IM_GRADLE_SHA256" ]; then
    if [ "$DRY_RUN" -eq 1 ] || ! grep -q "^distributionSha256Sum=" "$wrapper_props"; then
      log "deployer edit: ${wrapper_props#"$TRIAL_HOME"/}: add distributionSha256Sum"
      run bash -c "printf 'distributionSha256Sum=%s\n' '$IM_GRADLE_SHA256' >> '$wrapper_props'"
    fi
    deployer_edit "$wrapper_props" "distributionSha256Sum of gradle-$IM_GRADLE_VERSION-bin.zip" \
      -e "s|^distributionSha256Sum=.*|distributionSha256Sum=$IM_GRADLE_SHA256|"
  fi
  local f
  for f in gradle/wrapper/gradle-wrapper.jar gradlew; do
    if [ "$DRY_RUN" -eq 1 ] || ! cmp -s "$INTERMINE_SRC/intermine/$f" "$dir/$f"; then
      log "deployer edit: ${dir#"$TRIAL_HOME"/}/$f: the checkout's ($IM_GRADLE_VERSION) wrapper file"
      # cat, not cp, and compared afterwards: plain cp has silently zeroed files on virtiofs mounts
      # (see make-inputs.sh / the Makefile's fork-sync)
      run bash -c "cat '$INTERMINE_SRC/intermine/$f' > '$dir/$f' && cmp -s '$INTERMINE_SRC/intermine/$f' '$dir/$f'"
    fi
  done
}

# The imVersion/bioVersion pins of a copied mine or bio-sources checkout -> IM_VERSION.
_pin_intermine_version() {
  local props=$1/gradle.properties
  deployer_edit "$props" "imVersion -> $IM_VERSION" -e "s/^systemProp\.imVersion=.*/systemProp.imVersion=$IM_VERSION/"
  deployer_edit "$props" "bioVersion -> $IM_VERSION" -e "s/^systemProp\.bioVersion=.*/systemProp.bioVersion=$IM_VERSION/"
}

# Gradle 7 removed the compile/testCompile configurations (UPGRADING-build.md, 5.1.1 to 6.0.0).
_gradle7_configurations() {
  local f
  for f in "$@"; do
    deployer_edit "$f" "compile -> implementation, testCompile -> testImplementation (removed in Gradle 7)" \
      -e 's/^\([[:space:]]*\)compile\b/\1implementation/' \
      -e 's/^\([[:space:]]*\)testCompile\b/\1testImplementation/'
  done
}

# --intermine-src on the 6.0 line (Gradle 8): the mine checkout is the maint-2026 branch of the
# gmicklem/humanmine fork (HUMANMINE_60_URL/HUMANMINE_60_REF), which is upstream master plus the
# conversion of its build files per the checkout's docs/UPGRADING-build.md '5.1.1 to 6.0.0'
# (commits f426ac8 and 58fbf8f: root, dbmodel and webapp build.gradle, gradle.properties, wrapper;
# the plugin composes the war). Starting from that branch is cleaner than patching upstream
# master with sed: the conversion is a dozen edits (java {} block, publishing/cargo plugin
# versions, copyMineProperties, the whole war composition) that are reviewed, built and tested
# as a unit there, and project.xml, the model and everything the rest of this script touches are
# the same as master's. Cloned once into the upstream cache, copied (without .git) to $1.
_copy_mine_60() {
  local mine=$1 clone="$UPSTREAM_CACHE/humanmine-6.0"
  if [ ! -d "$clone/.git" ]; then
    log "6.0 line: cloning $HUMANMINE_60_URL ($HUMANMINE_60_REF) for the converted mine build files"
    run git clone --depth 1 --quiet --branch "$HUMANMINE_60_REF" "$HUMANMINE_60_URL" "$clone"
  fi
  log "6.0 line: mine checkout = $HUMANMINE_60_REF of $HUMANMINE_60_URL at $(git -C "$clone" log -1 --format='%h %s' 2>/dev/null | cut -c1-100)"
  run python3 tools/copy_tree.py "$clone" "$mine" --exclude .git
}

# --intermine-src only: moves a copied Gradle-4.9 mine checkout (humanmine as of 2022) onto the
# checkout's version and Gradle. Every change is a deployer_edit or a logged wrapper copy.
_upgrade_mine_build() {
  local mine=$1
  local major=${IM_GRADLE_VERSION%%.*}
  _pin_intermine_version "$mine"
  _switch_gradle_wrapper "$mine"
  if [ "$IM_LINE" = "6.0" ]; then
    # The 6.0 line: $mine is already the converted HumanMine (_copy_mine_60), so only the version
    # pins and the wrapper above are left. A checkout that still has the old war composition (a
    # hand-supplied TRIAL_HOME copy of upstream master) would fail Gradle 8 validation later
    # ("uses this output of task copyWebappContent without declaring a dependency"): say so now.
    if [ "$DRY_RUN" -eq 0 ] && grep -qE "copyWebappContent|warWebApp" "$mine/webapp/build.gradle"; then
      die "$mine/webapp/build.gradle still composes the war itself (copyWebappContent/warWebApp): not a 6.0-line mine. Remove $mine and re-run, or convert it by UPGRADING-build.md '5.1.1 to 6.0.0'"
    fi
    return 0
  fi
  # Gradle 5 removed TaskInputs.sourceFiles.stopExecutionIfEmpty(): without this the mine does not
  # configure at all (UPGRADING-build.md, 5.0.x to 5.1.1 step 3).
  if [ "$major" -ge 5 ]; then
    deployer_edit "$mine/build.gradle" "delete inputs.sourceFiles.stopExecutionIfEmpty() (removed in Gradle 5)" \
      -e '/inputs\.sourceFiles\.stopExecutionIfEmpty()/d'
  fi
  if [ "$major" -ge 7 ]; then
    # Gradle 7 removed the `maven` plugin; jcenter() is deprecated in 7, removed in 8, and has been
    # dead since 2021 anyway.
    deployer_edit "$mine/build.gradle" "delete apply plugin: 'maven' (removed in Gradle 7)" \
      -e "/^[[:space:]]*apply plugin: 'maven'[[:space:]]*\$/d"
    deployer_edit "$mine/build.gradle" "delete jcenter() (dead; removed in Gradle 8)" \
      -e '/^[[:space:]]*jcenter()[[:space:]]*$/d'
    _gradle7_configurations "$mine/build.gradle" "$mine/dbmodel/build.gradle" "$mine/webapp/build.gradle"
    # JavaExec.main is deprecated in 7.1 and removed in 8 (blueGenesStart, never run here).
    deployer_edit "$mine/webapp/build.gradle" "JavaExec main = -> mainClass = (removed in Gradle 8)" \
      -e 's/^\([[:space:]]*\)main = /\1mainClass = /'
    # Gradle 7 fails a copy/archive task on a duplicate entry unless a strategy is set. warWebApp
    # packs the unwarred bio-webapp (whose WEB-INF/lib already holds the jars) plus the War task's
    # own runtime classpath, so every shared jar is a duplicate - confirmed live: "Entry
    # WEB-INF/lib/hk2-locator-2.5.0-b30.jar is a duplicate". Gradle 4.9 wrote both copies (hence
    # trial-stage.sh's `unzip -o`); EXCLUDE keeps one (UPGRADING-build.md, 5.1.1 to 6.0.0 step 5).
    deployer_edit "$mine/webapp/build.gradle" "warWebApp: duplicatesStrategy = DuplicatesStrategy.EXCLUDE (duplicates fail in Gradle 7)" \
      -e '/^task warWebApp(type: War) {$/{n;/duplicatesStrategy/!i\    duplicatesStrategy = DuplicatesStrategy.EXCLUDE' -e '}'
  fi
}

# --intermine-src only: the same move for the copied humanmine-bio-sources checkout ($1) and the
# humanmine-items subproject copy ($2). Its root build.gradle publishes with the `maven` plugin
# (`install`), so on Gradle >= 7 that becomes maven-publish with one publication per subproject
# (`publishToMavenLocal`), and the sources/javadoc jars' `classifier` becomes `archiveClassifier`
# (deprecated in 7, removed in 8).
_upgrade_bio_sources_build() {
  local bio=$1 items=$2
  local major=${IM_GRADLE_VERSION%%.*}
  _pin_intermine_version "$bio"
  _switch_gradle_wrapper "$bio"
  if [ "$major" -ge 7 ]; then
    deployer_edit "$bio/build.gradle" "apply plugin: 'maven' -> 'maven-publish' plus a publication (maven removed in Gradle 7)" \
      -e "s/^\([[:space:]]*\)apply plugin: 'maven'[[:space:]]*\$/\1apply plugin: 'maven-publish'\n\1publishing { publications { maven(MavenPublication) { from components.java } } }/"
    deployer_edit "$bio/build.gradle" "classifier = -> archiveClassifier = (removed in Gradle 8)" \
      -e 's/^\([[:space:]]*\)classifier = /\1archiveClassifier = /'
    local f files=("$bio/build.gradle" "$items/build.gradle")
    for f in "$bio"/*/build.gradle; do files+=("$f"); done
    _gradle7_configurations "${files[@]}"
  fi
}

phase_prepare_mine_checkout() {
  local mine="$TRIAL_HOME/humanmine"
  # shellcheck disable=SC1090
  source "$HERE/.venv/bin/activate"   # tools/reduce_mine.py below needs lxml
  if [ ! -d "$mine" ]; then
    if [ "$IM_LINE" = "6.0" ]; then _copy_mine_60 "$mine"; else run cp -r "$UPSTREAM_CACHE/humanmine" "$mine"; fi
  fi
  if [ -n "$INTERMINE_SRC" ]; then _upgrade_mine_build "$mine"; fi
  # webapp/build.gradle pulls the Gretty plugin from JCenter/Bintray (dead since 2021, same class
  # of problem already worked around for bio-source-humanmine-static) - confirmed live: 403
  # Forbidden from jcenter.bintray.com, which fails Gradle's CONFIGURE phase for the whole
  # humanmine project (every subproject is evaluated up front, so this breaks :dbmodel:builddb
  # too, not just :webapp). Gretty is only used for its own embedded-Jetty dev-convenience tasks
  # (`gretty run`) - nothing in `war`'s own dependsOn graph needs it, and this build's actual
  # deployment goes through the Tomcat container (trial/docker-compose.yml), never gretty. Safe
  # to disable: comment out the plugin apply and its now-orphaned `gretty {}` config block.
  if grep -q "^apply from:.*gretty.plugin" "$mine/webapp/build.gradle" 2>/dev/null; then
    run sed -i.bak \
      -e 's|^\(apply from:.*gretty\.plugin.*\)$|// \1  # disabled by full-build.sh: dead JCenter plugin|' \
      -e '/^gretty {/,/^}/{ s/^/\/\/ /; }' \
      "$mine/webapp/build.gradle"
  fi
  # dbmodel/build.gradle's soTermListFilePath/soAdditionFilePath are relative strings, passed
  # straight into an Ant task (DBModelPlugin.groovy: `ant.createSoModel(soTermListFile:
  # config.soTermListFilePath, outputFile: config.soAdditionFilePath)`) with no project.file(...)
  # resolution first. Ant resolves a relative path against the JVM's OS-level `user.dir`, which
  # for a Gradle DAEMON process is fixed at $GRADLE_USER_HOME/daemon/<version>/ for the daemon's
  # whole lifetime, not the calling client's directory - confirmed live: createSoModel failed
  # looking for ".../daemon/4.9/dbmodel/resources/so_terms" (that exact prefix), even against a
  # freshly restarted daemon started from the right directory. A genuine bug in intermine's own
  # gradle plugin, not rdfc2im or full-build.sh; making both paths absolute here avoids it
  # without disabling the daemon for every other ./gradlew call this script makes.
  # (The 6.0 plugin resolves relative paths against the mine's root itself: left as they are.)
  if [ "$IM_LINE" != "6.0" ] && grep -q '^\s*soTermListFilePath = "dbmodel/resources/so_terms"' "$mine/dbmodel/build.gradle" 2>/dev/null; then
    run sed -i.bak \
      -e "s|soTermListFilePath = \"dbmodel/resources/so_terms\"|soTermListFilePath = \"$mine/dbmodel/resources/so_terms\"|" \
      -e "s|soAdditionFilePath = \"dbmodel/build/so_additions.xml\"|soAdditionFilePath = \"$mine/dbmodel/build/so_additions.xml\"|" \
      "$mine/dbmodel/build.gradle"
  fi
  # webapp/build.gradle's warWebApp task never told Gradle's War type where the REAL (struts-
  # merged, by addStrutsConfig) WEB-INF/web.xml lives, so it silently produced a war with NO
  # web.xml at all - confirmed live: the war deployed and Tomcat logged success, but every
  # request 404'd (no servlet mappings exist without one), with nothing resembling an error
  # anywhere in Tomcat's own logs. Gradle's War task manages WEB-INF/web.xml through its own
  # dedicated `webXml` property, not through the generic `from()` copy, and since `webXml` was
  # never set, nothing added one. Must ALSO exclude it from `from()` - setting webXml alone
  # added it twice (once via the property, once because it's a real file under
  # explodedWebAppDir), producing a corrupted war with two overlapping web.xml entries that
  # `unzip` refused as "possible zip bomb".
  # (Not on the 6.0 line: the plugin's war task composes the war and sets web.xml itself.)
  if [ "$IM_LINE" != "6.0" ] && grep -q '^\s*exclude "WEB-INF/web.properties"$' "$mine/webapp/build.gradle" 2>/dev/null; then
    run sed -i.bak \
      -e 's|exclude "WEB-INF/web.properties"|exclude "WEB-INF/web.properties", "WEB-INF/web.xml"\n    webXml = file("${explodedWebAppDir}/WEB-INF/web.xml")|' \
      "$mine/webapp/build.gradle"
  fi
  # The mine's two Solr URLs (search, autocomplete) are baked in as localhost:8983. postprocess runs
  # on this host and indexes into whatever answers there, so a stack on another SOLR_PORT must
  # point them at its own port - otherwise it silently re-indexes the default stack's Solr.
  # trial-stage.sh later rewrites localhost:$SOLR_PORT to solr:8983 for the container. A no-op
  # when the files already name $SOLR_PORT (always so at the default 8983).
  for f in "$mine/dbmodel/resources/keyword_search.properties" \
           "$mine/dbmodel/resources/objectstoresummary.config.properties"; do
    if [ -f "$f" ] && ! grep -q "localhost:$SOLR_PORT/solr/" "$f"; then
      run sed -i "s|localhost:[0-9]*/solr/|localhost:$SOLR_PORT/solr/|" "$f"
    fi
  done
  write_file "$mine/project.xml" "$(cat out/_mine/project.xml)"
  # rdfc2im's own project.xml keeps HumanMine's full ~40-source list, our sources inserted as
  # replacements (USAGE.md) - correct for a full mine, wrong for this reduced demo build.
  # dbmodel:addSourceDependencies tries to resolve a Maven jar for every listed source, and the
  # ~39 stock sources we don't run were only ever published to JCenter/Bintray (dead since 2021,
  # confirmed live: 403 from jcenter.bintray.com, and confirmed absent from Maven Central too -
  # not a dead-link, genuinely unpublished anywhere else). Trim to just our own sources (all
  # share one `type`, set once in rdfc2im.yaml) - the same reduction LOAD-TRIAL.md's own
  # "Reducing a mine" section describes doing by hand for the original go-only trial ("project.xml
  # lists only humanmine-go"), generalised to all 9 and finally scripted instead of manual.
  # "reactome" (stock, type="reactome") is kept alongside our own humanmine-reactome by exact
  # name, not by type: sources.yaml's own `alongside: [reactome]` already declares it a real
  # dependency, not an unused extra - our own reactome source maps Pathway.description only, no
  # participants (the pathwayComponent link is unmapped/pruned - see sources.yaml's own note),
  # so without the stock source Pathway never connects to any Protein or Gene at all. Its own
  # jar (org.intermine:bio-source-reactome) is equally dead on JCenter/Maven Central, but unlike
  # the ~39 sources dropped above, this one is worth building from local source and keeping -
  # see phase_build_humanmine_items' sibling handling of the same JCenter problem.
  run python3 tools/reduce_mine.py sources "$mine/project.xml" humanmine-items reactome
  # Restrict to human only, matching the rest of this build - rdfc2im's own generated project.xml
  # carries this source's original "9606 10090" (human+mouse) value untouched.
  run sed -i 's|<property name="reactome.organisms" value="9606 10090"/>|<property name="reactome.organisms" value="9606"/>|' \
    "$mine/project.xml"
  # HumanMine's own priorities file, merged with our sources (rdfc2im project already did the
  # merge; this just deploys it) - re-syncing after adding a source is required, not optional
  # (confirmed live, LOAD-TRIAL.md's hgnc section, finding 3).
  write_file "$mine/dbmodel/resources/genomic_priorities.properties" "$(cat out/_mine/genomic_priorities.properties)"
  local prod_props
  local tree="$INTERMINE_TREE"
  if [ "$DRY_RUN" -eq 1 ] && [ -n "$INTERMINE_SRC" ] && [ ! -d "$tree" ]; then tree="$INTERMINE_SRC"; fi  # as in build_reactome_source
  prod_props=$(find "$tree" -path "*resources/src/main/resources/default.intermine.production.properties" -not -path "*/build/*" | head -1)
  [ -n "$prod_props" ] || die "default.intermine.production.properties not found under $tree - did make-inputs.sh (or publish_intermine) run?"
  # Must be the one defining integration.production, NOT bio/model's copy (integration.bio-test)
  # - confirmed live, LOAD-TRIAL.md: the wrong one fails with "Failed to instantiate
  # IntegrationWriter class".
  write_file "$HOME/.intermine/humanmine.properties" "$(cat <<PROPS
db.production=psql
db.production.datasource.serverName=localhost:$PG_PORT
db.production.datasource.databaseName=humanmine-production
db.production.datasource.user=intermine
db.production.datasource.password=intermine

db.common-tgt-items=psql
db.common-tgt-items.datasource.serverName=localhost:$PG_PORT
db.common-tgt-items.datasource.databaseName=humanmine-items
db.common-tgt-items.datasource.user=intermine
db.common-tgt-items.datasource.password=intermine

db.userprofile-production=psql
db.userprofile-production.datasource.serverName=localhost:$PG_PORT
db.userprofile-production.datasource.databaseName=humanmine-userprofile
db.userprofile-production.datasource.user=intermine
db.userprofile-production.datasource.password=intermine

default.intermine.properties.file=$prod_props
webapp.baseurl=http://localhost:$MINE_PORT
webapp.path=humanmine
# webapp/build.gradle's cargo {} block (Gradle-Cargo remote-Tomcat deploy plugin) eagerly reads
# this during Gradle's CONFIGURE phase, not lazily when a cargo task actually runs - confirmed
# live: it calls getServerName(props.getProperty("webapp.deploy.url")) with a null deployUrl,
# which NPEs on deployUrl.contains("//") and fails the whole project's configuration (blocking
# :dbmodel:builddb too, same class of problem as the gretty fix above). The code LOOKS like it
# should skip this via `if (props.hasProperty("webapp.hostname")) ... else getServerName(...)`,
# but that's a Groovy trap: Properties.hasProperty(key) is the Groovy MOP method (does this
# OBJECT have a declared field/property with this name?), not Properties.containsKey(key) - it
# is FALSE for every loaded entry, always, regardless of what's in the file, so the `else`
# branch always runs and webapp.hostname (tried first, see prior commit) can never help. Setting
# webapp.deploy.url instead works because THAT one is read with the real, correct
# Properties.getProperty(key) API. This build never runs a cargo task at all (deployment goes
# through the Tomcat container in trial/docker-compose.yml instead), so the value only needs to
# be a syntactically valid URL - reusing webapp.baseurl's is the natural choice.
webapp.deploy.url=http://localhost:$MINE_PORT
project.title=$MINE_TITLE
# Neither default.intermine.production.properties nor anywhere else sets these - every real
# InterMine deployment must supply its own (confirmed: grep for superuser.account across every
# upstream checkout found it only in test/CI fixtures, never a real default). Without it,
# :webapp:loadDefaultTemplates (part of :dbmodel:buildUserDB, which creates the userprofile
# schema) fails live: "Unable to load super user profile" / "Loading default templates and tags
# into profile null" - and without THAT, the webapp's own ActionServlet fails to initialise at
# startup ("userprofileOSW is null"), so InterMineContext never initialises and every request
# 500s with ContextNotInitialisedException, however long you wait. Values match the convention
# every one of intermine's own CI/test properties files uses (config/ci.properties etc).
superuser.account=superuser@intermine.org
superuser.initialPassword=intermine
PROPS
)"
  log "~/.intermine/humanmine.properties done (default.intermine.properties.file=$prod_props)"
}

phase_stage_src_data() {
  # project.xml's src.data.file for each of our sources points at rdfc2im.yaml's src_data_dir
  # (/micklem/data/rdfc2im/<source>/<source>.xml - a real Micklem-lab deployment path; USAGE.md
  # documents this as where "items/<source>.xml will live on the build machine", i.e. something
  # meant to be staged there, not rewritten). Nothing before this phase ever puts a file there -
  # confirmed live: :dbmodel:integrate died on the very first source, "Exception while reading
  # from: /micklem/data/rdfc2im/clinvar/clinvar.xml" - this step was simply missing. Symlink
  # rather than copy: these items files can be large (clinvar alone is 54039 items) and a
  # symlink keeps out/ as the single source of truth, so a later `rdfc2im items` re-run is
  # picked up without re-staging.
  for src in $SOURCES; do
    local dest_dir="/micklem/data/rdfc2im/$src"
    run mkdir -p "$dest_dir"
    run ln -sf "$HERE/out/$src/items/$src.xml" "$dest_dir/$src.xml"
  done
}

phase_start_databases() {
  # COMPOSE_FILES (and its docker-compose.local.yml, if BIND_ADDR needs one) is computed
  # globally, above - see that block's comment for why (resume-safety: this phase can be
  # skipped by --from without start_mine_stack losing access to it).
  run "${COMPOSE_ENV[@]}" $COMPOSE "${COMPOSE_FILES[@]}" up -d postgres solr
  log "waiting for postgres to report healthy..."
  if [ "$DRY_RUN" -eq 0 ]; then
    for _ in $(seq 1 60); do
      docker inspect --format '{{.State.Health.Status}}' "$PG_CONTAINER" 2>/dev/null | grep -q healthy && break
      sleep 2
    done
  fi
  for db in humanmine-production humanmine-items humanmine-userprofile; do
    # \gexec must be fed via stdin, not -c: confirmed live that psql's -c mode never recognises
    # it as a meta-command regardless of line placement (it's sent to the server as literal SQL
    # text and fails with "syntax error at or near \"\\\""), while the identical text piped
    # through stdin (`docker exec -i ... <<SQL`) works. `-i` + a heredoc, matching the same
    # pattern phase_apply_templates already uses below for demo_public_templates.sql.
    run bash -c "docker exec -i $PG_CONTAINER psql -U intermine -d postgres <<SQL
SELECT 'CREATE DATABASE \"$db\"' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')
\\gexec
SQL"
  done
  # Solr's image only precreates one core via `command:`; both of this mine's cores are made
  # here. tools/solr-search-schema-fix.sh does NOT run here (moved to phase_postprocess) - see
  # that phase's own comment for why: it needs a field type Solr's schemaless configset only
  # creates once real documents exist, which they don't yet on a freshly created, empty core.
  for core in humanmine-search humanmine-autocomplete; do
    run bash -c "docker exec $SOLR_CONTAINER solr create_core -c $core 2>&1 | grep -qv 'already exists' || true"
  done
}

phase_build_dbmodel() {
  local mine="$TRIAL_HOME/humanmine"
  # Regenerate the model from scratch. dbmodel/build holds the generated genomic_model.xml (and the
  # resources the later reduce_mine.py trims read), and Gradle considers producing it up to date
  # when only the CONTENT of the already-installed bio-source-humanmine-items jar changed - same
  # coordinates, new additions. Confirmed live: after Protein.keywords was added and the jar
  # rebuilt, `builddb` succeeded in 9s having regenerated nothing, and humanmine-uniprot then died
  # "Collection not found in class: Protein.keywords". A fresh checkout has no dbmodel/build, so
  # only a resume (--from) or a re-run hits this - and it looks exactly like success.
  run rm -rf "$mine/dbmodel/build"
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:builddb
  # builddb drops and recreates the production schema, renumbering every intermineobject.id, so
  # the humanmine-search core is instantly stale and stays that way until phase_postprocess
  # re-runs create-search-index. In that window /service/search does not degrade gracefully, it
  # 500s outright: SolrKeywordSearchHandler.getSearchHits() calls objMap.get(id) with no null
  # guard (Objects.getObjects silently omits ids the objectstore cannot resolve), and that null
  # reaches SearchUtils.parseResults, which calls getObject().getClass() on it - NPE, rendered to
  # the user as "Service failed. Please contact support.". Confirmed live by injecting a single
  # document with an unresolvable id into an otherwise healthy core: the endpoint 500'd
  # immediately and recovered the instant that one document was deleted. ONE dead id anywhere in
  # a result page takes down the whole request, not just that row.
  # Emptying the core here converts that hard 500 into an honest zero-hit `wasSuccessful: true`
  # until the index is rebuilt - a state phase_postprocess already passes through deliberately
  # while the webapp is live, so it is proven safe. `|| true` (unlike the bare `run curl -sf`
  # below) because with --from build_dbmodel after a volume wipe the core may not exist yet, and
  # a 404 should not abort the build.
  run bash -c "curl -sf 'http://localhost:$SOLR_PORT/solr/humanmine-search/update?commit=true' \
    -H 'Content-Type: application/json' -d '{\"delete\": {\"query\": \"*:*\"}}' >/dev/null || true"
  # os.production only - the userprofile database's own schema (savedtemplatequery, tag, ...)
# The merged mine model that reduce_mine.py reads. Plugins before the maint-2026 rework copied it to
# dbmodel/build/resources/main/; the maint-2026 plugin leaves it where mergeModels writes it,
# dbmodel/build/im/mergeModels/ (found 2026-11-16: with the old path every reduce step died
# "failed to load .../build/resources/main/genomic_model.xml" right after builddb).
merged_model_xml() {
  local f
  for f in "$1/dbmodel/build/im/mergeModels/genomic_model.xml" "$1/dbmodel/build/resources/main/genomic_model.xml"; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  echo "$1/dbmodel/build/resources/main/genomic_model.xml"   # not built yet (--dry-run): the traditional place
}

  # is a SEPARATE task, never run anywhere else in this script. Without it the webapp's own
  # ActionServlet fails to initialise at startup ("userprofileOSW is null" - confirmed live),
  # InterMineContext never initialises, and every single request 500s with
  # ContextNotInitialisedException regardless of how long you wait - a much bigger symptom than
  # its cause looks like. buildUserDB (not just createUserDB) also loads the superuser account
  # and default templates (:webapp:loadDefaultTemplates), which curation/demo_public_templates.sql
  # depends on via foreign key (phase_apply_templates' own inserts reference the superuser row).
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:buildUserDB
  # genomic_priorities.properties (as written by phase_prepare_mine_checkout) still has entries
  # for classes only some OTHER, unrun stock source would have contributed (ProteinDomain, from
  # protein-atlas) - the exact "Reducing a mine" failure LOAD-TRIAL.md documents: PriorityConfig
  # throws "Class 'ProteinDomain' not found in model", which fails IntegrationWriter
  # instantiation for every single source, not just one - confirmed live. Must run AFTER builddb
  # (needs the real merged genomic_model.xml, not the live HumanMine model - same rule LOAD-
  # TRIAL.md states) and BEFORE integrate_sources (which needs a working IntegrationWriter).
  # shellcheck disable=SC1090
  source "$HERE/.venv/bin/activate"
  run python3 tools/reduce_mine.py priorities \
    "$mine/dbmodel/resources/genomic_priorities.properties" \
    "$(merged_model_xml "$mine")"
  # Same "Reducing a mine" class of problem, different file and a much quieter failure:
  # objectstoresummary.config.properties names HPOTerm/InteractionTerm/ProteinDomain (and
  # Interaction/InteractionRegion) in a reduced build that loads none of them.
  # AutoCompleter.buildIndex looks each ".autocomplete" class up by fully-qualified name and
  # throws when the model has no descriptor, so create-autocomplete-index dies - but
  # PostProcessPlugin CATCHES that, prints only "POSTPROCESS ... FAILED" plus the wrapped
  # exception's generic message, and carries on, leaving the build's exit code at 0. Confirmed
  # live: it failed on every run today that reached it and went unnoticed for exactly that
  # reason. Both copies are trimmed - the source under resources/ and, when it already exists,
  # the processResources output under build/resources/main/ that the postprocess classpath
  # (dirset over buildDir) actually reads.
  for f in "$mine/dbmodel/resources/objectstoresummary.config.properties" \
           "$mine/dbmodel/build/resources/main/objectstoresummary.config.properties"; do
    [ -f "$f" ] || continue
    run python3 tools/reduce_mine.py objectstoresummary "$f" \
      "$(merged_model_xml "$mine")" \
      "$HERE/curation/autocomplete_override.properties"
  done
  # webconfig-model.xml is the remaining "Reducing a mine" file, and its failure is NOT cosmetic:
  # widgets whose paths no longer resolve make InterMine's WebConfig reject the whole file, so
  # every classic-UI page renders an error banner AND logs a full Struts/Tiles stack trace. That
  # log storm filled the container's writable layer (localhost.log reached 2.3GB, ddi-ws.log
  # 1.3GB) until /var/lib/docker hit 100% and took Postgres down mid-WAL-redo. Trimming the
  # widgets that cannot work (they reference data this build does not load) is what stops it.
  run python3 tools/reduce_mine.py webconfig \
    "$mine/webapp/src/main/webapp/WEB-INF/webconfig-model.xml" \
    "$(merged_model_xml "$mine")"
}

phase_integrate_sources() {
  local mine="$TRIAL_HOME/humanmine"
  # Load order matters for `alongside` sources (uniprot, reactome): each must integrate after
  # the stock source it supplements, or it duplicates instead of merging (confirmed live,
  # commit 323e6fe). rdfc2im's own generated project.xml already encodes the correct order and
  # `check` already validated it - read it back rather than re-deciding the order here. Matches
  # ANY source name, not just humanmine-* ones: confirmed live that restricting to
  # "humanmine-[a-z]+" silently skipped the stock "reactome" alongside source entirely (added
  # back into project.xml by phase_prepare_mine_checkout's reduce_mine.py call, but this regex
  # predates that and was never updated) - integrate_sources ran all 9 of our own sources with
  # no error, reactome's own real data just never made it into the database, only found by
  # checking for pathway-protein rows after a "successful" build. project.xml is already
  # trimmed to exactly the sources we want by this point, so no prefix filter is needed at all.
  local order
  order=$(grep -oP '(?<=<source name=")[A-Za-z0-9_-]+(?=")' "$mine/project.xml" 2>/dev/null || true)
  if [ -z "$order" ] && [ "$DRY_RUN" -eq 1 ]; then
    order="reactome humanmine-$(echo "$SOURCES" | sed 's/ /\nhumanmine-/g')"  # placeholder so dry-run still shows the loop shape
    log "note: $mine/project.xml does not exist yet in this dry run - showing SOURCES as a stand-in for the real (project.xml-derived) load order"
  fi
  for src in $order; do
    run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:integrate -Psource="$src"
  done
}

phase_postprocess() {
  # Order from HumanMine's own project.xml <post-processing> block (LOAD-TRIAL.md). The
  # genomic-location-specific tasks (create-chromosome-locations-and-lengths,
  # transfer-sequences, create-gene-flanking-features, create-location-overlap-index,
  # create-overlap-view, populate-child-features) are deliberately not run: this build loads no
  # coordinate/sequence data, so they would no-op or fail on a missing prerequisite rather than
  # produce anything real (confirmed live). update-data-sources needs a Micklem-lab-specific
  # file path this build does not have; also skipped.
  local mine="$TRIAL_HOME/humanmine"
  for task in create-references create-attribute-indexes; do
    run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess="$task"
  done
  # Gene.pathways is populated ONLY by reactome's own source postprocessor - stock
  # reactome_additions.xml says so in as many words ("<!-- populated by postprocess -->" above
  # its Gene class), and ReactomePostProcess's javadoc is literally "Copy over Protein.pathways
  # to Gene.pathways": it derives the gene-level links by walking Gene<->Protein over the
  # protein-level ones the converter loaded. Without it, genespathways stays empty (confirmed
  # live: 0 rows) even though pathwayproteins is fully populated.
  #
  # Two things are needed, in this order. First rebuild the jar WITH the postprocessor class,
  # now that builddb has produced the mine's own dbmodel.jar to compile it against (see
  # _install_reactome_jar's header for the chicken-and-egg this resolves).
  _install_reactome_jar with-postprocess
  # Then run it. `do-sources` is the ONLY task that dispatches source-specific postprocessors
  # (PostProcessPlugin.groovy: every other process name goes down the "core postprocess" branch
  # instead). It is NOT being run blind/umbrella-wide here - that same plugin reads an optional
  # `-Psource=` and restricts itself to exactly those sources (line 75-82: an empty value is
  # what makes it iterate every source in project.xml). Scoping it to reactome alone keeps the
  # existing "do-sources is too broad to run blind" caution intact while still getting this one
  # source's postprocessor run - confirmed live: logs "Performing source postprocess on
  # reactome" and nothing else.
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=do-sources -Psource=reactome
  # solr-search-schema-fix.sh must run AFTER a first create-search-index pass, not before:
  # confirmed live, calling it against a freshly created empty core 400s with "The field type
  # 'analyzed_string' is not present in this schema, and so cannot be replaced" - Solr's
  # schemaless configset only creates that field type once a real document uses it (see that
  # script's own header comment). Originally called from phase_start_databases, right after the
  # core is created and before anything has been indexed into it - moved here instead. Its own
  # header comment already documents the fix-then-reindex sequence (the schema change is not
  # retroactive): index once, fix the type, clear the now-wrongly-analyzed docs, index again.
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=create-search-index
  run env SOLR_URL="http://localhost:$SOLR_PORT" sh tools/solr-search-schema-fix.sh
  run curl -sf "http://localhost:$SOLR_PORT/solr/humanmine-search/update?commit=true" \
    -H "Content-Type: application/json" -d '{"delete": {"query": "*:*"}}'
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=create-search-index
  for task in create-autocomplete-index summarise-objectstore; do
    run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess="$task"
  done
}

phase_build_webapp() {
  local mine="$TRIAL_HOME/humanmine"
  # Run copyWebappContent once on its own FIRST, so it has a history when the war build runs it.
  # unwarBioWebApp expands the bio-webapp war into build/explodedWebApp; copyWebappContent then
  # copies src/main/webapp into the same directory - its declared output. Gradle treats a task
  # with no history as owning nothing that already exists in its output directory and removes it,
  # so on the very first :webapp:war of a fresh checkout the copy deleted what the unwar had just
  # produced (2739 files down to 5, web.xml among the losses) and warWebApp died with "File
  # .../explodedWebApp/WEB-INF/web.xml specified for property 'webXml' does not exist". Any later
  # run has a history and passes, which is exactly why hand-run sessions never saw it: they had
  # always run the task at least once already. With the history in place :webapp:war's own unwar ->
  # copy sequence then leaves both sets of files - the war's, overlaid by src/main/webapp's.
  # The 6.0 line has no copyWebappContent: the plugin's war task composes the war from the task
  # outputs (unwarBioWebApp is a Sync), so a first run is no different from a later one.
  if [ "$IM_LINE" != "6.0" ]; then
    run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :webapp:copyWebappContent
  fi
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :webapp:war
}

phase_resolve_bluegenes_deps() {
  # Confirmed live 2026-09-21 (standalone, ahead of any real build attempt): resolves to exactly
  # 178 jars, matching LOAD-TRIAL.md's number exactly - see this script's header comment. If the
  # `org.intermine:bluegenes:1.4.5` coordinate or the Clojars repo ever changes, this fails loudly
  # at `resolveBgDeps` (an unresolvable dependency), not silently.
  local bgdir="$TRIAL_HOME/bgdeps"
  write_file "$bgdir/build.gradle" "$(cat <<'GRADLE'
repositories {
    maven { url 'https://repo.clojars.org' }
    mavenCentral()
}
configurations { bluegenes }
dependencies { bluegenes 'org.intermine:bluegenes:1.4.5' }
task resolveBgDeps(type: Copy) {
    from configurations.bluegenes
    into "$buildDir/lib"
}
task classpathTxt {
    doLast {
        file("$projectDir/classpath.txt").text =
            configurations.bluegenes.resolvedConfiguration.resolvedArtifacts
                .collect { it.file.absolutePath }.join(':')
    }
}
GRADLE
)"
  write_file "$bgdir/settings.gradle" "rootProject.name = 'bgdeps'"
  # No ./gradlew here (this is a throwaway project, not a checkout) - needs a plain Gradle 4.9
  # launcher on PATH or at $GRADLE49 (see this script's header comment).
  run_in "$bgdir" "${GRADLE_ENV[@]}" "$GRADLE49" resolveBgDeps classpathTxt
  if [ "$DRY_RUN" -eq 0 ]; then
    [ -f "$bgdir/classpath.txt" ] || die "bgdeps/classpath.txt was not produced - see this function's header comment"
  fi
}

phase_stage_artifacts() {
  run env TRIAL_HOME="$TRIAL_HOME" PG_PORT="$PG_PORT" SOLR_PORT="$SOLR_PORT" sh tools/trial-stage.sh
}

phase_start_mine_stack() {
  run "${COMPOSE_ENV[@]}" $COMPOSE "${COMPOSE_FILES[@]}" up -d mine bluegenes
  # The webapp reads the database once, at startup - postprocessing and the war it's serving
  # must both be in place before this, and it must run again after either changes.
  run docker restart "$MINE_CONTAINER"
}

phase_apply_templates() {
  [ "$SKIP_TEMPLATES" -eq 1 ] && { log "skipped (--skip-templates)"; return 0; }
  [ -f curation/demo_public_templates.sql ] || { log "no curation/demo_public_templates.sql - skipping"; return 0; }
  run bash -c "docker exec -i $PG_CONTAINER psql -U intermine -d humanmine-userprofile < curation/demo_public_templates.sql"
  run docker restart "$MINE_CONTAINER"
}

phase_verify() {
  if [ "$DRY_RUN" -eq 1 ]; then log "skipping live checks under --dry-run"; return 0; fi
  sleep 5
  run curl -sf "http://localhost:$MINE_PORT/humanmine/service/version"
  run curl -sf "http://localhost:$MINE_PORT/humanmine/service/model" -o /dev/null
  run curl -sf "http://localhost:$BG_PORT/" -o /dev/null
  log "mine webapp: http://localhost:$MINE_PORT/humanmine  BlueGenes: http://localhost:$BG_PORT"
  log "if BIND_ADDR is still 127.0.0.1 (the default), reach these via: ssh -L $MINE_PORT:localhost:$MINE_PORT -L $BG_PORT:localhost:$BG_PORT ..."
  log "live checks: MINE_BASE=http://localhost:$MINE_PORT/humanmine SOLR_BASE=http://localhost:$SOLR_PORT make test-live"
}

# ============================================================== main
run_phase() { local p=$1; phase_start "$p"; "phase_$p"; phase_end; }

# check_prereqs sets GRADLE_ENV (the JAVA_HOME override every gradle call below needs) as a
# side effect - it must run even when --from/--only skip past it in the phase list, or every
# gradle invocation in a resumed build silently loses that override. Always run it once, here,
# regardless of --from/--only; the loop below explicitly skips it so `--only check_prereqs`
# still runs it exactly once, not twice.
run_phase check_prereqs
CURRENT_PHASE=main

started=0
for p in "${PHASES[@]}"; do
  [ "$p" = "check_prereqs" ] && continue  # already ran, unconditionally, above
  if [ -n "$ONLY_PHASE" ]; then
    [ "$p" = "$ONLY_PHASE" ] && run_phase "$p"
    continue
  fi
  if [ -n "$FROM_PHASE" ] && [ "$started" -eq 0 ]; then
    [ "$p" = "$FROM_PHASE" ] && started=1 || continue
  else
    started=1
  fi
  run_phase "$p"
done

CURRENT_PHASE=main
log "build complete. Per-phase timings:"
if [ -s "$TIMING_TSV" ]; then
  sort -t $'\t' -k3 -rn "$TIMING_TSV" | while IFS=$'\t' read -r name _ secs _; do
    log "  ${secs}s  $name"
  done
fi
log "full log: $LOGFILE"
