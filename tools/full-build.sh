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
#   --report-layout FILE  After the demo templates, in phase apply_templates: load the HumanMine templates the
#                       mine's model can run (tools/apply_humanmine_templates.py on the sibling file
#                       humanmine_templates.xml) and set HumanMine's Gene report layout, filtered to what this mine
#                       and BlueGenes can show, as the bluegenes-properties key layout.report
#                       (tools/apply_report_layout.py FILE). FILE is HumanMine's /service/bluegenes-properties
#                       response: curation/humanmine_bluegenes_properties.json. Both write through the web service
#                       as the superuser, so the mine must be up (they wait up to 5 minutes); BUILD.md,
#                       "The report layout". Default off.
#   --tools-url URL     The BlueGenes whose /api/tools/all lists the tools the layout may keep (default
#                       http://localhost:$BG_PORT, the stack's bare BlueGenes, which has no patched tools; for the
#                       ut demo give the front, http://localhost:15001). Also REPORT_LAYOUT_TOOLS_URL.
#   --public-lists DIR  In phase apply_public_lists (after apply_templates), make the Genomics England PanelApp lists
#                       (one per panel, Green genes only) and HumanMine's 13 other public lists
#                       (curation/public_lists) public lists of the mine, as the superuser, through the web service
#                       (tools/apply_public_lists.py). DIR is the PanelApp cache group (rdfc2im cache save panelapp,
#                       which is not redistributable yet: BUILD.md, "Genomics England gene lists"). The mine's current
#                       public lists are archived first, to a new dated directory of --public-lists-archive. A rebuild
#                       wipes the userprofile database, so a rebuild needs this flag again. Default off.
#   --public-lists-archive DIR  The archive repository (a historic_artefacts checkout, with scripts/): each run adds
#                       DIR/humanmine-public-lists/<date>[-N]/. Required with --public-lists.
#   --public-lists-select all|100k  All panels (default), or the 175 of HumanMine's 2021 scope.
#   --public-lists-names 2021|current  The 17 panels renamed in PanelApp since 2021 keep their 2021 list names
#                       (default) or take the current panel names.
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
#   --stock-sources "a b"  Stock HumanMine/InterMine sources to load beside the rdfc2im ones (the
#                       hybrid testbed, epic im-9n4): names from rdfc2im/data/stock_sources.yaml
#                       (`python3 -m rdfc2im stock list`). Default empty: a build exactly as without
#                       the option. Needs --intermine-src on the 6.0 line (D-5) and --taxon 9606.
#                       check_prereqs validates the list as it does --sources; build_stock_sources
#                       builds or checks their loader jars, fetch_stock_data downloads the upstream
#                       files (cache groups stock-raw-<name> under $RDFC2IM_STOCK_DIR/cache, keyed to
#                       each file's URL and Last-Modified), subset_stock_data cuts them to the gene
#                       panel with tools/subset_raw.py (cache groups stock-<name>, keyed to genes_md5),
#                       stage_src_data links the results into HumanMine's own data paths under the
#                       data root, and rdfc2im project / reduce_mine.py keep their <source> entries.
#                       With a non-empty list the build also gates its ID resolver (plan 50 2.2): fetch_stock_data
#                       downloads NCBI's Homo_sapiens.gene_info.gz (cache group stock-raw-resolver),
#                       subset_stock_data writes it, filtered, as $RDFC2IM_STOCK_DIR/resolver/entrez, and
#                       prepare_mine_checkout sets resolver.file.rootpath to that directory in
#                       humanmine.properties and deletes any stale idresolver.cache.
#   --with-genome-sequence  Also load the GRCh38 genome FASTA (stock source ncbi-fasta, filtered to the 24
#                       chromosomes the ncbi-gff loader maps) and run transfer-sequences, which gives
#                       Chromosome.sequence and the sequences of every located feature. Needs ncbi-gff in
#                       --stock-sources. Off by default: a 973 MB download, about 3.1 GB unpacked twice
#                       (filtered file and its cache group) and the same again in Postgres [im-9n4.9].
#                       Without it Chromosome.length comes from the GFF's ##sequence-region lines.
#   --resolver-scope panel|taxon  What that entrez file holds: taxon (default) every gene of --taxon, so the
#                       mine holds all human genes as identifiers and interaction/orthologue partners outside
#                       the panel still resolve (plan 50 D-1); panel only the panel genes (strict subset).
#   --gene-identifiers panel|all  Which human genes the RDF identifier sources hold. panel (default): ncbigene and
#                       hgnc are fetched for the --genes panel like every other gene-shaped source. all: both are
#                       SCOPE_MODE full (every human gene of the types the stock ncbi-gene loader keeps:
#                       sources.yaml full_scope_filter), so interaction partners have symbols and a list resolves
#                       by symbol, HGNC id or Ensembl id (plan 50 2.2 b, D-1). The deep annotation stays on the
#                       panel, and so do the id sets subset_raw cuts the stock files to and the PMIDs pubmed is
#                       fetched for. Their cache groups are recorded as scope=full: give them a cache of their own
#                       (--cache-dir), not the panel's release cache [im-9n4.40].
#   --stock-local DIR   Local copies of stock data: DIR/<source>/<raw file name>. Used instead of a
#                       download when present; the only way in for a source that is not
#                       redistributable (OMIM: D-7). Also RDFC2IM_STOCK_LOCAL.
#   --jbrowse2-src DIR  The jbrowse2 bluegenes-tool checkout (also env JBROWSE2_SRC): stage_artifacts then
#                       runs tools/stage-bluegenes-tools.sh, which writes the patched BlueGenes tool set to
#                       <artifacts>/bluegenes-tools-patched and installs it to <artifacts>/bluegenes-tools
#                       (BUILD.md, "The patched BlueGenes tool set"). Without it stage_artifacts is as before.
#   --with-front        After the stack is up, start the aligner and nginx front (trial/front/up.sh). Off by
#                       default.
#   --source-pages DIR  Add a last phase, write_source_manifest (after verify): tools/source_manifest.py writes
#                       out/_mine/source_manifest.json (URLs, Last-Modified, fetch times, sizes, sha256, filters,
#                       records read and kept, field counts, objects loaded per class from the mine) and
#                       tools/source_pages.py writes the data-source status pages (Markdown) into DIR. Off by
#                       default; BUILD.md, "Data-source status pages" [im-9n4.42].
#   --data-set-links URL  In prepare_mine_checkout, add a last source, data-set-links (type humanmine-items), that sets
#                       DataSet.url to the status page URL/<kind>-<source>.md and DataSet.description on every data
#                       set the selected sources write, with first priority for both fields. URL is where the pages
#                       are published (e.g. the humanmine repository's docs/data-sources/ on GitHub). Off by default.
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
#   RDFC2IM_DATA_ROOT Directory the mine's source data lives under (default /micklem/data, the
#                     Micklem-lab layout rdfc2im.yaml's src_data_dir and HumanMine's project.xml
#                     name). stage_src_data symlinks each source's items file into
#                     $RDFC2IM_DATA_ROOT/rdfc2im/<src>/, the Reactome map goes to
#                     $RDFC2IM_DATA_ROOT/reactome/current/, and the mine checkout's copy of
#                     project.xml has every /micklem/data/ rewritten to the root. Set it per stack
#                     (e.g. under that stack's own home) so two stacks do not share or overwrite
#                     one another's staged files. Unset keeps the shared /micklem/data layout.
#   RDFC2IM_PREFIX    Container and volume name prefix (default rdfc2im; see --stack-name).
#   RDFC2IM_PGDATA, RDFC2IM_SOLRDATA   Host directories the PostgreSQL and Solr data live in, bind-
#                     mounted by trial/docker-compose.yml's volumes (created by start_databases).
#                     Default unset: ordinary named Docker volumes under /var/lib/docker. Set them
#                     before the stack's first start_databases (an existing volume keeps its kind).
#   RDFC2IM_ARTIFACTS Directory stage_artifacts writes the exploded war (humanmine/) and BlueGenes' jars
#                     (bluegenes-lib/) to, and the compose file bind-mounts into the mine and BlueGenes
#                     containers [im-ore.21]. Default: trial/artifacts in the checkout for the default
#                     stack, $TRIAL_HOME/artifacts with --stack-name - so a named stack's rebuild can
#                     never replace the webapp another stack is serving.
#   GRADLE_USER_HOME  Gradle's user home: caches, daemons, gradle.properties (default $HOME/.gradle).
#                     Passed, with -Duser.home=$HOME in JAVA_TOOL_OPTIONS, to every Gradle call -
#                     JDK 8 takes user.home from the passwd entry and ignores $HOME, so a private HOME
#                     was silently bypassed without them.
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
#   RDFC2IM_STOCK_DIR Where --stock-sources keeps its raw downloads (cache/stock-raw-<name>), the
#                     filtered and unpacked files (subset/, whole/) and the panel id sets (idsets/).
#                     Default $RDFC2IM_DATA_ROOT/_stock. Raw data is large (UniProt Swiss-Prot human
#                     175 MB, IntAct human 1 GB, the genome 973 MB gzipped): put it on a big disk, never
#                     under the worktree or a small root (check_prereqs checks the free space).
#   RDFC2IM_STOCK_FILTERED_CACHE  Where subset_stock_data keeps the filtered groups (stock-<name>) of
#                     redistributable stock sources. Default the raw-data cache (--cache-dir, the CI
#                     release asset's source); restricted sources always stay in $RDFC2IM_STOCK_DIR/cache.
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
# Likewise the bio sources: the maint-2026 branch of the humanmine-bio-sources fork is converted to
# Gradle 8 / maven-publish / the 6.0.+ line, so the 6.0 line builds humanmine-items inside it [im-ore.23]
HUMANMINE_BIO_60_URL=${HUMANMINE_BIO_60_URL:-https://github.com/gmicklem/humanmine-bio-sources.git}
HUMANMINE_BIO_60_REF=${HUMANMINE_BIO_60_REF:-maint-2026}
BIND_ADDR=${BIND_ADDR:-127.0.0.1}
MINE_TITLE=${MINE_TITLE:-"rdfc2im: 114 gene food/drug-metabolism panel"}

# The demo panel this project actually built and verified this session (STATUS.md Table 2 /
# LOAD-TRIAL.md). Each source's scope mode decides which rdfc2im CLI flags it gets in
# phase_rdfc2im_pipeline - see that function. Override with --sources for a different build.
SOURCES=${SOURCES:-"go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed"}
GENE_PANEL=${GENE_PANEL:-"$HERE/curation/demo_gene_panel.txt"}
TAXON=${TAXON:-9606}
SKIP_TEMPLATES=0
REPORT_LAYOUT=""
TOOLS_URL=${REPORT_LAYOUT_TOOLS_URL:-}
PUBLIC_LISTS=""
PUBLIC_LISTS_ARCHIVE=""
PUBLIC_LISTS_SELECT=all
PUBLIC_LISTS_NAMES=2021
USE_CACHED_DATA=0
OFFLINE=0
[ "${RDFC2IM_OFFLINE:-}" = 1 ] && { OFFLINE=1; USE_CACHED_DATA=1; }
RAW_CACHE_DIR=${RAW_CACHE_DIR:-"$HERE/cached_raw_data"}
REACTOME_LEVELS=${REACTOME_LEVELS:-default}
STOCK_SOURCES=${STOCK_SOURCES:-}
STOCK_LOCAL=${RDFC2IM_STOCK_LOCAL:-}
RESOLVER_SCOPE=taxon
GENE_IDENTIFIERS=panel
WITH_GENOME_SEQUENCE=0
JBROWSE2_SRC=${JBROWSE2_SRC:-}
WITH_FRONT=0
SOURCE_PAGES=""
DATA_SET_LINKS=""
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
        build_stock_sources fetch_stock_data subset_stock_data prepare_mine_checkout stage_src_data
        start_databases build_dbmodel integrate_sources postprocess build_webapp
        resolve_bluegenes_deps stage_artifacts start_mine_stack apply_templates apply_public_lists verify)

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
    --report-layout) REPORT_LAYOUT=$2; shift ;;
    --tools-url) TOOLS_URL=$2; shift ;;
    --public-lists) PUBLIC_LISTS=$2; shift ;;
    --public-lists-archive) PUBLIC_LISTS_ARCHIVE=$2; shift ;;
    --public-lists-select) PUBLIC_LISTS_SELECT=$2; shift ;;
    --public-lists-names) PUBLIC_LISTS_NAMES=$2; shift ;;
    --use-cached-data) USE_CACHED_DATA=1 ;;
    --offline) OFFLINE=1; USE_CACHED_DATA=1 ;;
    --cache-dir) RAW_CACHE_DIR=$2; shift ;;
    --reactome-levels) REACTOME_LEVELS=$2; shift ;;
    --stack-name) STACK_NAME=$2; shift ;;
    --intermine-src) INTERMINE_SRC=$2; shift ;;
    --stock-sources) STOCK_SOURCES=$2; shift ;;
    --stock-local) STOCK_LOCAL=$2; shift ;;
    --with-genome-sequence) WITH_GENOME_SEQUENCE=1 ;;
    --resolver-scope) RESOLVER_SCOPE=$2; shift ;;
    --gene-identifiers) GENE_IDENTIFIERS=$2; shift ;;
    --jbrowse2-src) JBROWSE2_SRC=$2; shift ;;
    --with-front) WITH_FRONT=1 ;;
    --source-pages) SOURCE_PAGES=$2; shift ;;
    --data-set-links) DATA_SET_LINKS=$2; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

# build_reactome_source became build_stock_sources (reactome first, then any --stock-sources); the
# old name still works for --from/--only.
[ "$FROM_PHASE" = build_reactome_source ] && FROM_PHASE=build_stock_sources
[ "$ONLY_PHASE" = build_reactome_source ] && ONLY_PHASE=build_stock_sources
STOCK_SOURCES=$(echo ${STOCK_SOURCES//,/ })   # one space between names; commas allowed
# --with-genome-sequence is ncbi-fasta added to the stock list (its table entry brings transfer-sequences
# and needs ncbi-gff, which check_prereqs enforces through `rdfc2im stock check`)
if [ "$WITH_GENOME_SEQUENCE" -eq 1 ]; then
  case " $STOCK_SOURCES " in
    *" ncbi-gff "*) ;;
    *) echo "--with-genome-sequence needs ncbi-gff in --stock-sources (the sequences are cut by its locations)" >&2; exit 2 ;;
  esac
  case " $STOCK_SOURCES " in *" ncbi-fasta "*) ;; *) STOCK_SOURCES="$STOCK_SOURCES ncbi-fasta" ;; esac
fi
case "$RESOLVER_SCOPE" in
  panel|taxon) ;;
  *) echo "--resolver-scope wants panel or taxon, not '$RESOLVER_SCOPE'" >&2; exit 2 ;;
esac
# --gene-identifiers all: the identifier sources hold every human gene; everything else keeps its mode
case "$GENE_IDENTIFIERS" in
  panel) ;;
  all) SCOPE_MODE[ncbigene]=full; SCOPE_MODE[hgnc]=full ;;
  *) echo "--gene-identifiers wants panel or all, not '$GENE_IDENTIFIERS'" >&2; exit 2 ;;
esac

case "$PUBLIC_LISTS_SELECT" in
  all|100k) ;;
  *) echo "--public-lists-select wants all or 100k, not '$PUBLIC_LISTS_SELECT'" >&2; exit 2 ;;
esac
case "$PUBLIC_LISTS_NAMES" in
  2021|current) ;;
  *) echo "--public-lists-names wants 2021 or current, not '$PUBLIC_LISTS_NAMES'" >&2; exit 2 ;;
esac
if [ -n "$PUBLIC_LISTS" ] && [ -z "$PUBLIC_LISTS_ARCHIVE" ]; then
  echo "--public-lists needs --public-lists-archive DIR: the mine's current public lists are archived before they are replaced" >&2
  exit 2
fi

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
# The mine's data root (project.xml's src.data.* paths). /micklem/data is where rdfc2im.yaml's
# src_data_dir and HumanMine's own project.xml point; RDFC2IM_DATA_ROOT moves everything this
# script stages and rewrites project.xml to match [im-ore.7].
DATA_ROOT=${RDFC2IM_DATA_ROOT:-/micklem/data}; DATA_ROOT=${DATA_ROOT%/}
# --stock-sources' working area (see RDFC2IM_STOCK_DIR above). The raw download groups live in their
# own cache directory there, not in $RAW_CACHE_DIR (cached_raw_data/, published as the CI release
# asset): only the small filtered groups of redistributable sources go there.
STOCK_DIR=${RDFC2IM_STOCK_DIR:-"$DATA_ROOT/_stock"}; STOCK_DIR=${STOCK_DIR%/}
STOCK_RAW_CACHE="$STOCK_DIR/cache"
STOCK_FILTERED_CACHE=${RDFC2IM_STOCK_FILTERED_CACHE:-}; STOCK_FILTERED_CACHE=${STOCK_FILTERED_CACHE%/}
# The ID resolver's data directory (resolver.file.rootpath): EntrezGeneIdResolverFactory reads
# $RESOLVER_ROOT/entrez, plain text in NCBI gene_info format (plan 50 2.2). Only used with --stock-sources.
RESOLVER_ROOT="$STOCK_DIR/resolver"
RESOLVER_GROUP=stock-raw-resolver
PG_CONTAINER="$RDFC2IM_PREFIX-postgres"
SOLR_CONTAINER="$RDFC2IM_PREFIX-solr"
MINE_CONTAINER="$RDFC2IM_PREFIX-mine"
BG_CONTAINER="$RDFC2IM_PREFIX-bluegenes"   # shares the mine container's network namespace: restart both together
# Every compose call gets the stack's names and ports explicitly (trial/docker-compose.yml reads
# them, with the default stack's values as its own defaults).
COMPOSE_ENV=(env PG_PORT="$PG_PORT" SOLR_PORT="$SOLR_PORT" MINE_PORT="$MINE_PORT" BG_PORT="$BG_PORT"
             RDFC2IM_PREFIX="$RDFC2IM_PREFIX")
[ -n "$COMPOSE_PROJECT_NAME" ] && COMPOSE_ENV+=(COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME")
# Host directories for the PostgreSQL and Solr data (bind-mounted by the compose volumes; unset =
# ordinary named volumes). phase_start_databases creates them.
[ -n "${RDFC2IM_PGDATA:-}" ] && COMPOSE_ENV+=(RDFC2IM_PGDATA="$RDFC2IM_PGDATA")
[ -n "${RDFC2IM_SOLRDATA:-}" ] && COMPOSE_ENV+=(RDFC2IM_SOLRDATA="$RDFC2IM_SOLRDATA")
# Staged webapp and BlueGenes jars, bind-mounted by the compose file. Per stack: a named stack's
# own TRIAL_HOME, so one stack's rebuild cannot replace what another serves [im-ore.21]. The default
# stack leaves it unset for the compose file's own ./artifacts (= trial/artifacts) default.
ARTIFACTS_DIR=${RDFC2IM_ARTIFACTS:-}
[ -n "$ARTIFACTS_DIR" ] || { [ -z "$STACK_NAME" ] || ARTIFACTS_DIR="$TRIAL_HOME/artifacts"; }
[ -z "$ARTIFACTS_DIR" ] || COMPOSE_ENV+=(RDFC2IM_ARTIFACTS="$ARTIFACTS_DIR")

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
# --source-pages: one more phase at the very end; without it the phase list is as before [im-9n4.42]
[ -z "$SOURCE_PAGES" ] || PHASES+=(write_source_manifest)
if [ "$LIST_PHASES" -eq 1 ]; then printf '%s\n' "${PHASES[@]}"; exit 0; fi

mkdir -p "$LOG_DIR"
: > "$TIMING_TSV" 2>/dev/null || true
log "full-build.sh starting - run id $RUN_ID, log $LOGFILE, dry_run=$DRY_RUN"
log "sources: $SOURCES"
log "trial home: $TRIAL_HOME"
log "raw-data cache: $RAW_CACHE_DIR (use_cached_data=$USE_CACHED_DATA offline=$OFFLINE)"
[ -z "$STOCK_SOURCES" ] || log "stock sources: $STOCK_SOURCES (working area $STOCK_DIR${STOCK_LOCAL:+, local copies $STOCK_LOCAL})"
if [ -n "$INTERMINE_SRC" ]; then
  log "intermine-src: $INTERMINE_SRC (InterMine $IM_VERSION, $IM_LINE line, mine Gradle $IM_GRADLE_VERSION${IM_GRADLE_SHA256:+, sha256 ${IM_GRADLE_SHA256:0:12}...})"
else
  log "intermine: published artefacts (the mine's own imVersion/bioVersion pins)"
fi
log "stack: containers $RDFC2IM_PREFIX-*, compose project ${COMPOSE_PROJECT_NAME:-trial (default)}, ports pg=$PG_PORT solr=$SOLR_PORT mine=$MINE_PORT bluegenes=$BG_PORT"

# JDK 8 takes user.home from the passwd entry, NOT from $HOME, and Gradle's own default for its user
# home (~/.gradle: caches, daemons, gradle.properties) and InterMine's ~/.intermine/*.properties
# both hang off user.home.  Without these two a build run with a private HOME silently used (and
# wrote into) the real account's ~/.gradle and ~/.intermine - the fb-env*.sh scripts worked around it
# with JAVA_TOOL_OPTIONS in the caller's environment, which a plain `HOME=... full-build.sh` lacked.
# GRADLE_HOME_ENV goes into every Gradle invocation below, explicitly.  im-ore.4.
GRADLE_USER_HOME=${GRADLE_USER_HOME:-"$HOME/.gradle"}
export GRADLE_USER_HOME
case " ${JAVA_TOOL_OPTIONS:-} " in
  *" -Duser.home=$HOME "*) _java_tool_options=$JAVA_TOOL_OPTIONS ;;
  *) _java_tool_options="${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }-Duser.home=$HOME" ;;
esac
GRADLE_HOME_ENV=("GRADLE_USER_HOME=$GRADLE_USER_HOME" "JAVA_TOOL_OPTIONS=$_java_tool_options")

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
  GRADLE_ENV=(env "JAVA_HOME=$JAVA8_HOME" "${GRADLE_HOME_ENV[@]}")
  log "JAVA8_HOME=$JAVA8_HOME, GRADLE_USER_HOME=$GRADLE_USER_HOME, user.home=$HOME"
  [ -f "$GENE_PANEL" ] || die "gene panel file not found: $GENE_PANEL"
  # A misspelled --sources entry falling through to SCOPE_MODE's ${...:-none} default would
  # silently fetch that source completely unscoped instead of erroring - exactly the kind of
  # mistake that would only surface hours later as an unexpectedly huge ClinVar/UniProt pull.
  # Fail fast, before any real work starts, on any name not in SCOPE_MODE at all.
  for src in $SOURCES; do
    [ -v "SCOPE_MODE[$src]" ] || die "unknown source '$src' - not in SCOPE_MODE (tools/full-build.sh); " \
      "known sources: ${!SCOPE_MODE[*]}"
  done
  [ -z "$STOCK_SOURCES" ] || _check_stock_sources
  # The host-side Gradle tasks reach Postgres and Solr through localhost:$PG_PORT/$SOLR_PORT. If a
  # port is already published by ANOTHER stack's container, builddb would drop and recreate that
  # stack's database (and postprocess re-index its Solr) - so a port held by anything but this
  # stack's own container is fatal, before any work starts. Read-only (docker ps), so it runs under
  # --dry-run too; a docker daemon that cannot answer is treated as "no conflict".
  local port_svc port svc holder
  for port_svc in "$PG_PORT:postgres" "$SOLR_PORT:solr" "$MINE_PORT:mine" "$BG_PORT:mine"; do   # BlueGenes shares the mine container's network namespace, so the mine publishes its port
    port=${port_svc%%:*}; svc=${port_svc#*:}
    holder=$(docker ps --filter "publish=$port" --format '{{.Names}}' 2>/dev/null | grep -vx "$RDFC2IM_PREFIX-$svc" | head -1 || true)
    [ -z "$holder" ] || die "host port $port (for $svc) is already published by container '$holder', which is not" \
      "this stack's ($RDFC2IM_PREFIX-$svc) - use --stack-name or set the *_PORT variables"
  done
  mkdir -p "$TRIAL_HOME"
  # The data root (default /micklem/data, rdfc2im.yaml's src_data_dir - a real Micklem-lab
  # deployment path; see phase_stage_src_data) lives under a root-owned path on a fresh sandbox.
  # One-time, idempotent: only touches it if not already ours. /micklem itself is handed over too,
  # so the default layout keeps working as it always did.
  if [ ! -w "$DATA_ROOT" ] 2>/dev/null || [ ! -e "$DATA_ROOT" ]; then
    run sudo mkdir -p "$DATA_ROOT"
    run sudo chown "$(id -u):$(id -g)" "$DATA_ROOT"
    case "$DATA_ROOT" in /micklem/*) run sudo chown "$(id -u):$(id -g)" /micklem ;; esac
  fi
  # Gradle 4.9's daemon default heap (1024m) is not enough for InterMine's
  # ParallelBatchingFetcher, which spawns a worker thread per available CPU core, each doing its
  # own DataTracker.prefetchIds() - confirmed live: "OutOfMemoryError: GC overhead limit
  # exceeded" in a worker thread on the very first source's load. The exception is in a
  # background thread, not main, so the daemon doesn't fail cleanly - it spins in a GC
  # death-spiral, burning CPU with no forward progress, rather than exiting. GRADLE_USER_HOME's
  # own gradle.properties (default $HOME/.gradle) applies to every daemon Gradle starts from here,
  # across both the humanmine and humanmine-bio-sources checkouts.
  # file.encoding=UTF-8: the daemon's own default (US-ASCII) comes from this sandbox having no
  # LANG/LC_ALL set at all, which Java's platform-default-charset detection falls back to
  # US-ASCII for. Harmless for plain ASCII data, but confirmed live to actively corrupt real
  # data: reactome's own UniProt2Reactome.txt has non-ASCII bytes (Greek letters in pathway
  # names, normal UTF-8), and BioFileConverter reads files via a platform-default-charset
  # Reader (no explicit UTF-8) - under US-ASCII those bytes get mis-decoded, and one specific
  # mis-decode produced a literal NUL byte, which Postgres's COPY then rejected outright:
  # "invalid byte sequence for encoding UTF8: 0x00".
  local gradle_props="$GRADLE_USER_HOME/gradle.properties"
  if ! grep -q "^org.gradle.jvmargs" "$gradle_props" 2>/dev/null; then
    write_file "$gradle_props" "org.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8"
  fi
  log "prerequisites OK"
}

# --stock-sources, validated against rdfc2im/data/stock_sources.yaml the way --sources is against
# SCOPE_MODE, before any work starts: unknown or repeated names, a source an rdfc2im source of this
# build replaces, a missing `needs`, a not-redistributable source (OMIM) with no local copy under
# --stock-local, and the 6.0-line / human-only limits (D-5). Rewrites STOCK_SOURCES into HumanMine's
# own project.xml order, the order every later phase uses. Read-only, so it runs under --dry-run too.
_check_stock_sources() {
  [ "$IM_LINE" = "6.0" ] || die "--stock-sources needs --intermine-src on the 6.0 line (D-5: the hybrid is" \
    "built on the 6.0.0 stack only; the humanmine-bio-sources fork is on that line)"
  activate_venv
  local out err="$LOG_DIR/build-$RUN_ID.stock-check.err"
  out=$(python3 -m rdfc2im stock check $STOCK_SOURCES --sources "$SOURCES" --taxon "$TAXON" \
        ${STOCK_LOCAL:+--local "$STOCK_LOCAL"} 2>"$err") || die "--stock-sources: $(cat "$err")"
  [ ! -s "$err" ] || log "$(cat "$err")"
  STOCK_SOURCES=$out
  log "stock sources, in HumanMine's project.xml order: $STOCK_SOURCES"
  # The filter tool (task T0.2) is a separate file; a real run cannot do without it.
  if [ ! -f "$HERE/tools/subset_raw.py" ]; then
    [ "$DRY_RUN" -eq 1 ] || die "--stock-sources needs tools/subset_raw.py (the raw-file filter, task T0.2), which this checkout lacks"
    log "note: tools/subset_raw.py is not in this checkout; a real run would stop here"
  fi
  # Raw downloads, plus room to unpack and filter them: twice the download plus 2 GB.
  local need avail probe=$STOCK_DIR
  need=$(python3 -m rdfc2im stock size $STOCK_SOURCES ${STOCK_LOCAL:+--local "$STOCK_LOCAL"}) || die "rdfc2im stock size failed"
  need=$(( need * 2 + (2 << 30) ))
  while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
  avail=$(df -B1 --output=avail "$probe" | tail -1 | tr -dc 0-9)
  if [ "${avail:-0}" -lt "$need" ]; then
    local msg="--stock-sources: $STOCK_DIR (on the filesystem of $probe) has $((avail >> 20)) MB free, $((need >> 20)) MB needed - set RDFC2IM_STOCK_DIR (or RDFC2IM_DATA_ROOT) to a directory on a bigger disk"
    [ "$DRY_RUN" -eq 1 ] && log "note: $msg" || die "$msg"
  fi
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
    run_in "$src/$m" env JAVA_HOME="$jdk" "${GRADLE_HOME_ENV[@]}" LANG=C.UTF-8 LC_ALL=C.UTF-8 ./gradlew -Dorg.gradle.jvmargs=-Xmx4g \
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
      if [ "${SCOPE_MODE[hgnc]}" = full ] && [[ " $SOURCES " == *" hgnc "* ]]; then
        # --gene-identifiers all: hgnc holds every human gene (about 23,500 papers); the PMIDs stay the
        # panel's, read from the panel genes' cut of its items (subset_raw.py panel_items) [im-9n4.40]
        local hgnc_cut="$TRIAL_HOME/hgnc-panel-items.xml"
        run python3 tools/subset_raw.py panel-items --genes "$GENE_PANEL" --in out/hgnc/items/hgnc.xml \
          --out "$hgnc_cut" --lookup-dir "$LOOKUP_DIR" --taxon "$TAXON"
        run bash -c "grep -ahoE '\"[0-9]{4,9}\"' '$hgnc_cut' out/{uniprot,gwascatalog,reactome}/items/*.xml 2>/dev/null \
                      | tr -d '\"' | sort -u > '$pmid_file'"
      else
        run bash -c "grep -ahoE '\"[0-9]{4,9}\"' out/{hgnc,uniprot,gwascatalog,reactome}/items/*.xml 2>/dev/null \
                      | tr -d '\"' | sort -u > '$pmid_file'"
      fi
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
  # --stock-sources: their <source> entries are checked against the table, get their data and
  # organism properties from it, and their integrate-order constraints are checked (plan 50 row 4).
  for s in $STOCK_SOURCES; do src_flags+=(--stock-source "$s"); done
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
  if [ ! -d "$bio" ]; then
    if [ "$IM_LINE" = "6.0" ]; then _copy_bio_sources_60 "$bio"; else run cp -r "$UPSTREAM_CACHE/humanmine-bio-sources" "$bio"; fi
  fi
  # hpo-annotation_additions.xml (humanmine-bio-sources d67fc5d) declares `Disease.dataSets` without the reverse
  # reference BioEntity.dataSets has, and our Disease extends BioEntity (curation/extensions_additions.xml, merged
  # first), so :dbmodel:mergeModels stops with "replacing the BioEntity.dataSets collection with Disease.dataSets
  # failed because the reverse references differ" [im-9n4.15]. Disease inherits dataSets: the line is redundant.
  # Removed in this build's copy only; the fork should drop it too.
  if [ "$IM_LINE" = "6.0" ] && [ -n "$STOCK_SOURCES" ]; then
    case " $STOCK_SOURCES " in *" hpo-annotation "*)
      deployer_edit "$bio/hpo-annotation/src/main/resources/hpo-annotation_additions.xml" \
        "delete Disease.dataSets (BioEntity already has it; the redefinition breaks mergeModels)" \
        -e '/<collection name="dataSets" referenced-type="DataSet"\/>/d' ;;
    esac
  fi
  # The dead JCenter/Bintray plugin in bio-source-humanmine-static fails Gradle's config phase
  # for every sibling project (confirmed live, LOAD-TRIAL.md). Not needed for this source list.
  # (The 6.0 line's fork has no such plugin, and its settings.gradle lists the include on a comma
  # continued line that commenting out would break.)
  if [ "$IM_LINE" != "6.0" ] && grep -q "^[^#]*bio-source-humanmine-static" "$bio/settings.gradle" 2>/dev/null; then
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

# Stock reactome: what phase build_reactome_source was until --stock-sources, unchanged; now the
# first step of phase_build_stock_sources.
_build_reactome_source() {
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
  local dest_dir="$DATA_ROOT/reactome/current"
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

# The rows `rdfc2im stock ROWS...` prints for this build's --stock-sources (tab-separated, '-' for an
# empty field). Dies on a failure rather than handing an empty list to a loop. Read-only.
_stock_rows() {
  local what=$1; shift
  local out
  out=$(python3 -m rdfc2im stock "$what" $STOCK_SOURCES "$@") || die "rdfc2im stock $what failed"
  printf '%s\n' "$out"
}
_stock_files() {
  _stock_rows files --stock-dir "$STOCK_DIR" --raw-cache "$STOCK_RAW_CACHE" ${STOCK_LOCAL:+--local "$STOCK_LOCAL"}
}
_dash() { [ "$1" = - ] && echo "" || echo "$1"; }

# Reactome as before, then the loader jar of every --stock-sources entry (plan 50 row 6), before
# prepare_mine_checkout and builddb: dbmodel:addSourceDependencies resolves org.intermine:bio-source-
# <type> for every source left in project.xml.
#   intermine              publish_intermine already published every bio/sources jar of the
#                          --intermine-src checkout into $IM_M2 at $IM_VERSION; only a missing one is
#                          built, in that checkout's bio/sources.
#   humanmine-bio-sources  built in the humanmine-bio-sources fork copy (maint-2026, 4.3.0) that
#                          build_humanmine_items made, exactly as humanmine-items is.
phase_build_stock_sources() {
  _build_reactome_source
  [ -n "$STOCK_SOURCES" ] || return 0
  activate_venv
  local rows src type origin art ver jar tree="$INTERMINE_TREE"
  if [ "$DRY_RUN" -eq 1 ] && [ ! -d "$tree" ]; then tree="$INTERMINE_SRC"; fi   # as in _build_reactome_source
  rows=$(_stock_rows jars --im-version "$IM_VERSION")
  while IFS=$'\t' read -r -u 3 src type origin art ver; do
    [ -n "$src" ] || continue
    case "$origin" in
      intermine)
        jar="$IM_M2/org/intermine/$art/$ver/$art-$ver.jar"
        if [ -f "$jar" ]; then
          log "$src: $art $ver published by publish_intermine ($jar)"
        elif [ "$DRY_RUN" -eq 1 ]; then
          log "$src: $art $ver from publish_intermine ($jar); built in $tree/bio/sources only if missing"
        else
          log "$src: $jar is missing - building it in the checkout's bio/sources"
          run_in "$tree/bio/sources" env JAVA_HOME="${INTERMINE_JAVA_HOME:-$JAVA8_HOME}" "${GRADLE_HOME_ENV[@]}" \
            LANG=C.UTF-8 LC_ALL=C.UTF-8 ./gradlew --no-daemon "${IM_GRADLE_ARGS[@]}" ":$art:publishToMavenLocal"
          [ -f "$jar" ] || die "$src: $art was built but $jar is still missing"
        fi ;;
      humanmine-bio-sources)
        run_in "$TRIAL_HOME/humanmine-bio-sources" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" ":$art:publishToMavenLocal" ;;
      *) die "$src: unknown jar origin $origin" ;;
    esac
  done 3<<< "$rows"
}

# Upstream Last-Modified of URL $1 as an ISO timestamp, or "unknown". HEAD first; some hosts answer
# HEAD with an error but a one-byte GET properly (purl.obolibrary.org's GitHub release assets: 401).
_last_modified() {
  local url=$1 h lm
  h=$(curl -fsSIL --max-time 60 "$url" 2>/dev/null) || h=$(curl -fsSL --max-time 60 -r 0-0 -D - -o /dev/null "$url" 2>/dev/null) || true
  lm=$(printf '%s' "$h" | tr -d '\r' | sed -n 's/^[Ll]ast-[Mm]odified: *//p' | tail -1)
  if [ -n "$lm" ] && lm=$(date -u -d "$lm" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then echo "$lm"; else echo unknown; fi
}

# Plan 50 row 6 (download half): every upstream file of the --stock-sources, as one raw cache group
# per source, stock-raw-<name>, in $STOCK_RAW_CACHE (under the data root: never cached_raw_data/).
# The loaders later read the files straight out of that group's data/ directory, so a download is on
# disk once. The group's META records each file's url.<id> and last_modified.<id>; a build without
# --use-cached-data asks the server for Last-Modified first and downloads again only when it changed
# (or is unknown). --use-cached-data / --offline never download: the raw group must verify against the
# table's URLs, unless the source's filtered group (subset_stock_data) is cached and it has no file
# that is used whole. Local copies (--stock-local) are read where they are.
phase_fetch_stock_data() {
  [ -n "$STOCK_SOURCES" ] || { log "no --stock-sources: nothing to fetch"; return 0; }
  activate_venv
  local rows src fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb
  _fetch_resolver_data
  rows=$(_stock_files)
  for src in $STOCK_SOURCES; do
    local group="stock-raw-$src" urls=() fids=() raws=() whole=0
    while IFS=$'\t' read -r -u 3 s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb; do
      [ "$s" = "$src" ] || continue
      [ "$origin" = derived ] && continue     # made from another file of the source by subset_stock_data
      [ "$origin" = download ] || { log "$src/$fid: local copy $raw"; continue; }
      urls+=("$url"); fids+=("$fid"); raws+=("$(basename "$raw")")
      [ "$kind" = filtered ] || whole=1
    done 3<<< "$rows"
    [ "${#urls[@]}" -gt 0 ] || continue
    local verify_meta=() i
    for i in "${!urls[@]}"; do verify_meta+=(--meta "url.${fids[$i]}=${urls[$i]}"); done
    if [ "$USE_CACHED_DATA" -eq 1 ]; then
      if [ -f "$STOCK_RAW_CACHE/$group/META.json" ] || [ "$DRY_RUN" -eq 1 ]; then
        run python3 -m rdfc2im cache verify "$group" --cache-dir "$STOCK_RAW_CACHE" "${verify_meta[@]}"
      elif [ "$whole" -eq 0 ] && [ -f "$(_stock_filtered_cache "$src")/stock-$src/META.json" ]; then
        log "$src: no raw download cached; subset_stock_data restores its filtered files instead"
      else
        die "$src: nothing cached in $STOCK_RAW_CACHE/$group - run once without --use-cached-data/--offline"
      fi
      continue
    fi
    local save_meta=("${verify_meta[@]}") known=1 lm
    for i in "${!urls[@]}"; do
      if [ "$DRY_RUN" -eq 1 ]; then
        log "+ curl -fsSIL ${urls[$i]}  (its Last-Modified)"; lm=dry-run
      else
        lm=$(_last_modified "${urls[$i]}")
      fi
      [ "$lm" = unknown ] && known=0
      save_meta+=(--meta "last_modified.${fids[$i]}=$lm")
    done
    if [ "$DRY_RUN" -eq 0 ] && [ "$known" -eq 1 ] && [ -f "$STOCK_RAW_CACHE/$group/META.json" ] &&
       python3 -m rdfc2im cache verify "$group" --cache-dir "$STOCK_RAW_CACHE" "${save_meta[@]}" >/dev/null 2>&1; then
      log "$src: cached download is current (same URLs and Last-Modified) - not fetched again"
      continue
    fi
    local incoming="$STOCK_DIR/incoming/$src"
    run rm -rf "$incoming"
    run mkdir -p "$incoming"
    for i in "${!urls[@]}"; do
      run curl -fsSL --retry 3 --retry-delay 10 -o "$incoming/${raws[$i]}" "${urls[$i]}"
    done
    # shellcheck disable=SC2046  # --meta k=v words without whitespace
    run python3 -m rdfc2im cache save "$group" "$incoming" --cache-dir "$STOCK_RAW_CACHE" "${save_meta[@]}" \
      $(python3 -m rdfc2im stock meta "$src" --record)
    run rm -rf "$incoming"
  done
}

# The ID resolver's gene_info (plan 50 2.2): one raw cache group per taxon, stock-raw-resolver for the --taxon one
# and stock-raw-resolver-<taxon> for the partner organisms the selected sources resolve (`rdfc2im stock resolver`:
# panther's rat and zebrafish, NCBI's per-organism files), beside the stock sources', fetched under the same rules
# (Last-Modified check, --use-cached-data only verifies). Public domain (NCBI), so the groups say
# redistributable=true; they live in the stock cache, not cached_raw_data/.
_fetch_resolver_data() {
  local rows t url
  rows=$(python3 -m rdfc2im stock resolver $STOCK_SOURCES --taxon "$TAXON") || die "rdfc2im stock resolver failed"
  while IFS=$'\t' read -r -u 4 t url _; do
    _fetch_resolver_file "$t" "$url"
  done 4<<< "$rows"
}

_resolver_group() { [ "$1" = "$TAXON" ] && echo "$RESOLVER_GROUP" || echo "$RESOLVER_GROUP-$1"; }

_fetch_resolver_file() {
  local t=$1 url=$2 raw group; raw=$(basename "$url"); group=$(_resolver_group "$t")
  local meta=(--meta "url.gene_info=$url")
  if [ "$USE_CACHED_DATA" -eq 1 ]; then
    if [ -f "$STOCK_RAW_CACHE/$group/META.json" ] || [ "$DRY_RUN" -eq 1 ]; then
      run python3 -m rdfc2im cache verify "$group" --cache-dir "$STOCK_RAW_CACHE" "${meta[@]}"
    else
      die "resolver: nothing cached in $STOCK_RAW_CACHE/$group - run once without --use-cached-data/--offline"
    fi
    return 0
  fi
  local lm
  if [ "$DRY_RUN" -eq 1 ]; then
    log "+ curl -fsSIL $url  (its Last-Modified)"; lm=dry-run
  else
    lm=$(_last_modified "$url")
  fi
  meta+=(--meta "last_modified.gene_info=$lm")
  if [ "$DRY_RUN" -eq 0 ] && [ "$lm" != unknown ] && [ -f "$STOCK_RAW_CACHE/$group/META.json" ] &&
     python3 -m rdfc2im cache verify "$group" --cache-dir "$STOCK_RAW_CACHE" "${meta[@]}" >/dev/null 2>&1; then
    log "resolver: cached gene_info for taxon $t is current (same URL and Last-Modified) - not fetched again"
    return 0
  fi
  local incoming="$STOCK_DIR/incoming/resolver-$t"
  run rm -rf "$incoming"
  run mkdir -p "$incoming"
  run curl -fsSL --retry 3 --retry-delay 10 -o "$incoming/$raw" "$url"
  run python3 -m rdfc2im cache save "$group" "$incoming" --cache-dir "$STOCK_RAW_CACHE" "${meta[@]}" \
    --meta redistributable=true --meta licence=public_domain_NCBI
  run rm -rf "$incoming"
}

# Where a source's filtered cache group lives: cached_raw_data/ (the CI release asset's source) for
# redistributable data, the data root's own cache for the rest (D-7), so restricted data cannot reach
# a release even before T0.3's `cache save --for-release` refusal exists.
_stock_filtered_cache() {
  local m; m=$(python3 -m rdfc2im stock meta "$1" --record) || die "rdfc2im stock meta $1 failed"
  case " $m " in *" --meta redistributable=false "*) echo "$STOCK_RAW_CACHE" ;; *) echo "${STOCK_FILTERED_CACHE:-$RAW_CACHE_DIR}" ;; esac
}

# Writes one file row's output (see `rdfc2im stock files`): a filtered file (tools/subset_raw.py filter),
# or a whole file unpacked from its archive or .gz, or a derived file (the Chromosome lengths read from
# a filtered GFF, tools/subset_raw.py chromosome-lengths). Arguments are the row's fields.
_stock_produce() {
  local src=$1 fid=$2 raw=$3 unpack=$4 member=$5 fmt=$6 ids=$7 col=$8 taxon=$9 keep=${10} work=${11} kind=${12} sname=${13} ktypes=${14:-} xdb=${15:-}
  local in=$raw tmp="$STOCK_DIR/unpacked/$src/$fid"
  run rm -rf "$work"
  run mkdir -p "$work"
  if [ "$kind" = filtered ] && [ "$fmt" = psi-xml ]; then
    # PSI-MI XML reads the zip itself (IntAct human.zip is 1 GB of dozens of members, never unpacked):
    # one filtered file per member, under the member's own name, into the work directory [im-9n4.13]
    local args=(--format psi-xml --in "$raw" --ids "$STOCK_DIR/idsets/$ids.txt")
    [ -z "$xdb" ] || args+=(--xref-db "$xdb")
    if [ -n "$unpack" ]; then args+=(--member "$member" --out "$work"); else args+=(--out "$work/$sname"); fi
    run python3 tools/subset_raw.py filter "${args[@]}"
    return 0
  fi
  if [ "$kind" = derived ]; then
    [ "$fmt" = chromosome-lengths ] || die "$src/$fid: unknown derived format $fmt"
    run python3 tools/subset_raw.py chromosome-lengths --in "$raw" --out "$work/$sname" --taxon "${taxon:-$TAXON}"
    return
  fi
  if [ "$kind" = whole ] && [ -n "$unpack" ] && [ -z "$sname" ]; then
    # several members (a glob), used whole: unpacked flat into the work directory
    case "$unpack" in
      zip) run unzip -o -q -j "$raw" "$member" -d "$work" ;;
      tar.gz) run tar -xzf "$raw" -C "$work" --wildcards --no-anchored --transform='s|.*/||' "$member" ;;
    esac
    return 0
  fi
  local out="$work/$sname"
  [ "$kind" = whole ] || out="$tmp/$(basename "${member:-x}")"
  if [ -n "$unpack" ]; then
    [ "$kind" = whole ] || { run rm -rf "$tmp"; run mkdir -p "$tmp"; }
    case "$unpack" in
      zip) run bash -c "unzip -p '$raw' '$member' > '$out'" ;;
      tar.gz) run bash -c "tar -xzOf '$raw' --wildcards --no-anchored '$member' > '$out'" ;;
    esac
    in=$out
  elif [ "$kind" = whole ]; then
    run bash -c "gzip -dc '$raw' > '$out'"
  fi
  if [ "$kind" = filtered ]; then
    local args=(--format "$fmt" --in "$in" --out "$work/$sname")
    [ -z "$ids" ] || [ "$ids" = none ] || args+=(--ids "$STOCK_DIR/idsets/$ids.txt")
    [ -z "$col" ] || args+=(--column "$col")
    [ -z "$taxon" ] || args+=(--taxon "$taxon")
    [ "${keep:-0}" = 0 ] || args+=(--keep-lines "$keep")   # keep_header: the number of leading lines kept [im-9n4.14]
    [ -z "$ktypes" ] || args+=(--keep-types "$ktypes")
    run python3 tools/subset_raw.py filter "${args[@]}"
    [ -z "$unpack" ] || run rm -rf "$tmp"
  fi
}

# Plan 50's new phase after row 6: the gene panel as id sets (Entrez, Ensembl, UniProt, symbol, from
# the rdfc2im items and the gene-id lookup cache), then every --stock-sources file cut to them
# (tools/subset_raw.py, task T0.2). The filtered files of a source are one cache group, stock-<name>,
# keyed like the panel sources (genes_md5, taxon) plus the table's spec for them (spec_md5); its META
# also records the upstream releases and redistributable/licence. Files used whole are unpacked from
# the raw group on every build and never cached a second time.
phase_subset_stock_data() {
  [ -n "$STOCK_SOURCES" ] || { log "no --stock-sources: nothing to subset"; return 0; }
  activate_venv
  [ "$DRY_RUN" -eq 1 ] || [ -f tools/subset_raw.py ] || die "tools/subset_raw.py (task T0.2) is missing"
  local rows s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb
  rows=$(_stock_files)
  run python3 tools/subset_raw.py idsets --genes "$GENE_PANEL" --out "$STOCK_DIR/idsets" --items-root out \
    --lookup-dir "$LOOKUP_DIR" --taxon "$TAXON"
  # The ID-resolver gate (plan 50 2.2 mechanism 1): the filtered NCBI gene_info as
  # ${resolver.file.rootpath}/entrez, so psi, biogrid, panther, omim and the HumanMine expression
  # loaders drop what the resolver does not know. Under D-1 the mine holds ALL human genes as
  # identifiers (deep annotation only for the panel), so the default keeps every row of the taxon;
  # --resolver-scope panel keeps only the panel's Entrez ids. prepare_mine_checkout sets
  # resolver.file.rootpath. The factory reads plain text, so the output has no .gz suffix.
  # One NCBI file per taxon (the --taxon one first, then the selected sources' `resolver_taxa`: panther's rat and
  # zebrafish), each cut to its taxon and appended to the one `entrez` file the factory reads [im-9n4.11].
  # --resolver-scope panel cuts the --taxon file to the panel's Entrez ids; the partner organisms stay whole.
  run mkdir -p "$RESOLVER_ROOT"
  local rrows rt rurl first=1
  rrows=$(python3 -m rdfc2im stock resolver $STOCK_SOURCES --taxon "$TAXON") || die "rdfc2im stock resolver failed"
  while IFS=$'\t' read -r -u 4 rt rurl _; do
    local rargs=(--format gene_info --in "$STOCK_RAW_CACHE/$(_resolver_group "$rt")/data/$(basename "$rurl")" --taxon "$rt")
    if [ "$first" -eq 1 ]; then
      first=0
      rargs+=(--out "$RESOLVER_ROOT/entrez")
      [ "$RESOLVER_SCOPE" = panel ] && rargs+=(--ids "$STOCK_DIR/idsets/entrez.txt")
      run python3 tools/subset_raw.py filter "${rargs[@]}"
    else
      rargs+=(--out "$STOCK_DIR/unpacked/resolver-$rt.gene_info")
      run python3 tools/subset_raw.py filter "${rargs[@]}"
      run bash -c "cat '$STOCK_DIR/unpacked/resolver-$rt.gene_info' >> '$RESOLVER_ROOT/entrez'"
    fi
  done 4<<< "$rrows"
  local genes_md5; genes_md5=$(md5sum "$GENE_PANEL" | cut -d' ' -f1)
  # panther goes first: mgi-identifiers and rgd-identifiers are cut to the genes on its filtered rows
  # (idsets/mgi.txt, idsets/rgd.txt, `subset_raw.py partner-ids` after the panther step below) [im-9n4.11]
  local src ordered=""
  for src in $STOCK_SOURCES; do [ "$src" = panther ] && ordered="panther $ordered" || ordered="$ordered $src"; done
  for src in $ordered; do
    local cdir group="stock-$src" filtered=0 spec more restore=0
    cdir=$(_stock_filtered_cache "$src")
    spec=$(python3 -m rdfc2im stock meta "$src" --restore) || die "rdfc2im stock meta $src failed"
    more=$(python3 -m rdfc2im stock meta "$src" --record) || die "rdfc2im stock meta $src failed"
    # shellcheck disable=SC2206  # --meta k=v words without whitespace
    local need=(--meta "genes_md5=$genes_md5" --meta "taxon=$TAXON" $spec)
    case "$src" in   # these two are cut to panther's partner genes: a new PANTHER release changes the cut
      mgi-identifiers) need+=(--meta "partners_md5=$(md5sum "$STOCK_DIR/idsets/mgi.txt" 2>/dev/null | cut -d' ' -f1 || true)") ;;
      rgd-identifiers) need+=(--meta "partners_md5=$(md5sum "$STOCK_DIR/idsets/rgd.txt" 2>/dev/null | cut -d' ' -f1 || true)") ;;
    esac
    # --use-cached-data restores the filtered group - unless none matches this panel (a new
    # genes_md5 after a panel change, or a first run) while the raw group is cached: filtering needs
    # no network, so the files are cut from the raw group and saved, as without the option [im-9n4.6]
    if [ "$USE_CACHED_DATA" -eq 1 ]; then
      restore=1
      if awk -F'\t' -v s="$src" '$1 == s && $14 == "filtered" { f = 1 } END { exit !f }' <<< "$rows" &&
         [ -f "$STOCK_RAW_CACHE/stock-raw-$src/META.json" ] && ! { [ -f "$cdir/$group/META.json" ] &&
           python3 -m rdfc2im cache verify "$group" --cache-dir "$cdir" "${need[@]}" >/dev/null 2>&1; }; then
        log "$src: no filtered group for this panel in $cdir; cutting it from the cached raw group"
        restore=0
      fi
    fi
    while IFS=$'\t' read -r -u 3 s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb; do
      [ "$s" = "$src" ] || continue
      case "$kind" in
        filtered) filtered=1
                  [ "$restore" -eq 1 ] && continue ;;
        derived) [ "$restore" -eq 1 ] && continue ;;   # in the filtered group; made after the file it reads
        asis) continue ;;
      esac
      _stock_produce "$src" "$fid" "$raw" "$(_dash "$unpack")" "$(_dash "$member")" "$(_dash "$fmt")" "$(_dash "$ids")" \
        "$(_dash "$col")" "$(_dash "$taxon")" "$keep" "$work" "$kind" "$(_dash "$sname")" "$(_dash "$ktypes")" "$(_dash "$xdb")"
      # phenotype.hpoa is disease-keyed: cut to the diseases of the genes_to_phenotype.txt just filtered (listed
      # before it in the table), as mgi-identifiers is cut to panther's partners [im-9n4.15]
      if [ "$src" = hpo-annotation ] && [ "$fid" = genes-to-phenotype ]; then
        run python3 tools/subset_raw.py disease-ids --in "$work/$sname" --out "$STOCK_DIR/idsets"
      fi
    done 3<<< "$rows"
    [ "$filtered" -eq 1 ] || continue
    if [ "$restore" -eq 1 ]; then
      run python3 -m rdfc2im cache restore "$group" "$STOCK_DIR/subset/$src" --cache-dir "$cdir" "${need[@]}"
    else
      # shellcheck disable=SC2086  # --meta k=v words without whitespace
      run python3 -m rdfc2im cache save "$group" "$STOCK_DIR/subset/$src" --cache-dir "$cdir" "${need[@]}" \
        $more $(_stock_releases "$src")
    fi
    if [ "$src" = panther ]; then
      run python3 tools/subset_raw.py partner-ids --in "$STOCK_DIR/subset/panther/orthologs/RefGenomeOrthologs" \
        --ids "$STOCK_DIR/idsets/uniprot.txt" --out "$STOCK_DIR/idsets"
    fi
  done
}

# `--meta release.<id>=<Last-Modified>` words for a source, from its raw group's META (empty when
# there is none: a dry run, or local copies only).
_stock_releases() {
  local f="$STOCK_RAW_CACHE/stock-raw-$1/META.json"
  [ -f "$f" ] || return 0
  python3 -c 'import json, sys
m = json.load(open(sys.argv[1])).get("meta", {})
print(" ".join("--meta release.%s=%s" % (k.split(".", 1)[1], v) for k, v in sorted(m.items()) if k.startswith("last_modified.")))' "$f"
}

# Writes $2 to file $1, or just logs the intent under --dry-run - a real dry run must not touch
# $HOME or the working tree. `run cmd > file` does NOT achieve this on its own: bash opens a
# bare redirect on the *caller's* command line before `run` is even invoked, so the file gets
# created (or the write attempted) regardless of DRY_RUN - found by dry-running this script, not
# by inspection. Route every generated-file write through this instead of a bare `>`.
write_file() {
  local dest=$1 content=$2
  log "+ write $dest ($(printf '%s' "$content" | wc -l) lines)"
  # RDFC2IM_DRY_RUN_SHOW_WRITES=1: also print what a dry run would write (tests read it)
  [ "$DRY_RUN" -eq 1 ] && [ "${RDFC2IM_DRY_RUN_SHOW_WRITES:-}" = 1 ] && printf '%s\n' "$content"
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
  # BlueGenes shares the mine's network namespace (im-ore.8), so the mine publishes both ports
  mine:     {ports: !override ["$BIND_ADDR:$MINE_PORT:$MINE_PORT", "$BIND_ADDR:$BG_PORT:5000"]}
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

# The 6.0 line's humanmine-bio-sources: the converted maint-2026 branch of the fork (pins 6.0.+, Gradle 8.14.6,
# maven-publish, java-target.gradle), cloned once into the upstream cache and copied (without .git) to $1.
_copy_bio_sources_60() {
  local bio=$1 clone="$UPSTREAM_CACHE/humanmine-bio-sources-6.0"
  if [ ! -d "$clone/.git" ]; then
    log "6.0 line: cloning $HUMANMINE_BIO_60_URL ($HUMANMINE_BIO_60_REF) for the converted bio-sources build files"
    run git clone --depth 1 --quiet --branch "$HUMANMINE_BIO_60_REF" "$HUMANMINE_BIO_60_URL" "$clone"
  fi
  log "6.0 line: bio-sources checkout = $HUMANMINE_BIO_60_REF of $HUMANMINE_BIO_60_URL at $(git -C "$clone" log -1 --format='%h %s' 2>/dev/null | cut -c1-100)"
  run python3 tools/copy_tree.py "$clone" "$bio" --exclude .git
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
  if [ "$IM_LINE" = "6.0" ]; then
    # $bio is already the converted fork (_copy_bio_sources_60): only the humanmine-items subproject,
    # this repository's own Gradle-4.9 build file, still needs compile -> implementation.
    _gradle7_configurations "$items/build.gradle"
    return 0
  fi
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
  # every src.data.* path of project.xml is under /micklem/data (rdfc2im.yaml's src_data_dir and
  # HumanMine's own entries); a per-stack RDFC2IM_DATA_ROOT rewrites them all [im-ore.7]
  [ "$DATA_ROOT" = /micklem/data ] || run sed -i "s|\"/micklem/data/|\"$DATA_ROOT/|g" "$mine/project.xml"
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
  # --stock-sources are kept by name the same way, in HumanMine's order (plan 50 row 7).
  run python3 tools/reduce_mine.py sources "$mine/project.xml" humanmine-items reactome $STOCK_SOURCES
  # Restrict to human only, matching the rest of this build - rdfc2im's own generated project.xml
  # carries this source's original "9606 10090" (human+mouse) value untouched.
  run sed -i 's|<property name="reactome.organisms" value="9606 10090"/>|<property name="reactome.organisms" value="9606"/>|' \
    "$mine/project.xml"
  # HumanMine's own priorities file, merged with our sources (rdfc2im project already did the
  # merge; this just deploys it) - re-syncing after adding a source is required, not optional
  # (confirmed live, LOAD-TRIAL.md's hgnc section, finding 3).
  write_file "$mine/dbmodel/resources/genomic_priorities.properties" "$(cat out/_mine/genomic_priorities.properties)"
  [ -z "$DATA_SET_LINKS" ] || _add_data_set_links "$mine"
  local prod_props
  local tree="$INTERMINE_TREE"
  if [ "$DRY_RUN" -eq 1 ] && [ -n "$INTERMINE_SRC" ] && [ ! -d "$tree" ]; then tree="$INTERMINE_SRC"; fi  # as in build_reactome_source
  prod_props=$(find "$tree" -path "*resources/src/main/resources/default.intermine.production.properties" -not -path "*/build/*" | head -1)
  [ -n "$prod_props" ] || die "default.intermine.production.properties not found under $tree - did make-inputs.sh (or publish_intermine) run?"
  # Must be the one defining integration.production, NOT bio/model's copy (integration.bio-test)
  # - confirmed live, LOAD-TRIAL.md: the wrong one fails with "Failed to instantiate
  # IntegrationWriter class".
  local props
  props="$(cat <<PROPS
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
# should skip this via \`if (props.hasProperty("webapp.hostname")) ... else getServerName(...)\`,
# but that's a Groovy trap: Properties.hasProperty(key) is the Groovy MOP method (does this
# OBJECT have a declared field/property with this name?), not Properties.containsKey(key) - it
# is FALSE for every loaded entry, always, regardless of what's in the file, so the \`else\`
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
  # The ID-resolver gate (plan 50 2.2): with --stock-sources, resolver.file.rootpath is the directory
  # subset_stock_data wrote the filtered entrez gene_info to. EntrezGeneIdResolverFactory also keeps
  # a built resolver in idresolver.cache (written to the working directory of the Gradle run, read
  # back from the classpath) and prefers it to the data file, so any one left by an earlier build -
  # possibly made from a different entrez file - is deleted before integrate.
  if [ -n "$STOCK_SOURCES" ]; then
    props+=$'\n'"resolver.file.rootpath=$RESOLVER_ROOT"
    run find "$mine" -maxdepth 3 -name idresolver.cache -type f -delete
  fi
  write_file "$HOME/.intermine/humanmine.properties" "$props"
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
    local dest_dir="$DATA_ROOT/rdfc2im/$src"
    run mkdir -p "$dest_dir"
    run ln -sf "$HERE/out/$src/items/$src.xml" "$dest_dir/$src.xml"
  done
  [ -z "$STOCK_SOURCES" ] || _stage_stock_data
}

# --stock-sources (plan 50 row 8): link every filtered, unpacked or as-is file into HumanMine's own data
# directory under the data root, by the name its converter expects, so the stock project.xml properties
# work unchanged. Several loaders read every file in their directory (go-annotation, panther, psi) or
# throw on an unexpected one (protein-atlas, orphanet), so each directory is first cleared of links
# into this build's own areas ($STOCK_DIR, the local copies) - links an earlier build left - and a real
# file (a deployment's own HumanMine data under /micklem/data) is never replaced.
_stage_stock_data() {
  activate_venv
  local rows s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb dirs=""
  rows=$(_stock_files)
  while IFS=$'\t' read -r -u 3 s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb; do
    [ -n "$s" ] || continue
    case " $dirs " in *" $sdir "*) ;; *) dirs="$dirs $sdir" ;; esac
  done 3<<< "$rows"
  local d
  for d in $dirs; do
    run mkdir -p "$DATA_ROOT/$d"
    run find "$DATA_ROOT/$d" -maxdepth 1 -type l \( -lname "$STOCK_DIR/*" ${STOCK_LOCAL:+-o -lname "${STOCK_LOCAL%/}/*"} \) -delete
  done
  while IFS=$'\t' read -r -u 3 s fid origin url raw unpack member fmt ids col taxon keep work kind sdir sname ktypes xdb; do
    [ -n "$s" ] || continue
    local dest="$DATA_ROOT/$sdir" from
    if [ "$kind" = asis ]; then from=$raw; else from="$work/$sname"; fi
    if [ "$sname" = - ]; then
      # a member glob: every file unpacked into the work directory
      run bash -c "for f in '$work'/*; do t='$dest'/\$(basename \"\$f\"); if [ -e \"\$t\" ] && [ ! -L \"\$t\" ]; then echo \"refusing to replace the real file \$t\" >&2; exit 1; fi; ln -sfn \"\$f\" \"\$t\"; done"
    else
      run bash -c "if [ -e '$dest/$sname' ] && [ ! -L '$dest/$sname' ]; then echo 'refusing to replace the real file $dest/$sname' >&2; exit 1; fi; ln -sfn '$from' '$dest/$sname'"
    fi
  done 3<<< "$rows"
}

phase_start_databases() {
  # COMPOSE_FILES (and its docker-compose.local.yml, if BIND_ADDR needs one) is computed
  # globally, above - see that block's comment for why (resume-safety: this phase can be
  # skipped by --from without start_mine_stack losing access to it).
  # a bind-mounted volume needs its directory to exist (Docker will not create it)
  [ -z "${RDFC2IM_PGDATA:-}" ] || run mkdir -p "$RDFC2IM_PGDATA"
  [ -z "${RDFC2IM_SOLRDATA:-}" ] || run mkdir -p "$RDFC2IM_SOLRDATA"
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

# The mine checkout is copied once (phase_prepare_mine_checkout) and the reductions of phase_build_dbmodel only
# ever remove: webconfig-model.xml loses the widgets and fields of classes the model lacks, and
# objectstoresummary.config.properties its autocomplete lines. A build with more stock sources than the one
# before it (go-annotation adds GOAnnotation) therefore never got them back: go_enrichment_for_gene stayed
# dropped from the 9n4.9 build, ProteinDomain's autocomplete too [im-9n4.11]. So the two files are put back
# as the upstream checkout has them (the Solr port edit made again) before the reductions run on them.
_restore_unreduced() {
  local mine=$1 clone="$UPSTREAM_CACHE/humanmine" rel
  [ "$IM_LINE" = "6.0" ] && clone="$UPSTREAM_CACHE/humanmine-6.0"
  [ -d "$clone" ] || [ "$DRY_RUN" -eq 1 ] || die "no pristine mine checkout at $clone to restore the web config from"
  for rel in webapp/src/main/webapp/WEB-INF/webconfig-model.xml dbmodel/resources/objectstoresummary.config.properties; do
    run bash -c "cat '$clone/$rel' > '$mine/$rel'"
  done
  run sed -i "s|localhost:[0-9]*/solr/|localhost:$SOLR_PORT/solr/|" "$mine/dbmodel/resources/objectstoresummary.config.properties"
}

phase_build_dbmodel() {
  local mine="$TRIAL_HOME/humanmine"
  _restore_unreduced "$mine"
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
  # pathway_enrichment filters on the NAMES of the pathway data sets: HumanMine's file lists
  # "KEGG pathways data set" and "Reactome data set", but this mine has one pathway data set, the
  # stock reactome source's "Reactome pathways data set" (humanmine-reactome joins it, see
  # sources.yaml), so the Reactome filter matched nothing. im-ore.10.
  deployer_edit "$mine/webapp/src/main/webapp/WEB-INF/webconfig-model.xml" \
    "pathway_enrichment filters: this mine's one pathway data set" \
    -e 's|filters="All,KEGG pathways data set,Reactome data set"|filters="All,Reactome pathways data set"|'
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
  # --stock-sources load in this same project.xml order: HumanMine's own, with the table's `after`
  # constraints (plan 50 row 11) checked by `rdfc2im project`.
  [ -z "$STOCK_SOURCES" ] || log "stock sources load in project.xml order with the rest: $STOCK_SOURCES"
  # One Gradle daemon loads every source, and its 4 GB heap is not given back between them. With
  # --gene-identifiers all (some 600,000 more ncbigene/hgnc items) the old generation was full by the
  # time panther converted: 1,976 full collections, 46 min of GC, no progress. A fresh JVM per
  # source (--no-daemon) costs a few seconds each [im-9n4.40].
  local per_source=()
  [ "$GENE_IDENTIFIERS" = all ] && per_source=(--no-daemon)
  for src in $order; do
    run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" "${per_source[@]}" :dbmodel:integrate -Psource="$src"
  done
}

phase_postprocess() {
  # Order from HumanMine's own project.xml <post-processing> block (LOAD-TRIAL.md). The
  # genomic-location-specific tasks (create-chromosome-locations-and-lengths,
  # transfer-sequences, create-gene-flanking-features, create-location-overlap-index,
  # create-overlap-view, populate-child-features) run only for the --stock-sources that ask for them
  # (ncbi-gff, ncbi-fasta: the stock table's `postprocess`, below); the RDF sources load no
  # coordinates, so without those they would no-op or fail on a missing prerequisite (confirmed
  # live). populate-child-features is not in HumanMine's list. update-data-sources needs a Micklem-lab-specific
  # file path this build does not have; also skipped.
  local mine="$TRIAL_HOME/humanmine"
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=create-references
  # The postprocesses the --stock-sources need (plan 50 row 12; the table's `postprocess`: the
  # genomic-location tasks for ncbi-gff/ncbi-fasta, do-sources for go-annotation's GoPostprocess), in
  # HumanMine's <post-processing> order, which `rdfc2im stock postprocess` prints [im-9n4.6]. All of
  # them sit between create-references and create-attribute-indexes there. do-sources is scoped with
  # -Psource to the stock sources that asked for it, as it is to reactome below.
  if [ -n "$STOCK_SOURCES" ]; then
    activate_venv
    local pp p wanted
    pp=$(_stock_rows postprocess)
    while IFS=$'\t' read -r -u 3 p wanted; do
      [ -n "$p" ] || continue
      log "stock postprocess $p (for $wanted)"
      if [ "$p" = do-sources ]; then
        run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=do-sources -Psource="$wanted"
      else
        run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess="$p"
      fi
    done 3<<< "$pp"
  fi
  run_in "$mine" "${GRADLE_ENV[@]}" ./gradlew "${IM_GRADLE_ARGS[@]}" :dbmodel:postProcess -Pprocess=create-attribute-indexes
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
  # PostProcessPlugin prints "POSTPROCESS <task> FAILED." and still exits 0, so a failed
  # create-autocomplete-index (ProteinDomain.shortName, im-9n4.19) passed the phase with an empty core: check it
  if [ "$DRY_RUN" -eq 0 ]; then
    local n
    n=$(curl -sf "http://localhost:$SOLR_PORT/solr/humanmine-autocomplete/select?q=*:*&rows=0&wt=json" |
        python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["numFound"])') || n=0
    [ "${n:-0}" -gt 0 ] || die "create-autocomplete-index left the humanmine-autocomplete core empty (look for 'POSTPROCESS create-autocomplete-index FAILED' in the log)"
    log "autocomplete core: $n documents"
  fi
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
  run env TRIAL_HOME="$TRIAL_HOME" PG_PORT="$PG_PORT" SOLR_PORT="$SOLR_PORT" \
      ${ARTIFACTS_DIR:+RDFC2IM_ARTIFACTS="$ARTIFACTS_DIR"} sh tools/trial-stage.sh
  # The patched BlueGenes tool set (BUILD.md, "The patched BlueGenes tool set"): only with --jbrowse2-src
  # (or env JBROWSE2_SRC), the one input that is not in cached_raw_data/.
  if [ -n "$JBROWSE2_SRC" ]; then
    local art=${ARTIFACTS_DIR:-$HERE/trial/artifacts}
    run tools/stage-bluegenes-tools.sh --jbrowse2-src "$JBROWSE2_SRC" --src-cache "$RAW_CACHE_DIR/bluegenes-tools/data" \
      --out "$art/bluegenes-tools-patched" --install-to "$art/bluegenes-tools"
  fi
}

phase_start_mine_stack() {
  run "${COMPOSE_ENV[@]}" $COMPOSE "${COMPOSE_FILES[@]}" up -d mine bluegenes
  # The webapp reads the database once, at startup - postprocessing and the war it's serving
  # must both be in place before this, and it must run again after either changes.
  run docker restart "$MINE_CONTAINER" "$BG_CONTAINER"
  # --with-front: the aligner and the nginx front on the BlueGenes origin (trial/front/README.md)
  [ "$WITH_FRONT" -eq 0 ] || run trial/front/up.sh
}

phase_apply_templates() {
  if [ "$SKIP_TEMPLATES" -eq 1 ]; then
    log "skipped (--skip-templates)"
  elif [ ! -f curation/demo_public_templates.sql ]; then
    log "no curation/demo_public_templates.sql - skipping"
  else
    run bash -c "docker exec -i $PG_CONTAINER psql -U intermine -d humanmine-userprofile < curation/demo_public_templates.sql"
    run docker restart "$MINE_CONTAINER" "$BG_CONTAINER"
  fi
  [ -z "$REPORT_LAYOUT" ] || apply_report_layout
}

# --report-layout: through the web service, so after the restart above. Templates first, as the layout drops
# an entry whose template the mine does not serve.
apply_report_layout() {
  [ -f "$REPORT_LAYOUT" ] || die "--report-layout: no such file: $REPORT_LAYOUT"
  local mine="http://localhost:$MINE_PORT/humanmine" bg=${TOOLS_URL:-"http://localhost:$BG_PORT"}
  run python3 tools/apply_humanmine_templates.py "$(dirname "$REPORT_LAYOUT")/humanmine_templates.xml" --mine "$mine" --wait 300
  run python3 tools/apply_report_layout.py "$REPORT_LAYOUT" --mine "$mine" --bluegenes "$bg" --wait 300
}

# --public-lists: through the web service, after the template phase's restart. The tool archives the mine's current public
# lists first and stops before any upload if that fails.
phase_apply_public_lists() {
  if [ -z "$PUBLIC_LISTS" ]; then
    log "no --public-lists: the Genomics England lists and HumanMine's other public lists are not applied"
    return 0
  fi
  [ -d "$PUBLIC_LISTS" ] || die "--public-lists: no such directory: $PUBLIC_LISTS"
  [ -d "$PUBLIC_LISTS_ARCHIVE" ] || die "--public-lists-archive: no such directory: $PUBLIC_LISTS_ARCHIVE"
  local mine="http://localhost:$MINE_PORT/humanmine" names=--keep-2021-names
  [ "$PUBLIC_LISTS_NAMES" = current ] && names=--current-names
  run python3 tools/apply_public_lists.py --mine "$mine" --panelapp-cache "$PUBLIC_LISTS" --legacy curation/public_lists \
      --archive-repo "$PUBLIC_LISTS_ARCHIVE" --select "$PUBLIC_LISTS_SELECT" "$names" \
      --report "$LOG_DIR/public-lists-$RUN_ID.json" --wait 300
}

# --data-set-links URL [im-9n4.42]: an items file of DataSet records (name, url = the source's status page,
# description) for every data set the selected sources write, loaded by one more humanmine-items source after all
# the others, first for DataSet.url and DataSet.description (no loader sets either in this build).
_add_data_set_links() {
  local mine=$1 items="$DATA_ROOT/rdfc2im/_data-set-links/data_set_links.xml"
  run mkdir -p "$(dirname "$items")"
  run python3 tools/source_pages.py data-set-links --base-url "$DATA_SET_LINKS" --sources "$SOURCES" \
      --stock-sources "$STOCK_SOURCES" --out "$items"
  run python3 tools/source_pages.py add-links-source --project "$mine/project.xml" \
      --priorities "$mine/dbmodel/resources/genomic_priorities.properties" --items "$items" --name data-set-links
}

# --source-pages DIR [im-9n4.42]: the build manifest and the data-source status pages, from the caches, the logs and
# the running mine (read-only queries). Field counts are cached under $RDFC2IM_STOCK_DIR/field-counts by sha256.
phase_write_source_manifest() {
  activate_venv   # source_manifest.py reads the YAML tables
  local mine="http://localhost:$MINE_PORT/humanmine" man="out/_mine/source_manifest.json"
  run python3 tools/source_manifest.py --out "$man" --sources "$SOURCES" --stock-sources "$STOCK_SOURCES" \
      --cache-dir "$RAW_CACHE_DIR" --stock-dir "$STOCK_DIR" ${STOCK_FILTERED_CACHE:+--filtered-cache "$STOCK_FILTERED_CACHE"} \
      --logs "$LOG_DIR" --mine "$mine" --gene-identifiers "$GENE_IDENTIFIERS" --build-name "${STACK_NAME:-default} $(basename "$LOG_DIR")" \
      ${INTERMINE_SRC:+--intermine-src "$INTERMINE_SRC"} --trial-home "$TRIAL_HOME" \
      --reference-datasets curation/humanmine_2022_datasets.json
  run python3 tools/source_pages.py pages --manifest "$man" --out "$SOURCE_PAGES"
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
