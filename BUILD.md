# Building the demonstration mine

`tools/full-build.sh` takes this repository from nothing to a running, fully-configured
demonstration HumanMine: RDF Portal SPARQL extraction, Items XML generation, the InterMine
database build and load, postprocessing, the Solr search index, the webapp, BlueGenes, and the
demo templates. One command, 20 phases, no manual steps in between.

This file is the operator's guide to running it on an ordinary Linux machine with Docker. The
script's own header comment (`sed -n '1,65p' tools/full-build.sh`, or `tools/full-build.sh
--help`) is the authoritative reference for its options and environment variables; this file
covers what you have to provide, what to expect, and what to do when it goes wrong.

It was written from the record of many hand-run sessions (`LOAD-TRIAL.md`) and first run for
real on 2026-09-21, which surfaced and fixed about thirty genuine bugs. It was then run again
from scratch in a different sandbox the same day - new checkout state, new Docker volumes, a
new `TRIAL_HOME`, a workspace still holding derived files from earlier sessions - which found
ten more (see "A second, from-scratch run" below). Everything here is from those runs, not
from reading the script.

## What you get

A 114-gene food/drug-metabolism demonstration HumanMine (113 genes plus PAX6):

- **Nine rdfc2im-generated sources** - `go`, `ncbigene`, `reactome`, `hgnc`, `ensembl`,
  `uniprot`, `clinvar`, `gwascatalog`, `pubmed` - all loaded through the stock
  `intermine-items-large-xml-file` loader, with no per-source Java.
- **Plus the stock `reactome` source loaded alongside.** rdfc2im's own reactome mapping covers
  `Pathway.description` but not pathway participants (the `pathwayComponent` link is
  unmapped/pruned), so without the stock source a `Pathway` never connects to any `Protein` or
  `Gene`. The script builds `org.intermine:bio-source-reactome` from upstream source (its
  published jar is dead on JCenter) and runs `ReactomePostProcess`, which is what fills
  `Gene.pathways` from `Protein.pathways`.
- **Four containers**: the InterMine webapp at `http://localhost:8090/humanmine`, BlueGenes at
  `http://localhost:5000`, PostgreSQL on `15432`, Solr on `8983`. All four publish to
  `127.0.0.1` only, so they are reachable from the machine that built them and nowhere else.

Scope is controlled by `--sources`, `--genes` and `--taxon`; the defaults are the demo panel
described above.

## Prerequisites

The script checks all of these in `phase_check_prereqs` and dies with a usable message if one is
missing - but it installs none of them. Get these in place first.

### JDK 8 (required, and it must be 8)

InterMine's mine build uses Gradle 4.9, which **cannot start a daemon under a newer JDK**. This
is not a warning you can work around; it fails immediately.

```sh
sudo apt-get install -y openjdk-8-jdk-headless          # 8u502 is what the first real build used
```

The script auto-detects `/usr/lib/jvm/java-8-openjdk-*` or `/usr/lib/jvm/java-1.8.0*`. If yours
lives elsewhere, set `JAVA8_HOME` to it. A newer JDK may remain your system default: the script
passes `JAVA_HOME=$JAVA8_HOME` to every Gradle invocation itself.

### Python venv at the repo root

```sh
sudo apt-get install -y python3-venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt               # pyyaml, lxml
```

The path is not configurable: `phase_rdfc2im_pipeline` looks for `<repo>/.venv/bin/activate` and
dies with *"no .venv at ... - create one with pyyaml+lxml first"* if it is absent.

### A standalone Gradle 4.9 launcher

```sh
curl -fsSLO https://services.gradle.org/distributions/gradle-4.9-bin.zip
unzip -q gradle-4.9-bin.zip -d ~/opt && export PATH="$HOME/opt/gradle-4.9/bin:$PATH"
```

This is needed by `phase_resolve_bluegenes_deps` and `phase_build_stock_sources` (its reactome step), which build
throwaway Gradle projects that have no wrapper of their own. Put it on `PATH` as `gradle`, or
point `GRADLE49` at the launcher. The humanmine and humanmine-bio-sources checkouts use their
own `./gradlew` wrapper and are unaffected by this.

### Docker and Docker Compose

Docker 29.7.2 with Compose v5.5.0 were used for the first real build. Compose v2 syntax is
required (the script calls `docker compose`, overridable with `COMPOSE=`). Your user must be
able to run `docker` without `sudo`.

### Everything else

`git`, `curl`, `unzip`, and `sudo` - the last only for a one-time, idempotent bootstrap of the
data root, `/micklem/data` by default (where `rdfc2im.yaml`'s `src_data_dir` points: a real
Micklem-lab deployment path). The script creates it and chowns it to you if it does not already
exist or is not writable. `RDFC2IM_DATA_ROOT` moves it (see "Running two stacks").

### Network

The build reaches out to `rdfportal.org`, `grch38.togovar.org` (GWAS Catalog),
`www.humanmine.org`, `reactome.org`, `github.com`, `repo.clojars.org`, `services.gradle.org`,
`repo.maven.apache.org`, and Docker Hub.

### What the script sets up for you

You do not need to do any of this by hand:

- JDK 8 discovery and the `JAVA_HOME` override on every Gradle call.
- Gradle's user home, passed explicitly to every Gradle call: `GRADLE_USER_HOME` (default
  `$HOME/.gradle`) and `JAVA_TOOL_OPTIONS=-Duser.home=$HOME`. JDK 8 takes `user.home` from the
  passwd entry and ignores `$HOME`, so with a private `HOME` (a second stack, a task sandbox) Gradle
  used and wrote the real account's `~/.gradle` and `~/.intermine`, silently bypassing the private
  one; `fb-env*.sh`-style wrappers worked around it by exporting `JAVA_TOOL_OPTIONS` themselves.
  The script no longer depends on that. (Your own `gradle --stop` is not covered: give it the same
  two variables.)
- The `/micklem` bootstrap, and symlinking each source's items file into
  `/micklem/data/rdfc2im/<source>/`.
- `$GRADLE_USER_HOME/gradle.properties` (`~/.gradle/gradle.properties` by default), written (if it has no `org.gradle.jvmargs` line) as:

  ```
  org.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8
  ```

  Both halves matter. The heap: Gradle 4.9's 1 GB daemon default is not enough for InterMine's
  `ParallelBatchingFetcher`, which runs a prefetch thread per CPU core; it dies with
  `OutOfMemoryError: GC overhead limit exceeded` **in a background thread**, so the daemon does
  not fail cleanly - it spins in a GC death-spiral, burning CPU with no forward progress. The
  encoding: with no `LANG`/`LC_ALL` set, Java's platform default charset falls back to US-ASCII,
  and `BioFileConverter` reads data files through a platform-default-charset reader. Reactome's
  own `UniProt2Reactome.txt` contains ordinary UTF-8 (Greek letters in pathway names); under
  US-ASCII one of those mis-decodes to a literal NUL byte, and Postgres rejects the `COPY` with
  `invalid byte sequence for encoding UTF8: 0x00`. This is data corruption, not cosmetics.
- Source-list validation: a name not in the script's `SCOPE_MODE` table is a fatal error before
  any work starts, rather than silently becoming an unscoped full-database fetch hours later.
- All the upstream workarounds the first real build needed - the dead JCenter/Bintray plugins,
  the relative-path Ant bug in InterMine's own `DBModelPlugin`, the war built with no
  `WEB-INF/web.xml`, the missing userprofile schema, the reduced-mine trims of
  `genomic_priorities.properties`, `objectstoresummary.config.properties` and
  `webconfig-model.xml`.

## Running it

Always start with a dry run. It prints the exact command sequence without executing anything -
`run`/`run_in`/`write_file` are the only things in the script that touch the outside world, and
under `--dry-run` all three are no-op printers, so there is no separate code path that could
drift from what really executes.

```sh
tools/full-build.sh --dry-run
tools/full-build.sh
```

Useful options:

| Option | Effect |
|---|---|
| `--dry-run` | Print every command instead of running it |
| `--list-phases` | Print the 20 phase names (21 with `--intermine-src`), in order, and exit |
| `--from PHASE` | Resume: start at `PHASE` instead of the beginning |
| `--only PHASE` | Run exactly one phase and stop |
| `--sources "a b c"` | Override the nine-source demo panel |
| `--genes FILE` | Gene panel for the panel-scoped sources (default `curation/demo_gene_panel.txt`) |
| `--taxon LIST` | NCBI taxon ids (default `9606`) |
| `--skip-templates` | Do not apply `curation/demo_public_templates.sql` |
| `--use-cached-data` | Restore the fetched raw data from `cached_raw_data/` instead of fetching it again. The upstream clones are not part of that cache: missing ones are cloned (needs network, e.g. a fresh CI runner), present ones are left as they are (see below) |
| `--offline` | `--use-cached-data` plus a guarantee that the data phases make no network request at all; a missing upstream clone is an error. Implies `--use-cached-data`; also on when the caller exports `RDFC2IM_OFFLINE=1` (see below) |
| `--cache-dir DIR` | Use `DIR` instead of `cached_raw_data/` |
| `--reactome-levels default\|all` | Which of Reactome's own two files to load (see below); default `default` |
| `--intermine-src DIR` | Build against the InterMine checkout `DIR` instead of the published 5.0.x artefacts (see "Building against a local InterMine checkout") |
| `--stack-name NAME` | Run a second stack beside the default one: own container/volume names, Compose project and ports (see "A second stack") |
| `--stock-sources "a b"` | Also load these stock HumanMine/InterMine sources (the hybrid testbed; see "Stock sources"). Default empty: the build is exactly as without the option |
| `--stock-local DIR` | Local copies of stock data, `DIR/<source>/<file>`; the only way in for data that is not redistributable (OMIM) |

`--from` and `--only` always run `check_prereqs` first regardless, because that phase is what
sets the `JAVA_HOME` override the Gradle calls need.

Key environment variables (see the script header for the rest): `TRIAL_HOME` (scratch tree for
the upstream checkouts and Gradle output, default `~/intermine-build/trial_home`),
`UPSTREAM_CACHE` (default `in/.upstream`), `JAVA8_HOME`, `GRADLE49`, `COMPOSE`, `PG_PORT`,
`BG_PORT`, `SOLR_PORT`, `MINE_PORT`, `RDFC2IM_PREFIX`, `COMPOSE_PROJECT_NAME`, `MINE_TITLE`,
`INTERMINE_JAVA_HOME`, `RDFC2IM_STOCK_DIR`, `RDFC2IM_STOCK_LOCAL`.

`--from build_reactome_source` and `--only build_reactome_source` still work: that phase is now
`build_stock_sources`, which builds stock reactome exactly as before and then the `--stock-sources`
jars.

### Reactome pathway levels

The stock reactome source (phases 6/13/14 - see "What you get") reads one of Reactome's own two
published UniProt-to-pathway files:

- **`default`** (`UniProt2Reactome.txt`) - a protein is listed only against the specific, lowest-
  level pathway it participates in. A broad pathway like "Metabolism" gets no direct protein or
  gene participants of its own unless something happens to be annotated at that exact level - most
  of the demo panel's own pathway hits are on much more specific pathways (e.g. "Aspirin ADME"),
  which is why this is the default.
- **`all`** (`UniProt2Reactome_All_Levels.txt`, via `--reactome-levels all`) - every ancestor
  pathway also carries its descendants' proteins and genes, matching how a pathway's "Proteins"
  tab looks on reactome.org itself. The file is larger, `Gene.pathways` and `Pathway.proteins` fan
  out a lot more (a top-level pathway can have thousands of participants), and Reactome
  postprocessing and search indexing take longer.

Only one of the two files is ever present under `$RDFC2IM_DATA_ROOT/reactome/current/` (`/micklem/data/reactome/current/` by default) at a time - the
stock converter processes every file it finds there, so both together would double-count. Switching
`--reactome-levels` between runs removes the other one first. The cache
(`cached_raw_data/reactome-uniprot-map/`) records which level was fetched and refuses to restore it
for a build that asked for the other one.

### Building against a local InterMine checkout

`--intermine-src DIR` makes the build use the InterMine checkout `DIR` (for example a worktree of
the 2026 maintenance branch) instead of the published `org.intermine` 5.0.x artefacts: the Gradle
plugin, the `intermine-*` and `bio-*` jars, the bio sources and the webapp wars. RDF Portal data,
the humanmine project files and BlueGenes are the same as without it. This is the whole-system
acceptance test for back-end changes: "the modernised InterMine builds the demo mine".

```sh
tools/full-build.sh --use-cached-data --intermine-src ~/git/intermine --stack-name ut
MINE_BASE=http://localhost:18090/humanmine SOLR_BASE=http://localhost:18983 make test-live
```

What changes:

- **A new phase, `publish_intermine`**, right after `fetch_inputs` (it appears in `--list-phases`
  only with the option). `DIR` is only read: it is copied, without `.git` and build output, to
  `$TRIAL_HOME/intermine-src`, where the checkout's own `config/lib/install_intermine.py` writes
  the `gradle.properties` files and `publishToMavenLocal` runs in each module of its install list
  (plugin, intermine, bio, bio/sources, bio/postprocess) into the private Maven repo
  `$TRIAL_HOME/m2-intermine`. About 4-6 minutes with a warm Gradle cache.
- **Every later Gradle call gets `-Dmaven.repo.local=$TRIAL_HOME/m2-intermine`.** `mavenLocal()`
  is first in the humanmine repositories, so `org.intermine:*` resolves from that repo and never
  from a shared `~/.m2`; the mine's repository list is not edited.
- **Versions come from `DIR`**: the InterMine version from `gradle/libs.versions.toml`, the Gradle
  version (and its checksum) from `config/lib/install_intermine.py`.
- **The copied humanmine and humanmine-bio-sources checkouts move to that version and Gradle**,
  through the deployer edits of `DIR`'s `docs/UPGRADING-build.md`. Each edit is applied only when
  it changes the file and is logged as `deployer edit: <file>: <what>`, so
  `grep 'deployer edit' .build-logs/build-<run>.log` lists what a mine's maintainer has to do by
  hand. With a Gradle 7.6.6 checkout they are:
  - both: `imVersion`/`bioVersion` set to the checkout's version; the checkout's wrapper
    (`gradlew`, `gradle-wrapper.jar`, `distributionUrl`, `distributionSha256Sum`);
    `compile`/`testCompile` to `implementation`/`testImplementation`;
  - humanmine `build.gradle`: delete `inputs.sourceFiles.stopExecutionIfEmpty()`,
    `apply plugin: 'maven'` and `jcenter()`;
  - humanmine `webapp/build.gradle`: `JavaExec` `main =` to `mainClass =`; `duplicatesStrategy =
    DuplicatesStrategy.EXCLUDE` in `warWebApp` (Gradle 7 fails on the duplicate jars that 4.9
    silently packed twice);
  - humanmine-bio-sources `build.gradle`: `apply plugin: 'maven'` to `maven-publish` with one
    publication per subproject (so `install` becomes `publishToMavenLocal`), `classifier =` to
    `archiveClassifier =`. The humanmine-items subproject is built from a copy under
    `TRIAL_HOME` so that this repository's `humanmine-items/build.gradle` is not edited.
- **The bio-sources build must move to the new Gradle too.** A plugin built by Gradle 7.6.6 does
  not load in Gradle 4.9 (`NoClassDefFoundError: groovy/ant/AntBuilder`: Groovy 3 moved the
  class), whatever `UPGRADING-build.md` says about 5.1.1 still running on 4.9.
- The standalone reactome source build and its dependencies use the checkout's version, and
  `default.intermine.production.properties` and `bio/sources/reactome` are read from the copy.
- `INTERMINE_JAVA_HOME` selects the JDK for building the checkout (default `JAVA8_HOME`).

**Which line is built** is read from the checkout: the Gradle its own wrappers use
(`DEFAULT_GRADLE_VERSION` in `config/lib/install_intermine.py`). 7.x and older (the 5.1.1 line,
Gradle 6.9.4/7.6.6) get the deployer edits above. 8.x is the **6.0 line** (maint-2026), where:

- the mine checkout is not upstream `intermine/humanmine` master patched with `sed` but the
  `maint-2026` branch of `gmicklem/humanmine` (`HUMANMINE_60_URL`, `HUMANMINE_60_REF`; cloned once
  into `in/.upstream/humanmine-6.0`, copied without `.git`). That branch is master plus exactly the
  `docs/UPGRADING-build.md` "5.1.1 to 6.0.0" conversion of the root, `dbmodel` and `webapp`
  `build.gradle`, `gradle.properties` and the Gradle 8.14.6 wrapper (the plugin composes the war:
  no `copyWebappContent`/`warWebApp`/`explodedWebAppDir`, no Gretty; the plugin resolves the
  relative SO term paths). Only the
  version pins and the wrapper are then re-applied from the checkout. A pre-existing
  `$TRIAL_HOME/humanmine` that still has the old war composition stops the phase with a message;
- the `web.xml`/absolute-SO-path patches and the `copyWebappContent` pre-run of `build_webapp` are not
  applied (the plugin's war task does not need them);
- `build_stock_sources` (reactome) takes the caching antlr jar from `bio/sources/reactome/libs` (5.x
  trees) or `intermine/libs/antlr-2.7.6-caching.jar` (maint-2026, since im-jqz.6), and stops with
  a message naming both paths if neither exists.

First run (2026-11-15, maint-2026 at 58d3b6cb44, InterMine 5.1.1, Gradle 7.6.6 in the mine, warm
Gradle cache, `--use-cached-data`): 638 s end to end, the same row counts as the 5.0.8 build
(113 genes, 13,546 proteins, 2,883 pathways, 50,283 pathway-protein rows, 450 gene-pathway rows,
6,781 publications, 331,497 objects), web service version 35 (34 with 5.0.8), and `make
test-live` 17/17. The war holds only 5.1.1 `intermine-*`/`bio-*` jars.

6.0-line run (2026-11-16, maint-2026 at 6dbc1417ff, mine = `gmicklem/humanmine` `maint-2026` at
58fbf8f, Gradle 8.14.6, `--use-cached-data`, fresh `TRIAL_HOME`): all 18 phases passed in 599 s
(`publish_intermine` 202 s, `integrate_sources` 150 s, `postprocess` 82 s, `build_dbmodel` 43 s,
`build_webapp` 10 s), `make test-live` 17/17, `template.do` returns 200 with a full page and the
mine's log has no `JasperException`.

Panel of 114 genes (2026-11-18, im-9n4.5, decision D-4): PAX6 (NCBI 5080), the fixture gene of
`[mines.humanmine.gene]` in mine-tests, was added to `curation/demo_gene_panel.txt`; no other
mine-tests or BlueGenes Cypress fixture is a human gene outside the panel. New `genes_md5`
`17702eff6e8f3e08801a2d9877bc2aa1` (was `68ac89b6b78ea87e72dc7323f02ee490`). The panel-scoped
sources (`ncbigene hgnc ensembl uniprot clinvar gwascatalog`, `pubmed` through its cited-PMID list
`pmids_md5` `5d346e5be740dceeaf8ab924bcd8f299`) and `gene-id-lookup` were fetched afresh into a new cache directory,
`cached_raw_data.panel-2026-11-18/` (`go`, `reactome` and the other unscoped groups copied unchanged):
`--only rdfc2im_pipeline --sources "ncbigene hgnc ensembl uniprot clinvar gwascatalog pubmed"
--cache-dir ...`, 1,968 s (clinvar 21 min, gwascatalog 2 min, no endpoint errors), after which
`tools/full-build.sh --use-cached-data --intermine-src ... --stack-name ut` took 547 s on 6.0.0
(`publish_intermine` 197 s, `integrate_sources` 136 s, `postprocess` 79 s, `rdfc2im_pipeline` 57 s,
`build_dbmodel` 27 s, `build_webapp` 14 s). `make test-live` 20/20, no expectation changed.

| Class | 113 genes | 114 genes |
|---|---|---|
| Gene | 113 | 114 |
| Protein | 13,546 | 13,591 |
| Pathway | 2,883 | 2,883 |
| Publication | 6,781 | 6,896 |
| Allele | 53,105 | 59,031 |
| GWASResult | 23,201 | 30,832 |
| Gene-pathway rows | 450 | 455 |
| Pathway-protein rows | 50,283 | 50,283 |
| OntologyTerm | 79,874 | 79,904 |
| all objects (`intermineobject`) | 331,474 | 346,735 |

PAX6 in the mine: 46 proteins, 996 alleles, 5 pathways; Ensembl id ENSG00000007372. The release
tarball for CI is `cached_raw_data-2026-11-18.tar.gz` (the groups of the `demo-data-2026-11-16`
asset, from the new directory); it is not uploaded until the asset is approved.

#### When the InterMine catalog moves to 6.0.0

Everything that says "5.1.1" is a *value read from the checkout*, not a constant of the script.
`IM_VERSION` is `intermine = "..."` in the checkout's `gradle/libs.versions.toml` (older trees:
`intermine/build.gradle`), and `_pin_intermine_version` rewrites `systemProp.imVersion` and
`systemProp.bioVersion` in the copied mine and bio-sources `gradle.properties` to it. That is why
the log reads "InterMine 5.1.1, 6.0 line": the version is still 5.1.1, while the *line*, chosen by
the checkout's Gradle being 8.x, is 6.0. When the maintenance branch's catalog says `6.0.0`:

- **`tools/full-build.sh` needs no edit.** The artefacts are published and resolved at
  `IM_VERSION` (`publish_intermine`, `-Dmaven.repo.local=$TRIAL_HOME/m2-intermine`), and the
  version in `plugin/build.gradle` must equal the catalog's or the script exits 2 ("plugin version
  ... differs from the catalog's"). The `5.0.8`/`5.0.+` fallbacks in `_install_reactome_jar` apply
  only without `--intermine-src`.
- **The `gmicklem/humanmine` fork's `gradle.properties` says 5.1.1** (`systemProp.imVersion` and
  `systemProp.bioVersion`). The build overwrites both in its copy, so it works unchanged; bump
  them in the fork to `6.0.0` anyway, so that a build of the fork outside this script, and a diff
  against what the script writes, agree. The same goes for `humanmine-bio-sources`, pinned by the
  same function. `systemProp.blueGenesVersion` is independent.
- If the fork gets a release branch or tag for 6.0.0, point `HUMANMINE_60_REF` at it (default
  `maint-2026`). An existing `in/.upstream/humanmine-6.0` is never pulled: delete it to pick up a
  new ref.
- `IM_LINE` stays `6.0` (decided by Gradle 8.x, not by the number). Redo and re-record the figures
  above that name 5.1.1: web service version 35 and the "war holds only 5.1.1 jars" check (the war's
  `WEB-INF/lib` and `$TRIAL_HOME/m2-intermine` carry the version in the file names).

#### A first run without network: `HUMANMINE_60_URL`

On the 6.0 line the mine's converted build files come from a clone of the fork in
`$UPSTREAM_CACHE/humanmine-6.0` (default `in/.upstream/humanmine-6.0`). `_copy_mine_60` clones
`$HUMANMINE_60_URL` at `$HUMANMINE_60_REF` only when that directory has no `.git`; an existing
clone is used as it is, with no fetch or pull, and the log line `6.0 line: mine checkout = ...`
names its commit. On a machine that cannot reach GitHub, either:

```sh
# 1. point the URL at a clone you already have (a plain path works; git warns that --depth is
#    ignored for local clones). REF must be a local branch or tag of that clone: `git clone
#    --branch` does not see origin/* remote-tracking branches
HUMANMINE_60_URL=/path/to/humanmine HUMANMINE_60_REF=maint-2026 \
  tools/full-build.sh --use-cached-data --intermine-src ~/git/intermine

# 2. or put the clone where the script looks; nothing is cloned and nothing needs the network
git clone --branch maint-2026 /path/to/humanmine in/.upstream/humanmine-6.0
```

`--offline` does not cover this step by itself: it stops `make-inputs.sh` cloning, but a missing
`in/.upstream/humanmine-6.0` is still cloned from `HUMANMINE_60_URL`, so supply one of the above
first. Checked 2026-11-16: `git clone --depth 1 --branch maint-2026 <path of an existing clone>`
works and yields `58fbf8f`, the commit of the 6.0-line run above.

### Stock sources (`--stock-sources`, the hybrid testbed)

`--stock-sources "uniprot go-annotation ..."` loads stock InterMine and HumanMine sources beside the
rdfc2im ones, with their own converters, from upstream files cut down to the gene panel (planning
repo `plans/50-hybrid-humanmine-testbed.md`, decisions D-1 to D-10). The default is an empty list,
and then every phase below is a no-op and the build is exactly the one without the option.

The sources, and everything the build needs to know about each, are one table:
`rdfc2im/data/stock_sources.yaml` (`python3 -m rdfc2im stock list`). Per HumanMine project.xml
source name: its `type`; where its loader jar comes from (`intermine`: the `--intermine-src`
checkout, published by `publish_intermine`; `humanmine-bio-sources`: the fork's `maint-2026`
branch, version 4.3.0); HumanMine's own data directory under `/micklem/data`; the upstream files
with the name the converter expects and how each is filtered; the licence and a
`redistributable` flag; integrate-order constraints (`after`), other stock sources it `needs`, and
the postprocesses it wants. The file's header documents every key; bash reads it only through
`python3 -m rdfc2im stock check|jars|files|postprocess|size|meta`.

Limits: the 6.0 line only (`--intermine-src` with Gradle 8, D-5; check_prereqs refuses anything
else), human only (`--taxon 9606`), and `tools/subset_raw.py` (the raw-file filter) must be in the
checkout for a real run.

What each phase does with the list:

| Phase | With `--stock-sources` |
|---|---|
| `check_prereqs` | Validates the list against the table, as `--sources` is validated against `SCOPE_MODE`: unknown or repeated names, a source an rdfc2im source of this build replaces (stock `hgnc` with rdfc2im `hgnc`), a missing `needs` (mgi-identifiers needs panther), a `redistributable: false` source with no local copy under `--stock-local`, the 6.0-line and human-only limits, and the free space where `RDFC2IM_STOCK_DIR` lives (twice the downloads plus 2 GB). Puts the list into HumanMine's project.xml order, which every later phase uses |
| `rdfc2im_project` | `rdfc2im project --stock-source NAME...`: each named `<source>` must still be in project.xml (not replaced) with the table's type and the version attribute its jar origin needs; its data property and organism properties are rewritten from the table; its `after` constraints are checked against the final order. Fields an `alongside` rdfc2im source also writes list the stock source first in `genomic_priorities.properties` (risk 3) |
| `build_stock_sources` | Reactome as before, then each jar: an `intermine` one is checked in the private m2 repo (`publish_intermine` already published every `bio/sources` jar; a missing one is built there), a `humanmine-bio-sources` one is built in the fork copy with `publishToMavenLocal`, like humanmine-items |
| `fetch_stock_data` | Downloads each source's files into the cache group `stock-raw-<name>` in `$RDFC2IM_STOCK_DIR/cache` (default `$RDFC2IM_DATA_ROOT/_stock/cache`, never `cached_raw_data/`), keyed to each file's URL and `Last-Modified`; an unchanged upstream file is not fetched again. The loaders read the files where they lie in the cache, so each is on disk once. `--use-cached-data`/`--offline` only verify the cached group |
| `subset_stock_data` | `tools/subset_raw.py idsets` turns the panel into Entrez, Ensembl, UniProt and symbol id sets (from the rdfc2im items and the gene-id lookup); `subset_raw.py filter` cuts each filtered file to them. A source's filtered files are the cache group `stock-<name>`, keyed to `genes_md5`, `taxon` and the table's filter spec (`spec_md5`), and also recording each file's upstream `Last-Modified`, `redistributable` and `licence`. It goes to `cached_raw_data/` for redistributable data and to the stock cache otherwise. Files used whole are unpacked from the raw group on every build and are not cached twice |
| `prepare_mine_checkout` | `reduce_mine.py sources ... humanmine-items reactome <stock names>` keeps their entries, in project.xml order. A name project.xml lacks stops the build |
| `stage_src_data` | Links each file into HumanMine's own data directory under the data root by the name its converter expects (`go-annotation/current/human/gene_association.goa_human`, `uniprot/current/9606_uniprot_sprot.xml`, ...). Each directory is first cleared of links this build made earlier (several loaders read every file in their directory, and some throw on an unexpected one). A real file there is never replaced |
| `integrate_sources` | The stock sources load in project.xml order with the rest, except that a source the table marks `load_first` (uniprot) is moved by `rdfc2im project` ahead of every rdfc2im source (see the first stock build below) |
| `postprocess` | Runs the postprocesses the table asks for (`rdfc2im stock postprocess`), in HumanMine's `<post-processing>` order, between `create-references` and `create-attribute-indexes` (where HumanMine has all of them); `do-sources` is scoped with `-Psource` to the stock sources that want it [im-9n4.6]. The three UniProt sources want none |

`subset_stock_data` under `--use-cached-data` restores each source's filtered group; when no group matches the
panel (a new `genes_md5` after a panel change, or the first build after `fetch_stock_data`) and the raw group is
cached, it cuts the files from the raw group and saves the group instead, since that needs no network [im-9n4.6].
`RDFC2IM_STOCK_FILTERED_CACHE` keeps the filtered groups of redistributable sources out of the raw-data cache
(default: the raw-data cache, as before). The ID-resolver gate and the release refusal of T0.3 are described next.

#### The first stock build: uniprot, uniprot-keywords, uniprot-fasta [im-9n4.6]

`--stock-sources "uniprot uniprot-fasta uniprot-keywords"` on the ut stack (6.0.0), 114-gene panel
(`genes_md5` `17702eff...`), `RDFC2IM_STOCK_DIR` and `RDFC2IM_STOCK_FILTERED_CACHE` under `repos/.sandbox-disk/`.

* Downloads (once; `fetch_stock_data` without `--use-cached-data`, 53 s from the EBI mirror): Swiss-Prot human XML
  174,683,391 B, `keywlist.xml.gz` 155,546 B, varsplic FASTA 8,586,697 B, `Homo_sapiens.gene_info.gz` 5,204,903 B.
* `subset_stock_data` (6 s, 2 s when cached): 20,429 Swiss-Prot entries in, 114 out (the 1,501 panel accessions
  include TrEMBL; only the Swiss-Prot ones are in this file, D-6); varsplic 41,374 records in, 140 out; the resolver
  `entrez` keeps 194,025 of 194,098 rows (all human genes).
* Extra time against the same build without stock sources: `integrate_sources` 158 s (was 136 s; uniprot 13 s,
  uniprot-keywords 6 s, uniprot-fasta 2 s), `postprocess` 82 s (79 s); nothing else measurable. Whole driver run from
  `rdfc2im_project` about 5 min, plus `publish_intermine` 202 s when it runs.
* Disk: `stock_ut/` 240 MB (raw cache 180 MB, filtered groups 13 MB, resolver `entrez` 35 MB); Postgres 2.0 GB.

| | RDF only (114 genes) | with the three stock sources |
|---|---|---|
| Protein | 13,591 | 13,723 |
| Swiss-Prot canonical (`isUniprotCanonical`) | - | 114 |
| isoforms (`canonicalProtein` set) | - | 140 (0 dangling) |
| with `sequence` | 0 | 254 (every canonical and isoform) |
| with features / comments | - | 114 (8,105 UniProtFeature) / 254 |
| with keywords | - | 1,654 |
| Gene | 114 | 114 |
| duplicate Protein.primaryAccession / Gene.primaryIdentifier / Gene.symbol (9606) | 0 / 0 / 0 | 0 / 0 / 0 |
| DataSet | 9 | 12 (`Swiss-Prot data set`, `UniProt data set`, `uniprot-fasta`) |
| all objects | 346,735 | 366,232 |

Two merge bugs showed up on the first run, both fixed in `rdfc2im project`:

1. **CrossReference key.** No stock keys file declares one, so the generated keys fell back to `identifier` alone.
   An rdfc2im cross-reference (an InterPro id cited by several proteins) then matched one stock object per protein
   and `humanmine-uniprot` stopped with "Duplicate objects from the same data source". It is now keyed on
   `subject, identifier` (`project.KEY_DEFAULTS`).
2. **Load order.** Stock uniprot keys Protein on `md5checksum, organism` only, so after `humanmine-hgnc` (Protein by
   `primaryAccession`) it made a second Protein per accession; `humanmine-uniprot` matched both, merged them and
   deleted one, leaving 77 of 140 isoforms with a `canonicalProtein` pointing at nothing. The table's
   `load_first: true` puts stock uniprot before the rdfc2im sources.

Canonical proteins have no `canonicalProtein`, as on HumanMine (P10635 there has none; P10635-2 points at it).
The rdfc2im uniprot proteins (TrEMBL included, D-6) carry no sequence, so a gene's TrEMBL proteins have none:
CYP2D6 has 59 proteins (2 Swiss-Prot, 57 TrEMBL), PAX6 47 (2 and 45). The MSA viewer queries every protein of
the gene and stops at the first without a sequence ("No protein found for UniProtKB accession ...").

The ID resolver: none of these three converters asks for the Entrez resolver (UniprotConverter only creates a
FlyBase one, for taxon 7227, which logs "Creating id resolver from database and caching id resolver to file:
idresolver.cache" and writes nothing without fly data), so the gate's "Creating id resolver for [9606] ... from data
file" line does not appear yet; the first loaders that will show it are psi, biogrid and panther. No
`idresolver.cache` was written anywhere.

#### Locations and gene models: ncbi-gff [im-9n4.9]

`--stock-sources "uniprot uniprot-fasta uniprot-keywords ncbi-gff"` on the ut stack, same panel and cache.
It gives the panel genes their GRCh38 coordinates, RefSeq transcripts and exons, and the chromosomes their
lengths, which is what the JBrowse endpoints need (planning repo plan 50, 1.4).

* **Download** (once): `GRCh38_latest_genomic.gff.gz`, 77,807,126 B, 12 s from NCBI (RefSeq release of
  27 Aug 2024; raw group `stock-raw-ncbi-gff`, 75 MB).
* **Filter** (`subset_raw.py filter --format gff3`, 40 s, peak 0.44 GB; it was 1.2 GB before the parent
  links were kept as strings): 4,903,918 feature rows in, 15,087 out; every `##sequence-region` line, and
  each panel gene (Dbxref `GeneID`) with its descendants (mRNA and other transcripts, exons, CDS) and
  ancestors. 113 of the 114 panel genes have a gene row on a primary chromosome; GSTT1 (2952) is
  annotated only on the alternate locus NT_187633.1, because the primary GRCh38 chr22 carries the deletion
  allele, so it gets no location (HumanMine has none for it either). The filtered group `stock-ncbi-gff`
  is 4.7 MB.
* **Chromosome lengths.** No InterMine loader sets `Chromosome.length` from a GFF: the GFF3 parser skips
  directives, `gff_config.properties` excludes the 9606 `region` rows, and
  `create-chromosome-locations-and-lengths` sets only feature `chromosomeLocation`/`chromosome` and the
  feature's own `length` (`CreateChromosomeLocationsProcess`, despite its name); only the genome FASTA
  (`FastaLoaderTask`) sets it. So `subset_raw.py chromosome-lengths` reads the filtered file's
  `##sequence-region` lines into a small Items XML (Organism 9606, DataSource NCBI, DataSet `ncbi-gff`,
  24 Chromosomes with `length`), cached in the same group, and `rdfc2im project` adds a source
  `ncbi-gff-lengths` (type `humanmine-items`, right after `ncbi-gff`, the table's `chromosome_lengths`)
  that loads it. All 24 lengths equal HumanMine's own `refSeqs.json` (`cached_raw_data/grch38-chromosome-lengths`,
  used as a reference value only). That cache group is read by no code and is no longer needed for the
  lengths: it can leave the release list.
* **Merging (plan 50 risk 3).** `ncbi-gff_keys.properties` keys Gene on `primaryIdentifier` (the converter
  sets it from Dbxref `GeneID`, the Entrez id, as the rdfc2im sources do) and Chromosome on
  `primaryIdentifier, organism`; `NcbiGffGFF3SeqHandler` names NC_000001.11 to NC_000024.10 `1`..`22`,
  `X`, `Y`, the names the rdfc2im items use. Loaded last (HumanMine's project.xml order, after
  humanmine-ncbigene, which satisfies the table's `after: [ncbi-gene]`) it merges into the existing
  objects, so it needs no `load_first`. MT (NC_012920.1) is not in the converter's map: an MT gene would
  be stored without a location (the panel has none) and no MT Chromosome exists; rows on NT_/NW_
  scaffolds are dropped by the record handler. Result: one Gene per Entrez id, no duplicate symbol, one
  Chromosome per name (24: chromosomes 14 and Y are new, from the lengths), no dangling
  `Location.feature`, `Gene.chromosome` or `Transcript.gene`.
* **Priorities** (found by reading the comparator, fixed before the first run): entries `rdfc2im project`
  generated for fields only rdfc2im sources wrote (`Chromosome.primaryIdentifier = humanmine-ensembl,
  humanmine-ncbigene`, `Gene.chromosome`, ...) had no `*`, and `SourcePriorityComparator` refuses a source
  missing from such an entry even when the values are equal. With stock sources every generated entry
  now ends in `*`, and the table's `priority_first` ranks ncbi-gff first for `Gene.chromosome`
  (`Gene.chromosome = ncbi-gff, humanmine-ensembl, humanmine-ncbigene, *`). Symbols stay ranked as
  HumanMine has them (ncbi-gene's slot first, ncbi-gff under `*`).
* **The ID resolver.** ncbi-gff does not use it (no `Creating id resolver for [9606]` line); the gate is
  still unexercised, as with the UniProt sources.
* **Neighbour genes (D-1, plan 50 2.2 b).** `keep_types: [gene]` in the filter keeps every other gene row
  too (63,069 rows), so a genome browser shows the panel gene's neighbours as HumanMine's does. Measured on
  this stack: Gene 42,069, Location 897,539, GeneFlankingRegion 841,300 (create-gene-flanking-features
  makes 20 per gene, as on HumanMine), 2,183,886 objects, Postgres 4.3 GB, ncbi-gff integrate 32 s,
  postprocess 353 s (flanking 55 s, the two search-index passes 81 s and 138 s), and two duplicate symbols
  (RefSeq names five tRNA genes TRNAA-AGC). That doubles the build, so the table leaves it off; the
  thin genome is better served by the RDF side first (`ncbigene=full`), which would also give those genes
  their official symbols.

| | three UniProt sources | with ncbi-gff |
|---|---|---|
| Gene / with `chromosomeLocation` | 114 / 0 | 114 / 113 (all but GSTT1) |
| Chromosome / with `length` | 22 / 0 | 24 / 24 |
| Location | 0 | 16,547 |
| Transcript (all) / MRNA | 0 / 0 | 674 / 604 |
| Exon / CDS | 0 / 0 | 7,466 / 604 |
| GeneFlankingRegion | 0 | 2,260 |
| PAX6 transcripts / exons | - | 53 / 638 (HumanMine: 53 / 637) |
| CYP2D6 transcripts / exons | - | 2 / 17 (HumanMine: 2 / 17) |
| duplicate Gene.primaryIdentifier / Gene.symbol (9606) / Chromosome name | 0 / 0 / - | 0 / 0 / 0 |
| all objects | 366,232 | 395,183 |

Timings of the driver run from `rdfc2im_pipeline` (10 min in all): `subset_stock_data` 41 s (was 6 s),
`integrate_sources` 172 s (was 158 s: ncbi-gff 11 s, ncbi-gff-lengths 5 s), `postprocess` 93 s (was 82 s;
the four location postprocesses 8 s). Disk: Postgres 2.1 GB, `stock_ut/` 615 MB.

JBrowse: `/service/jbrowse/config/9606/seq/refSeqs.json` answers 200 with the 24 chromosomes and their
lengths (it was 404 "No Chromosomes on 9606"); `/service/jbrowse/9606/refSeqs.json` (plan 50's path) is
not an endpoint and stays 404. `/service/jbrowse/9606/features/11?start=31789026&end=31817961&type=Gene`
returns PAX6. Every feature has `subfeatures: []`: the endpoint builds them from `childFeatures`, which
only `populate-child-features` fills, and HumanMine's project.xml has that postprocess commented out
(HumanMine answers the same). The BlueGenes JBrowse 2 panel opens an iframe on the BlueGenes origin,
`/jbrowse2/?assembly=<project.title>-9606&loc=11:31786132..31820855` (served by `trial/front`, see
"JBrowse 2 on the front" below).

What the gene models lack: the converter has no CDS or UTR handling. It stores one CDS object per
protein (604), each with the first segment as `chromosomeLocation` and the other segments as further
Locations, but no `CDS.transcript` (its `refsAndCollections` names only Exon, Transcript and MRNA) and no
protein; it makes no UTRs at all (the RefSeq GFF has no UTR rows; they are exon minus CDS), so
`Transcript.UTRs` and `Transcript.CDSs` are empty and a JBrowse gene glyph cannot tell coding from
untranslated exons. A converter change would map `CDS -> transcript` in `NcbiGffGFF3RecordHandler`, keep
one CDS per transcript with its segments, derive `FivePrimeUTR`/`ThreePrimeUTR` per mRNA from the exon and
CDS spans (strand-aware), and add `NC_012920.1 -> MT` to the chromosome map.

`--with-genome-sequence` adds stock `ncbi-fasta` (it `needs` ncbi-gff) and its postprocess
`transfer-sequences`. The FASTA is cut to the 24 mapped chromosomes (`ids: chromosomes`,
`idsets/chromosomes.txt`): `NCBIFastaLoaderTask` names a record by the words after "chromosome" in its
header, so the file's alt, patch and unlocalized scaffolds would become hundreds of Chromosome objects
named like "1 unlocalized genomic scaffold". Dry-run tested only, never run here; its cost would be a
973 MB download, about 3.1 GB for the filtered file and as much again for its cache group, about 3.1 GB
of `Chromosome.sequence` in Postgres plus the transferred feature sequences, and a filter pass over 3 GB
(minutes). Its lengths equal the GFF's, so the two loaders agree.

#### GO annotation: go-annotation and interpro-go [im-9n4.11]

`--stock-sources "uniprot uniprot-fasta uniprot-keywords ncbi-gff go-annotation interpro-go"` on the ut stack, same
panel. `go_enrichment_for_gene` and the `GOAnnotation` model are what it restores.

* **Downloads** (once): `goa_human.gaf.gz` 15,041,996 B, `interpro2go` 3,057,468 B.
* **Filter.** `subset_raw.py filter --format gaf` on the panel's UniProt ids (1,547 ids, TrEMBL included):
  906,445 rows in, **9,121 out**, **114 accessions matched**. GOA human holds no row for any panel TrEMBL
  accession, so "annotate TrEMBL too" has nothing to add: the 114 Swiss-Prot canonicals carry every annotation, and
  HumanMine's go-annotation annotates `Protein.primaryAccession` too (`9606.typeAnnotated=protein`). interpro2go is
  loaded whole (`filter: none`, 3 MB): 5,556 GO terms for 14,776 ProteinDomain stubs (`primaryIdentifier` only;
  they merge with any later `interpro` data).
* **Result.** GOAnnotation 40,516 (7,019 on Protein, 29,922 on ProteinDomain, 3,575 on Gene via GoPostprocess), GOEvidence
  7,139, all 114 panel genes annotated; objects 458,469 (was 395,183). Integrate about 2 min, postprocess 105 s.
  CYP2D6 33 and PAX6 57 distinct GO terms on the Gene: that is what the GAF holds (33 and 57 distinct `GO:` columns for
  P10635 and P26367); HumanMine's 79 for PAX6 comes from an older GOA release.
* **Merging.** GOTerm (keyed on `identifier`) 78,100, every one also in the RDF `go` source's data set: no duplicates
  and no new terms from the GAF or interpro2go. Protein stays 13,723: the loader creates a stub Protein for each
  UniProt `with` value, but every one matches an existing accession, so no Protein lacks an organism and none is
  duplicated. 29,760 of the RDF terms are not GO terms at all (identifiers `Reactome:...`, `RHEA:...`, `EC:...`)
  and have no name; that is the RDF side's, not this source's (gone since im-9n4.41: the RDF go source keeps only the
  cross references the stock OBO loader keeps, 48,348 GOTerms).
* **Widget.** `go_enrichment_for_gene` was missing although `GOAnnotation` was now in the model: the mine checkout is copied
  once and `reduce_mine.py webconfig` only removes, so the widget dropped in the earlier GOA-less builds never came back
  (the same for the ProteinDomain autocomplete lines of `objectstoresummary.config.properties`). `build_dbmodel` now puts
  both files back from the upstream checkout (the Solr port edit made again) before reducing them
  (`_restore_unreduced`). An enrichment request on six panel genes (`/service/list/enrichment`,
  `widget=go_enrichment_for_gene`, `filter=biological_process`) returns terpenoid metabolic process (p 2.9e-4) and
  demethylation.
* **Priorities.** interpro-go declares `ProteinDomain` but not `ProteinDomain.shortName` (interpro's), and HumanMine's
  `ProteinDomain.shortName = interpro, uniprot, *` made `IntegrationWriter` fail for every source ("ProteinDomain does not
  have a field shortName"). `reduce_mine.py priorities` now drops lines whose field the model lacks as well as those of absent
  classes.
* **The ID resolver.** go-annotation is the first loader to use it (`IdResolverService.getIdResolverForMOD`, taxa
  7227 7955 10090 10116 4932 6239 9606), though it needs it only for gene-annotated organisms and human is
  protein-annotated. The integrate log has `EntrezGeneIdResolverFactory - Creating id resolver for [10090, 9606, 7955,
  4932, 10116] and gene from data file and writing to: .../stock_ut/resolver/entrez` (6239 is in the factory's
  `taxon.ignored`), then `No records in gene_info file for species: [10090, 559292, 7955, 10116]` (the file holds human
  only; yeast is looked up as strain 559292) and `Writing id resolver to file: idresolver.cache`. The cache lands in the
  **mine's root directory** (`$TRIAL_HOME/humanmine/idresolver.cache`, the Gradle JVM's working directory); the integrate
  task itself prints `deleting idresolver cache` at its start, so a stale one cannot survive a run, and
  `prepare_mine_checkout`'s delete finds it too. The same run warns `Resolver file does not exist: .../resolver/wormid`
  (WormBase resolver, not used for human).

#### Homologues: panther and mgi-identifiers [im-9n4.12]

`--stock-sources "... go-annotation interpro-go panther mgi-identifiers"` on the ut stack, same panel.

* **Downloads** (once): `RefGenomeOrthologs.tar.gz` 5.9 MB (PANTHER 19), `MRK_List2.rpt` 78.8 MB (MGI, 16 Nov 2026), and
  NCBI's `Rattus_norvegicus.gene_info.gz` (2.6 MB) and `Danio_rerio.gene_info.gz` (2.2 MB) for the resolver.
* **Filter.** A PANTHER row is `HUMAN|HGNC=8620|UniProtKB=P26367<TAB>MOUSE|MGI=MGI=97490|UniProtKB=P63015<TAB>LDO<TAB>Euarchontoglires<TAB>PTHR45636`.
  The tab filter keeps a row when either of columns 1 and 2 holds a panel UniProt accession (`ids: uniprot`, `column: "1,2"`).
  `subset_raw.py`'s cell matcher knew `db:id` only; it now also strips `db=` (`UniProtKB=P26367`, `MGI=MGI=97490`), with tests.
  908,678 rows in, **2,289 out**, 113 of the 114 panel genes matched (HNMT, P50135, has no PANTHER row).
* **Partner genes and symbols.** PantherConverter creates every partner gene from its id alone (`MGI:97490`, `RGD:3258`,
  `FBgn...`, `ZDB-GENE-...`, `WBGene...`): no symbol. In HumanMine only mouse and rat get one, from `mgi-identifiers`
  (MRK_List2.rpt) and `rgd-identifiers` (GENES_RAT.txt); fly, worm, zebrafish and yeast partners have a primary identifier
  only there too. Both identifier loaders read every marker of their genome, so they are cut to the partner genes:
  `subset_raw.py partner-ids` writes `idsets/mgi.txt` (182 ids) and `idsets/rgd.txt` (170) from the filtered PANTHER file
  (panther is therefore cut first, `needs: [panther]` on both), and MRK_List2.rpt is filtered on column 1 to those ids
  (656,902 markers in, 182 out). The cache group of each also records the md5 of its id set.
  **rgd-identifiers [im-9n4.35]** was first left out because `download.rgd.mcw.edu` was behind the sandbox firewall; it
  is now loaded. `GENES_RAT.txt` is 50,659,314 B (RGD, `Last-Modified` 14 Nov 2026; 103 `#` header lines, then the column-name
  line, then about 45,000 rows). The loader makes `Gene` `RGD:<column 1>` with symbol, name, description, and Ensembl and NCBI
  cross-references; PantherConverter's rat genes are `RGD:<n>` too (the existing ones are `RGD:3258` and so on), and
  `Gene.key_primaryidentifier` is the key of both, so the rows merge and no Java change was needed. The cut keeps 168 of the
  170 partner ids (two are not in the file), 455 KB. `rgd-identifiers` precedes `panther` in HumanMine's project.xml; the
  order does not matter for the key. Licence: the file and the download host carry no licence text, and `rgd.mcw.edu` (the
  site) was not reachable from the sandbox, so the table keeps HumanMine's wording (data free to use with citation) as
  unverified and `redistributable: true`; confirm it on the RGD site before the filtered group goes in a release asset.
  A build that adds a source needs the download phase to fetch it: with `--use-cached-data` a missing group is a FATAL in
  `fetch_stock_data` (not fetched), so run that phase once without `--use-cached-data` and `--offline`
  (`DRIVE_DOWNLOAD=1 drive-ut-NAME.sh fetch_stock_data fetch_stock_data`; it also re-fetched BioGRID, whose server dates
  the file at the request, and the NCBI resolver and PSI-MI files), then resume from `subset_stock_data`.
* **Result.** Homologue 3,166 (2,568 orthologue, 598 least diverged), Gene 1,111 (human 114, worm 257, fly 216, mouse 182,
  rat 165, zebrafish 152, yeast 25), all objects 465,814 (was 458,469). PAX6 has 12 homologues (HumanMine 10: mouse,
  rat, 3 fish, 5 fly, 2 worm), CYP2D6 67. 0 duplicate `Gene.primaryIdentifier`, 0 duplicate symbol within a taxon, no Gene
  without an organism. Only the 114 human and 182 mouse genes have a symbol. Integrate 297 s (was about 2 min), postprocess 101 s.
* **With rgd-identifiers** (im-9n4.35, full rebuild 12:04 UTC, 11:34 to 12:04): rat genes 169 (was 165), 168 with a symbol (was 0).
  The four extra are RGD ids on PANTHER rows that PantherConverter drops when the resolver cannot map them (`RGD:61894`,
  `RGD:15004611`, `RGD:15005179`, `RGD:150344934`): the loader makes them from the file, they have no homologue link. The one rat
  gene with no symbol is `RGD:1306542`, absent from the current file. PAX6's rat homologue is `Pax6` (`RGD:3258`); CYP2D6's five
  are `Cyp2d1` to `Cyp2d5` (`RGD:708427`, `2471`, `2472`, `620640`, `628630`). Gene 65,471 (was 65,467), objects 1,120,890 (was
  1,120,120); 0 duplicate `primaryIdentifier`, 0 duplicate symbol within a taxon, over all 65,471 genes. `make test-live` 60/60.
* **No human partners outside the panel**: the file has no paralogue rows, so every human Gene is a panel gene.
* **The ID resolver, now with a real consumer.** PantherConverter resolves only human (HGNC id to Entrez id, the primary
  identifier), rat and zebrafish genes; mouse, fly, worm and yeast ids are never looked up and pass through. When the
  resolver holds no file for rat or fish the id passes through too (`no resolver available` is logged). With only the
  human file that is what happened; now `resolver_taxa: [10116, 7955]` makes the build fetch one NCBI file per
  taxon (cache group `stock-raw-resolver-<taxon>`, `rdfc2im stock resolver`), cut each to its taxon and append it to
  `resolver/entrez` (HumanMine's own is one multi-species `gene_info`). The log shows `Gene ... does not have xref
  pattern: ZFIN` for the fish genes without a ZFIN id and `RESOLVER: failed to resolve gene to one identifier, ignoring
  gene` 16 times (Ensembl-only or ZFIN-less fish ids and one rat id): the converter drops those. Mouse, fly and yeast
  files are not fetched: nothing here resolves them (go-annotation's `getIdResolverForMOD` asks for them but annotates human
  proteins only; it logs `No records in gene_info file for species: [10090, 559292]`).
* **Layout.** Homology now keeps `homologues`; HumanMine's `Gene_Orth2` is not one of its public templates, so the
  category holds the class table only.

#### Interactions: psi-mi-ontology, psi-intact and biogrid [im-9n4.13]

`--stock-sources "... panther mgi-identifiers psi-mi-ontology psi-intact biogrid"` on the ut stack, same panel. It
restores `Gene.interactions`, the Cytoscape tool and the templates `Gene_Interactions_forReportPage` and
`Gene_Interact_disease`.

* **Downloads** (once): IntAct `human.zip` 1,061,726,001 B (release 24 Oct 2026; 344 members, 20 GB unpacked, 7 min from
  the EBI mirror), BioGRID `BIOGRID-ORGANISM-LATEST.psi25.zip` 208,061,555 B (5.0.263; the human member is 5.8 GB;
  51 s), `mi.obo` 744,253 B. BioGRID's server dates the file at the request (`Last-Modified` is always now), so a run
  without `--use-cached-data` fetches it again.
* **Why a filter.** Both loaders were `filter: none`, relying on the resolver gate; with the all-human resolver (D-1)
  that cuts nothing from a human file, so the whole human interactome would have loaded. `subset_raw.py filter
  --format psi-xml` keeps every interaction with at least one participant whose interactor has a panel id in an xref
  of the table's `xref_db` (IntAct: `uniprotkb` against `idsets/uniprot.txt`, isoform and chain accessions on their
  base; BioGRID: `entrez gene/locuslink` against `idsets/entrez.txt`), with exactly the interactors and experiments
  those reference. Both files are compact PSI-MI 2.5 (lists per `<entry>`, `<interactorRef>` in the participants),
  which is what both converters read; the expanded form is refused. It reads the zip itself, two streaming passes per
  member, and writes one file per member under the member's own name (BioGridConverter reads the organism from the
  file name at `substring(17)`, so the BioGRID file keeps `BIOGRID-ORGANISM-Homo_sapiens-5.0.263.psi25.xml`). Nothing
  is unpacked to disk.
* **Three rules the real files needed.**
  1. *Ensembl versions.* PsiConverter resolves a human interactor through its `ensembl` xrefs
     (`psi-intact_config.properties`: `9606.datasource = ensembl`) against `gene_info`, whose Ensembl ids have no
     version; IntAct now writes `ENSG00000007372.27`. Without a fix no human interactor resolves. The filter drops
     the version (94,341 ids). The ENSP and ENST ids still fail to resolve, harmlessly (about 83,000 `RESOLVER:
     failed` log lines); 897 ENSG ids are unknown to `gene_info` and 12 resolve to two genes.
  2. *Negative interactions.* 40 members are `human_NN_negative.xml` (`<negative>true</negative>`: shown not to
     interact). Neither converter reads the flag, so they would load as interactions; 923 are dropped. (HumanMine
     loads the whole directory, so its 2022 load may include them.)
  3. *n-ary records.* Both converters turn a record into every pair of its participants except prey-prey. A
     583-member complex with one panel gene would load 56,814 pairs, 204 with the panel gene. An interaction with
     more than two participants keeps the panel participants and those the converter pairs with them (1,792 records
     trimmed, 180,007 participants dropped). Counted on the filtered files, the pairs go from 470,310 to 57,418 and all
     22,900 pairs with a panel gene stay; most of the rest come from one 176-member complex whose members all pair
     with each other. The cost: `allInteractors` on such a detail lists the kept participants, not the whole complex.
* **Filter numbers** (`subset_stock_data` 263 s, was 41 s):

  | | IntAct | BioGRID |
  |---|---|---|
  | interactions in / kept | 549,887 / 6,922 | 1,441,421 / 12,019 |
  | interactors in / kept | 551,770 / 10,828 | 49,856 / 5,684 |
  | experiments in / kept | 43,161 / 1,382 | 71,029 / 2,202 |
  | panel ids matched | 137 accessions (of 1,547) | 114 Entrez ids (of 114) |
  | files | 344 in, 288 written, 318 MB | 1, 62 MB |
  | time, peak RSS | 221 s, 87 MB | 34 s, 33 MB |

* **Merging.** Nothing failed on the first integrate. Read from the keys files before the run and checked after it:
  `Interaction` is keyed on `participant1, participant2` by both loaders, so IntAct and BioGRID details hang off one
  Interaction per ordered gene pair (each direction is its own Interaction, as on HumanMine); `Publication` on
  `pubMedId` by both and by the RDF pubmed source; `InteractionTerm` on `identifier` through the inherited
  `OntologyTerm.key_identifier` (BioGRID's own `InteractionTerm.key_name` cannot apply: it sets no name), so the
  loaders' terms merge into psi-mi-ontology's (MI:0018 has its name "two hybrid"); partner `Gene`s on
  `primaryIdentifier` (the resolved Entrez id). `InteractionExperiment` and `InteractionDetail` have no key in
  psi and are new objects, as on HumanMine. The model additions (`psi_additions.xml`, `biogrid_additions.xml`) do not
  touch `curation/extensions_additions.xml`. The live tests check each of these: no duplicate pair, pubMedId,
  InteractionTerm identifier or Gene primaryIdentifier, and every InteractionDetail has an experiment, an interaction
  and a type.
* **Partner genes.** 5,994 human genes are partner stubs: an Entrez id, the organism and the data set, **no symbol**
  (3,381 from both sources, 1,753 BioGRID only, 860 IntAct only). The RDF `ncbigene` and `hgnc` sources are
  panel-scoped, so nothing names them; the Cytoscape tool labels such a node with its Entrez id (CYP2D6: CYP2C9 by
  symbol, 1528, 5447, 51374 by id). Loading every human gene as an identifier with its symbol is a separate task (D-1,
  `ncbigene=full`).
* **Result** (before: the homologue build above):

  | | before | after |
  |---|---|---|
  | Interaction / InteractionDetail | - | 22,351 / 37,826 |
  | InteractionExperiment / InteractionTerm / InteractionRegion | - | 2,692 / 1,480 / 78 |
  | Gene: human (panel + stubs) / all | 114 / 1,111 | 6,108 (114 + 5,994) / 7,105 |
  | Publication | 7,748 | 9,485 |
  | PAX6 `Gene.interactions` (IntAct / BioGRID partners) | - | 361 (138 / 350); HumanMine (2022): 156 |
  | CYP2D6 `Gene.interactions` | - | 4 (BioGRID 4, IntAct 1) |
  | all objects (`intermineobject`) | 465,814 | 554,192 |

  PAX6 has more partners than HumanMine's 156 because BioGRID 5.0 (2026) holds many more PAX6 interactions than the
  2022 release.
* **Timings** (driver from `rdfc2im_project`, 17 min in all): integrate 441 s (was 297 s; psi-mi-ontology about 10 s,
  psi-intact 50 s, biogrid 131 s), postprocess 113 s (was 101 s). Disk: `stock_ut/` 2.7 GB (raw IntAct 1.06 GB, BioGRID
  208 MB, filtered groups 380 MB), Postgres 2.3 GB; the root disk is untouched (3.4 GB free before and after).
* **Report page.** `apply_report_layout.py`'s `TOOL_QUERIES` guard for the Cytoscape tool now lists every path of the
  query bundled in the tool (`Gene.interactions.participant2.symbol`, ..., `Gene.interactions.details.dataSets.name`);
  they resolve once these sources are loaded, so the Interactions category comes back by itself with the class table,
  the tool and both templates. The guard stays for builds without them. 37 HumanMine templates load (was 30).
  On the PAX6 report page in Chromium the panel draws the network (361 nodes) and no request to the mine answers 400
  (109 requests). `Gene_Interactions_forReportPage` returns 433 rows for PAX6 and 6 for CYP2D6.
  `Gene_Interact_disease` loads but returns no rows: it inner-joins `Gene.interactions.participant2.diseases`, and
  `Gene.diseases` is empty in this mine (hpo-annotation and omim, T1.10).

#### Expression and disease: protein-atlas, protein-atlas-rna, gtex, atlas-express, hpo-annotation, orphanet [im-9n4.14, im-9n4.15]

`--stock-sources "... biogrid protein-atlas protein-atlas-rna gtex atlas-express hpo-annotation orphanet"` on the ut
stack. The converters are the fixed ones of humanmine-bio-sources d67fc5d: `in/.upstream/humanmine-bio-sources-6.0` was
fetched to that commit (`git fetch <checkout> maint-2026`, `checkout FETCH_HEAD`) and `$TRIAL_HOME/humanmine-bio-sources`
removed, so `build_humanmine_items` copied it again (its log line: `bio-sources checkout = maint-2026 ... at d67fc5d`) and
`build_stock_sources` built the jars from it. A build restarts from `build_humanmine_items` for this; the copy is only
made when the directory is missing.

| Source | Upstream file | Filter | Rows in / out | Loads |
|---|---|---|---|---|
| protein-atlas | `normal_ihc_data.tsv` (zip, 5.6 MB) + `rdfc2im/data/hpa_tissue_to_organ.tsv` | Ensembl id, column 1, header kept | 1,179,586 / 8,390 (90 of 115 ids) | ProteinAtlasExpression 8,390, Tissue 48, TissueGroup 15 (14 from the next rebuild: Retina moved to Brain) |
| protein-atlas-rna | `rna_tissue_consensus.tsv` (zip) | same | 1,026,292 / 5,814 (114) | RNASeqResult 5,814 |
| gtex | v8 `..._gene_median_tpm.gct.gz` | same, 3 header lines kept, Ensembl version stripped | 56,200 / 114 (114) | RNASeqResult 6,156 (114 x 54 tissues) |
| atlas-express | `E-MTAB-513-fpkms.tsv` | same | 58,735 / 114 | AtlasExpression 1,824 (114 x 16 assay groups) |
| hpo-annotation | `genes_to_phenotype.txt`, `phenotype.hpoa` | entrez id, column 1; then the diseases of that cut | 3,845 / 193 diseases; hpoa to 3,637 rows | see below |
| orphanet | `en_product1.xml` (54 MB) | none | 11,645 disorders | Disease 11,645 |

* `subset_raw.py`: `keep_header` may be a number of lines (GCT: `#1.2`, the dimensions line, the header); the tab filter
  strips an Ensembl version before matching; `disease-ids` writes `idsets/hpo-diseases.txt` from the filtered
  `genes_to_phenotype.txt` (as `partner-ids` does for PANTHER) and `phenotype.hpoa` is cut on column 1 to it. The
  panel list holds one wrong id for UGT1A1 (ENSG00000242366) beside the right one: only the right one matches, UGT1A1 loads once.
* One file per directory where the converter parses every file: atlas-express only the fpkms file (the tpms file would
  double every row, a `tpm` name makes the type TPM), protein-atlas-rna only `rna_tissue_consensus.tsv`, gtex no `signif` file.
* **Tissue groups.** `tissue_to_organ.tsv` has no download. Without it `Tissue.tissueGroup` is empty and the Protein Atlas
  tool's query (`proteinAtlasExpression.tissue.tissueGroup.name`, an inner join through the web service) returns
  nothing: the panel said "No data found!". `rdfc2im/data/hpa_tissue_to_organ.tsv` is a hand-written mapping of the
  48 tissues to the organ systems of HPA's tissue pages, shipped in the repository (table key `repo_file`) and staged as it is.
  Gos reviewed the grouping on 18 Nov 2026 and accepted it with one change: Retina is in the Brain group (14 groups,
  no separate Eye group).
  Check it against HPA before a release.
* **Levels** in the tool: HPA now says Not detected / Low / Medium / High (the tool's `STRENGTHS` knows exactly these) and the
  heat map colours them; the file also holds a few `Ascending`, `Descending` and `Not representative` (19 rows).
* **Merging.** No model clash between the four expression additions and `extensions_additions.xml`; Tissue is keyed on
  name, Gene on primaryIdentifier (no duplicate of either); RNASeqResult comes from two data sets without a key
  (HPA 5,814, GTEx 6,156). hpo-annotation's additions declare `Disease.dataSets` without the reverse reference, which our
  `Disease extends BioEntity` already has: `mergeModels` stopped ("replacing the BioEntity.dataSets collection with
  Disease.dataSets failed because the reverse references differ"). `build_humanmine_items` deletes that line in the build's
  copy of the fork (a logged deployer edit); the fork should drop it. And `Disease.name = omim, hpo-annotation, ...`
  starved the 72 ORPHANET diseases linked to panel genes of their name (hpo-annotation writes none), so
  `curation/priorities_override.properties` ranks orphanet above it.
* **Disease.** hpo-annotation keys Disease on primaryIdentifier (`OMIM:n`, `ORPHANET:n`); the ClinVar diseases (888 with a name only,
  no primaryIdentifier) have none, so nothing merges with them and nothing is duplicated. Orphanet is loaded
  whole: the 11,573 it holds that no panel gene links to are harmless stubs, and it needs no new filter. 121 OMIM diseases
  have no name (the cost of having no OMIM copy; the hpoa file has a `disease_name` column the converter does not store);
  all 11,645 ORPHANET have one. HPOTerm (1,523, all linked) has an identifier only: HPOTerm names need the RDF `hpo` source.
* **HPO counts.** 74 panel genes have a disease: 72 with OMIM (121 diseases), 44 with ORPHA (72 diseases). Evidence rows 3,637
  (OMIM 1,685, ORPHA 1,952, so 1,685 without the ORPHA rows), HPOAnnotation 3,631. The converter loads ORPHA annotations; undoing it is dropping
  `ORPHA:` rows from the two files. PAX6 has 15 diseases (8 OMIM, 7 ORPHANET), CYP2D6 1 (OMIM:608902).
* **The RDF `hpo` source** stopped integrate here; it loads since im-9n4.41 (next section).
* **Report page.** `TOOL_QUERIES` now lists `atlasExpression.tStatistic`/`pValue` for the three ArrayExpress tools (they need
  E-MTAB-62, `arrayexpress-atlas`, not loaded): they are dropped, as is `Gene_SigSNP` (`EMPTY_TEMPLATES`: no eQTL). Kept: both
  Protein Atlas and Human Tissue tools, `Gene_Disease2`, `Gene_Disease_HPO`, `Gene_HPOphenotype_2`. On the PAX6 page in Chromium
  no request answers 400 and no script error.
* **Counts** (before: the interactions build). All objects 554,192 -> 597,076; PAX6 proteinAtlasExpression 137 (HumanMine
  2022: 90), rnaSeqResults 105 (97), atlasExpression 16 (376, which had the frozen E-MTAB-62); CYP2D6 97 / 105 / 16.
  Templates on PAX6: `Gene_Disease2` 15 rows, `Gene_Disease_HPO` 187, `Gene_HPOphenotype_2` 187, `Gene_Interact_disease` 7 (it had
  none), `Gene_SigSNP` 0.
* **Timings and disk.** `subset_stock_data` 11 s from the cache (the expression files 20 s cold), integrate 391 s with the four
  expression sources (was 441 s with a warm machine; 717 s on the last run), postprocess 115 s, whole driver run from
  `rdfc2im_project` 18 min. `stock_ut/` 2.9 GB, Postgres 1.2 GB, root disk 3.3 GB free before and after.
* **Licence.** The HPA groups are `redistributable: true` with the CC BY-SA note (share-alike); nothing from OMIM is loaded
  or cached. `cache check-release` passes on `cached_raw_data/` (16 groups) and on the stock filtered cache (13).

#### HPO term names: the RDF hpo source beside hpo-annotation [im-9n4.41]

`--sources "go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed hpo"` with the stock list above. `hpo`
`replaces: [hpo]`: the stock OBO `hpo` entry (in HumanMine's project.xml right before `hpo-annotation`) moves to
`replaced_sources.xml`, and `humanmine-hpo` loads with the other rdfc2im sources, after `humanmine-hgnc`, so still
before `hpo-annotation`, as on HumanMine. Its terms merge into hpo-annotation's identifier-only `HPOTerm`s through
`HPOTerm.key_identifier` (now in the generated keys file).

* **Why it failed.** Not the cross references. `ItemStore` keyed items on the raw Unicode value, but `write()` folds every
  attribute to ASCII (the large-file loader's UTF-8 bug, see `items.py`). HP:0011002 (Osteopetrosis) has the related
  synonyms "Albers-Schonberg disease" and "Albers-Schönberg disease": two `OntologyTermSynonym` items, identical once
  written. InterMine keys that class on `name` (the GO synonyms already in the database make the key live), so the
  `ParallelBatchingFetcher` prefetch of the batch holding the term (items 5,001 to 10,000) failed with "Duplicate objects
  found for pk" in a worker thread (the log shows only `PrefetchManager ... Error in worker thread`). That fetch had
  already put the batch's collection members into the translator's `doneAlready` set; the batch was fetched again in the
  main thread, those members came back as `ProxyReference`s never stored, and the first one met, `UMLS:C1850970` in
  HP:0007541's `crossReferences`, stopped the load with "Given a ProxyReference, but id not in ID Map".
* **The fix.** `ItemStore.key_for` keys on `to_ascii(value)`, so items InterMine would see as identical are one item (and
  equal-once-folded values are not reported as conflicts). The hpo items have one synonym fewer (29,090) and no duplicate
  under any key the integration uses except two obsolete terms named "obsolete Radial deviation of the thumb" (key
  `name, ontology`; harmless while the HPO `Ontology` is new when humanmine-hpo loads, as here, because the fetcher's
  hints then skip that key; GO has 22 such pairs and loads the same way).
* **Cross references.** HumanMine's own loader keeps an OBO `xref` only when its prefix is in bio/core's
  `obo_xrefs.properties` (FBbt, FMA, MA, WBbt, ZFA; `OboParser.addXrefs`); HumanMine has 0 `HPOTerm.crossReferences`,
  no `UMLS:` term at all, and 8 GOTerm cross references (www.humanmine.org, 18 Nov 2026). The `oboinowl:hasDbXref` entry
  in `knowledge.yaml` now carries the same rule as a filter, for every ontology: the 17,547 `UMLS:`/`SNOMEDCT_US:`/`NCIT:`/
  `MSH:` HPOTerm stand-ins and the 29,760 nameless `Reactome:`/`RHEA:`/`EC:` GOTerms of the RDF go source (im-9n4.38) are no
  longer made; go keeps 8 cross references (48,348 GOTerms, was 78,100). The queries and the cache are unchanged (the
  filter applies to the fetched rows).

| | before (no hpo) | with hpo |
|---|---|---|
| HPOTerm / without a name | 1,523 / 1,523 | 20,413 / 0 (all `HP:`) |
| GOTerm / without a name | 78,100 / 29,760 | 48,348 / 8 |
| OntologyTermSynonym | 79,819 | 108,909 |
| `Gene_Disease_HPO` / `Gene_HPOphenotype_2` for PAX6 | 187 / 187 rows, every term name empty | 187 / 187 rows, every term named |
| duplicate HPOTerm / OntologyTerm identifier | 0 / 0 | 0 / 0 |
| PAX6 / CYP2D6 deep counts (proteins, alleles, GO, homologues, interactions, expression, diseases) | | unchanged |
| all objects | 597,076 | 615,144 |

Integrate 521 s (humanmine-hpo 14 s), postprocess 116 s, the whole driver run from `rdfc2im_pipeline` 17 min.
Live tests `test_hpo_terms_*` skip on a mine without the `Human Phenotype Ontology (RDF Portal)` data set.

**`Disease.dataSets` and the fork.** `build_humanmine_items` still deletes `Disease.dataSets` from the build's copy of
`hpo-annotation_additions.xml`. Deleting it in the fork is not the fix: on HumanMine `Disease extends Annotatable`, which
has no `dataSets`, so the line is what gives HumanMine's Disease its data sets (its `/service/model/Disease` lists
`Disease.dataSets`; `BioStoreHook.setDataSets` fills it for every hpo-annotation and orphanet Disease). The clash exists
only because this repository's `curation/extensions_additions.xml` makes `Disease extends BioEntity`, whose `dataSets`
has the reverse `DataSet.bioEntities`. A fork change that works for both would have to make HumanMine's Disease a
BioEntity too; until someone decides that, the build's logged edit is the right place.

#### All human genes as identifiers: `--gene-identifiers all` [im-9n4.40, T1.15]

Decision D-1 (plan 50 2.2 b): the mine holds every human gene as an identifier, the deep annotation only for the panel.
`--gene-identifiers all` makes the RDF `ncbigene` and `hgnc` sources `SCOPE_MODE` `full` (`--taxon 9606`, no
`--genes`); every other source keeps its mode. The default stays `panel`: the 5.1.1 baseline, CI and the release
cache are unchanged (the dry-run tests check both).

What has to stay panel-scoped, and how:

* **The stock filters.** `subset_raw.py idsets` derives the Entrez, Ensembl and UniProt id sets the stock raw files are
  cut to from `out/<source>/items`. It only takes genes whose symbol is in the panel, so with 64,000 genes in the
  ncbigene and hgnc items the sets are still the panel's (a unit test runs it on an every-gene fixture; on the real
  build `idsets/*.txt` are byte-identical to the panel build's). Without that, every stock filter (UniProt XML, GAF,
  GFF, PSI-MI, expression) would stop filtering.
* **The PMIDs pubmed is fetched for.** They are grepped from `out/{hgnc,uniprot,gwascatalog,reactome}/items`; a full
  hgnc cites about 23,500 papers (and the grep also catches its 44,000 Entrez ids), so the PMID set, its md5 and the
  cached pubmed group would no longer be the panel's. With `all` the grep reads `subset_raw.py panel-items`' cut of the
  hgnc items instead: the panel genes (by the Entrez ids of the gene-id lookup) and every non-Gene item they reach.
  On the real items the PMID file is identical to the panel build's, so the panel's pubmed cache group is reused.
* **Gene types.** RDF Portal's NCBI Gene graph holds 194,018 human records, 128,261 of them `biological-region` (the
  "193,000 genes" of the scope bug). The stock ncbi-gene loader never loads `other`, `biological-region` or `unknown`
  (`NcbiGeneInfoParser.TYPES_TO_IGNORE`). ncbigene's `full_scope_filter` (sources.yaml, `scope.apply_full_scope_filter`)
  restricts an unscoped run to the other eight types; the field is promoted to required, so it joins every table's
  query and the synonym and cross-reference tables of a dropped record are not fetched either. A gene-scoped run never
  applies it: the panel queries are unchanged.
* **Shared symbols.** In the whole genome ten tRNA symbols (TRNAG-GCC, TRNAD-GUC, ...) are each NCBI's Symbol for 2 to
  17 Entrez records; InterMine also keys Gene on `(symbol, organism)`, so they would merge. NcbiGeneConverter sets a
  symbol only when it is unique in the taxon; ncbigene's `key_ambiguity` now also lists `symbol` with no preferred
  holder, so it is dropped from every gene that shares it.
* **Proteins.** hgnc links every protein-coding gene to its UniProt accession. In a panel build those Protein items merge
  into stock UniProt's; with every gene about 20,000 are proteins of their own, an accession and a gene and nothing
  else. `organism_from_genes: [Protein]` gives them the organism of their gene (`items.organisms_from_genes`), so no
  Protein lacks an organism.

* **Merging (plan 50 risk 3).** Gene is keyed on `primaryIdentifier`, `(symbol, organism)` and `(secondaryIdentifier,
  organism)`, and an object merges into everything any key finds. Checked on the items before the first load
  (`merge_risk`/`simulate` scripts of the bead): the RDF NCBI and HGNC snapshots disagree on who owns 9 symbols (HGNC
  still gives KCNIP4-AS2 to Entrez 105374516, NCBI to 143433685; RNR1/RNR2 are HGNC's 6052/6053, of NCBI type `other`,
  while NCBI's own Symbol column names MT-RNR1 and MT-RNR2 "RNR1"/"RNR2") and 109 Ensembl ids (each on one Entrez gene in
  one source and another in the other), and HGNC's own data gives 6 Ensembl ids to two genes. Through the symbol and
  Ensembl keys every one of these would have merged two Entrez genes. Three rules:
  1. `own_keys: {Gene: [primaryIdentifier]}` for ncbigene and hgnc: `rdfc2im project` writes
     `humanmine-ncbigene_keys.properties` and `humanmine-hgnc_keys.properties` (the type file without Gene's symbol and
     Ensembl keys; InterMine reads `<source name>_keys.properties` before `<type>_keys.properties`), and `make fork-sync`
     puts them in the humanmine-items jar. Their genes all carry the Entrez id, so nothing is lost; ensembl, uniprot and
     gwascatalog, which have no Entrez id, keep the full keys and still find their (panel) gene by symbol or Ensembl id.
  2. hgnc `defer_to: ncbigene` for `symbol` and `secondaryIdentifier`: where ncbigene gives the value to another Entrez
     gene, hgnc's copy is dropped (9 symbols, 106 Ensembl ids); ncbigene ranks first for both fields anyway. It reads
     `out/ncbigene/items`, so ncbigene must come before hgnc in `--sources` (it does by default).
  3. hgnc `key_ambiguity` on `secondaryIdentifier` (6 genes), as ncbigene already had for its 492.
  The simulation of the merged table then has 0 duplicate symbols and 0 duplicate Ensembl ids among 64,470 Entrez genes,
  and all 5,994 interaction-partner stubs named.
* **Chromosomes.** ncbigene's chromosome column (a `guess` row) gave the whole genome three extra Chromosome objects,
  `MT`, `Un` and `X|Y`, with no length (the GFF names 24). `knowledge.yaml` now filters it to `1`-`22`, `X`, `Y`; the
  37 MT genes and the unplaced ones keep their row, without a chromosome (ncbi-gff maps no MT either).
* **Integrate memory.** One Gradle daemon loads every source and its 4 GB heap is not given back between them: on the
  first all-genes run the old generation was full by panther (1,976 full collections, 46 min of GC, no progress; it had
  to be killed). With `all`, `integrate_sources` runs each source with `--no-daemon`.

**The build** (ut stack, the stock list of the disease build, `--sources "... pubmed hpo" --gene-identifiers all`):

| | panel (hpo build above) | all genes |
|---|---|---|
| human Gene / with symbol / with Ensembl id | 6,108 / 114 / 113 | 64,470 / 64,359 / 45,051 (HumanMine 2022: 64,160 / 56,020 / 42,429) |
| interaction-partner stubs without a symbol | 5,994 | 0 (PAX6's 361 partners and CYP2D6's 4 all named) |
| orthologue partner genes (6 organisms) / with symbol | 997 / 182 | 997 / 182 |
| duplicate Gene.primaryIdentifier / symbol (9606) / Ensembl id (9606) | 0 / 0 / 0 | 0 / 0 / 0 |
| Protein / genes-proteins links | 13,723 / 1,687 | 22,630 / 21,950 (hgnc's accession stubs, all with an organism) |
| Synonym / CrossReference / Publication | 6,696 / 32,561 / 9,550 | 232,023 / 221,697 / 32,794 (25,899 without a title: hgnc's references) |
| Chromosome / GeneFlankingRegion / Location | 24 / 2,260 / 16,603 | unchanged (only the panel genes are located) |
| PAX6 / CYP2D6: proteins, alleles, pathways, GO terms, homologues, interactions, HPA, RNA-seq, atlas, diseases, transcripts | 47, 996, 5, 57, 12, 361, 137, 105, 16, 15, 53 / 59, 356, 6, 33, 67, 4, 97, 105, 16, 1, 2 | identical |
| all objects | 615,144 | 1,120,120 |

The 64,470 human genes are the 63,649 NCBI records of the kept types plus 821 Entrez ids only HGNC names (types NCBI files
as `other` or `unknown`, such as the PIRC piRNA clusters and RNR1/RNR2, or records NCBI has since replaced); the 111 without
a symbol are the 106 genes of the ten shared tRNA symbols and 5 HGNC-only genes whose symbol NCBI gives to another gene.
`idsets/*.txt` and `cited_pmids.txt` are byte-identical to the panel build's, so every stock filter and the pubmed group
are the panel's. A list of 20 non-panel symbols (BRCA1, BRCA2, TP53, ...) uploaded through `/service/lists` resolves 20 of 20
(0 before); `/service/ids` finds BRCA2 by symbol, by `HGNC:1101` (a synonym match) and by `ENSG00000139618`; keyword search
finds BRCA2 first. The Cytoscape tool on the CYP2D6 page labels its four partners CYP2C9, POR, CYB5A, ATRAID (they were
CYP2C9, 1528, 5447, 51374).

* **Fetch** (once, RDF Portal, the configured 1 s between pages, one source at a time): ncbigene 767 s (466,399 rows, raw
  44 MB, 274,697 items), hgnc 898 s (778,913 rows, raw 15 MB, 333,149 items): 28 min. The cache groups are 45 MB and 15 MB
  (the panel's were 0.1 MB); the allgenes cache is 267 MB against the panel cache's 210 MB.
* **Build** from `rdfc2im_project`, all from the cache: 19.5 min. Integrate 809 s (was 521 s; humanmine-hgnc 164 s,
  humanmine-ncbigene 160 s, `--no-daemon` per source), postprocess 161 s (was 116 s; the two search-index passes 45 s and
  49 s), `rdfc2im_pipeline` from the cache 110 s. Postgres 2.2 GB (`pg_database_size`; the volume 3.3 GB), Solr 275 MB.
  Lowest available memory during the build 2.6 GB (0.66 GB in the panel build, whose integrate shares one daemon). Root
  disk unchanged (3.0 GB free; the worktree's `out/` grew by about 200 MB of items).
* **ensembl=full is not cheap**: RDF Portal holds 53,636 human Ensembl genes, and 845 labels are each shared by several of
  them (4,678 genes: haplotype and patch copies, Y_RNA, U6, ...). ensembl has no Entrez id, so it merges on symbol and
  Ensembl id: it would need its own `key_ambiguity` on the symbol and a rule against NCBI/HGNC's Ensembl ids before it
  could load, for no gain the two sources do not already give (45,051 genes carry an Ensembl id from them). Left `panel`.

**The CI data asset should stay panel-scoped.** The panel cache is what CI and the 5.1.1 baseline build from; `all`
changes neither (default `panel`, dry-run tests). Everything the gene panel exercises is exercised there, while the
all-genes groups add 60 MB to the asset, half an hour of network to refresh and five minutes and half a million objects
to every CI build, with no test that needs them. Publish the allgenes cache as a second, optional asset (both sources
are redistributable: NCBI Gene public domain, HGNC CC0) when the demo mine or the PanelApp lists of milestone 2 need it.

The cache groups of the two sources are saved as `scope=full` (no `genes_md5`), so a panel cache refuses them and they
refuse a panel build: they live in a cache of their own (`--cache-dir`, here `repos/rdfc2im/cached_raw_data.allgenes-
2026-11-18`, a verified copy of the panel cache with the two groups replaced).

### The ID-resolver gate [im-9n4.4]

The stock loaders for psi, biogrid, panther, omim and the HumanMine expression sources have no gene filter of their
own. omim and the expression sources are `filter: none` in the table; panther, psi-intact and biogrid are pre-filtered
to records with a panel gene, since with the all-human resolver the gate cuts nothing from a human file
[im-9n4.12, im-9n4.13]. The other cut is the mine's ID resolver: each of those converters asks
`EntrezGeneIdResolverFactory` whether it knows a gene and drops what it does not. With a non-empty
`--stock-sources` the build therefore gives the resolver a gene list (plan 50 2.2, decision D-1):

* `fetch_stock_data` downloads NCBI's `Homo_sapiens.gene_info.gz` (public domain, 5.2 MB; cache group
  `stock-raw-resolver` in the stock cache, same URL / `Last-Modified` rules as the other raw groups).
* A source with `resolver_taxa` in the table (panther: rat 10116 and zebrafish 7955) adds NCBI's per-organism file of each
  taxon (`rdfc2im stock resolver`; cache group `stock-raw-resolver-<taxon>`); each is cut to its taxon and appended to
  `entrez` [im-9n4.12].
* `subset_stock_data` runs `subset_raw.py filter --format gene_info --taxon 9606` on it and writes the result
  uncompressed as `$RDFC2IM_STOCK_DIR/resolver/entrez`. The default keeps **every** human gene, because the mine
  holds all human genes as identifiers (deep annotation only for the panel): interaction and orthologue
  partners outside the panel must still resolve. `--resolver-scope panel` keeps only the panel's Entrez ids
  (`idsets/entrez.txt`) for anyone who wants the strict subset; partners outside the panel are then dropped.
* `prepare_mine_checkout` adds `resolver.file.rootpath=$RDFC2IM_STOCK_DIR/resolver` to the generated
  `~/.intermine/humanmine.properties` and deletes any `idresolver.cache` under the mine checkout
  (`find ... -maxdepth 3 -name idresolver.cache -delete`).

What the factory needs (`bio/core/.../EntrezGeneIdResolverFactory.java`, `NcbiGeneInfoParser.java`):

* the file is `<resolver.file.rootpath>/entrez` (lines 39-40 and 183), read with a plain `FileReader` (line 215),
  so it must be **uncompressed**; the name has no extension;
* tab-delimited NCBI `gene_info`: `#` lines skipped, column 1 the tax id, 2 GeneID, 3 symbol, 4 locus tag,
  5 synonyms, 6 dbXrefs, 8 map location, 9 description, 10 gene type, 11 and 12 the nomenclature symbol and
  name (parser lines 61-79); rows of type `other`, `biological-region`, `unknown` or empty are ignored;
* with `resolver.file.rootpath` unset the factory logs a warning and returns an empty resolver (lines 177-181);
  a missing file is only a warning too (line 191), so the gate must be checked in the log
  (`Creating id resolver for [9606] ... from data file`);
* after reading the file it writes a **cache**, `idresolver.cache`, to the working directory of the JVM
  (`resolver.writeToFile(new File(idResolverCachedFileName))`, line 189; the name is in
  `IdResolverFactory.java:40`), and on the next call restores it from the *classpath*
  (`getClassLoader().getResource("idresolver.cache")`, `IdResolverFactory.java:93-99`), preferring it to the
  data file. A stale cache therefore silently overrides a changed entrez file, which is why the build deletes
  it. For the Gradle `:dbmodel:integrate` run the working directory is the mine's `dbmodel/` (or the mine
  root), so the delete looks three levels down from the mine checkout. After a `--from integrate_sources`
  resume that follows a change of `--resolver-scope`, delete it by hand.

`--use-cached-data` and `--offline` verify the raw group and re-filter it (a few seconds); no filtered copy of
the resolver file is cached.

Large raw data: UniProt Swiss-Prot human is 175 MB gzipped, IntAct human 1 GB, the genome FASTA
973 MB. In the sandbox set `RDFC2IM_STOCK_DIR` (or `RDFC2IM_DATA_ROOT`) to a directory under
`repos/.sandbox-disk/`; the sandbox root has about 4 GB free.

```sh
python3 -m rdfc2im stock list                       # the table
python3 -m rdfc2im stock check go-annotation uniprot --sources "go ncbigene uniprot"
tools/full-build.sh --dry-run --intermine-src DIR --stack-name ut --stock-sources "go-annotation uniprot"
```

### A second stack

`--stack-name NAME` runs a second Compose stack beside the default one, for example the
`--intermine-src` build next to a published-artefact build. Its containers and volumes are
`rdfc2im-NAME-*` (`RDFC2IM_PREFIX`), its Compose project is `rdfc2im-NAME`
(`COMPOSE_PROJECT_NAME`; without a project of its own, a second `up` in the default project
`trial` would recreate the first stack's containers) and its ports default to

| Service | Default stack | `--stack-name` |
|---|---|---|
| Postgres | 15432 | 25432 |
| Solr | 8983 | 18983 |
| webapp | 8090 | 18090 |
| BlueGenes | 5000 | 15000 |

Each port can still be set with `PG_PORT`, `SOLR_PORT`, `MINE_PORT` and `BG_PORT`, which
`trial/docker-compose.yml` reads directly. Tomcat listens on `MINE_PORT` inside its container too,
and `webapp.baseurl` uses it, because the webapp fetches its own `query.xsd` from
`webapp.baseurl`. A Solr port other than 8983 is written into the mine's two Solr URLs, so
postprocess indexes this stack's Solr. `check_prereqs` refuses to start when one of the ports is
already published by a container that is not this stack's, since the host-side `builddb` would
otherwise drop the other stack's database.

`RDFC2IM_PGDATA` and `RDFC2IM_SOLRDATA` (absolute host directories) put the PostgreSQL and Solr data
somewhere other than `/var/lib/docker`: `trial/docker-compose.yml` then makes `pgdata` and `solrdata`
bind mounts of them (`start_databases` creates the directories). Unset, they are ordinary named
volumes, as before. Set them before the stack's first `start_databases`; Compose reuses a volume that
already exists, whatever kind it is. This replaces creating the bind volumes by hand with
`docker volume create --opt type=none --opt o=bind --opt device=DIR`.

Give the second stack its own `TRIAL_HOME` and `HOME` (the mine's
`~/.intermine/humanmine.properties` carries the ports).

`RDFC2IM_ARTIFACTS` is the directory `stage_artifacts` (`tools/trial-stage.sh`, `make trial-stage`) writes
the exploded war (`humanmine/`) and BlueGenes' jars (`bluegenes-lib/`) to, and that
`trial/docker-compose.yml` bind-mounts into the mine and BlueGenes containers [im-ore.21]. Unset it is
`trial/artifacts` in the checkout for the default stack (as before); with `--stack-name` it is
`$TRIAL_HOME/artifacts`. Before this the two stacks shared `trial/artifacts`, so a rebuild of the
default stack replaced the war the named stack was serving (every query on its port then failed: the
webapp fetches its own `query.xsd` from the other stack's `webapp.baseurl`). A stack that is already
running keeps its old mount until it is recreated (`docker compose up -d`/`start_mine_stack` with the
variable set). Still shared between stacks by design: the repository checkout (`out/<src>/`,
generated items and TSV, which only matter during a build's `stage_src_data`/`integrate_sources`),
`cached_raw_data/` and `in/.upstream` (read-only caches), the Docker images, and, unless
`RDFC2IM_DATA_ROOT`, `LOG_DIR`, `HOME` or `GRADLE_USER_HOME` are set per stack, `/micklem/data`,
`.build-logs/` and `~/.gradle`. Per stack through `TRIAL_HOME`: the mine and bio-sources checkouts,
`bgdeps` (the BlueGenes jar resolution), `m2-intermine` and now `artifacts`.

`RDFC2IM_DATA_ROOT` (default `/micklem/data`) is the directory the mine's source data lives under:
`stage_src_data` symlinks each `out/<src>/items/<src>.xml` into `$RDFC2IM_DATA_ROOT/rdfc2im/<src>/`,
the Reactome mapping goes to `$RDFC2IM_DATA_ROOT/reactome/current/`, and the mine checkout's copy of
`project.xml` has every `"/micklem/data/` rewritten to the root, so `integrate_sources` reads what
was staged. Set it per stack (for example under the stack's own `HOME`) and two stacks no longer
share or overwrite one another's staged files; left unset, both stacks keep sharing `/micklem/data`,
which is harmless only while they are built from the same cache. Set it before the stack's
`prepare_mine_checkout`, since that is where `project.xml` is rewritten. `check_prereqs` creates the
directory (with `sudo` if it has to).

### Browser-facing URLs and the BlueGenes service root

`webapp.baseurl` is `http://localhost:$MINE_PORT` and so is BlueGenes' only service root
(`BLUEGENES_DEFAULT_SERVICE_ROOT`): both are URLs the browser follows, and the webapp fetches its
own `query.xsd` from `webapp.baseurl`, so they must also resolve inside the mine container.
BlueGenes uses the backend root (`BLUEGENES_BACKEND_SERVICE_ROOT`), when one is set, to build URLs it
hands to the browser - the `/favicon.ico` redirect and the schema.org JSON-LD in the page - so a
compose-internal `http://mine:$MINE_PORT` there leaked into what the browser follows [im-ore.8]
(`curl -sI :$BG_PORT/favicon.ico` gave `Location: http://mine:18090/humanmine/model/images/favicon.ico`,
and 21 `http://mine:18090` in the front page). The variable is no longer set. Instead the
`bluegenes` service runs with `network_mode: "service:mine"`, so `localhost` inside BlueGenes is the
mine and the one public root works for the server and the browser; the mine service publishes
BlueGenes' port (`BG_PORT:5000`) for it. Consequence: restarting the mine container alone leaves
BlueGenes on a dead network namespace - restart both (`docker restart $PREFIX-mine
$PREFIX-bluegenes`, which `start_mine_stack` and `apply_templates` do) or `docker compose up -d`. If
you serve the stack under another host name, `webapp.baseurl` and the service root need it too, and
the mine container must be able to resolve it.

## Caching the fetched data

The slow, remote part of a build is the SPARQL extraction (phase 3) plus a few downloads. Every
normal run saves what it fetched to `cached_raw_data/` (gitignored, in the repository root - so on a
sandbox it is on the host side of the workspace mount, and outlives the sandbox), and

```sh
tools/full-build.sh --use-cached-data
```

restores it instead of asking the network. There are two modes, because one input is not in the cache:
the four upstream repositories cloned into `$UPSTREAM_CACHE` (default `in/.upstream`) are git's own
cache, not part of `cached_raw_data/`, and a fresh checkout (the BlueGenes nightly CI runner, a new
laptop) has none.

| Option | Cached inputs (SPARQL results, gene-id lookups, HumanMine model, Reactome map) | Upstream clones in `$UPSTREAM_CACHE` | Network needed by the data phases | Guards |
|---|---|---|---|---|
| none | fetched, then saved | cloned if missing, else `git pull` | yes | none |
| `--use-cached-data` | restored from `cached_raw_data/` | cloned if missing, else left as they are (no pull) | only the clones, and only when missing | none: a lookup missing from the cache is asked from the network |
| `--offline` (implies `--use-cached-data`) | restored from `cached_raw_data/` | must exist: a missing one stops the build | none | `RDFC2IM_OFFLINE=1` for the pipeline: any SPARQL request raises `OfflineError` naming the endpoint, a missing lookup names the file |

`--offline` is the mode to use where a network request would be a bug (`unshare -rn tools/full-build.sh
--only rdfc2im_pipeline --offline` runs in a namespace with no network at all); `--use-cached-data`
is the everyday and CI mode. The build phases that follow the data phases still need the network for
their tooling (Gradle and Maven downloads, Docker images, the 6.0 line's HumanMine clone) in both
modes - that is not data and is not cached here.

Everything the data phases take from the network, and where `--use-cached-data` / `--offline` finds it:

| Fetched from | Phase | Saved as (fetch run) / read from (`--use-cached-data`) |
|---|---|---|
| RDF Portal and TogoVar SPARQL endpoints (`rdfc2im fetch`; PubMed, MeSH, GWAS Catalog included) | `rdfc2im_pipeline` | `cached_raw_data/<source>/`, one entry per source (9 for the demo panel) |
| RDF Portal SPARQL, gene symbol -> NCBI/Ensembl id (`translate --genes`, `scope.resolve_gene_ids`) | `rdfc2im_pipeline` | `cached_raw_data/gene-id-lookup/` (keyed to taxon and gene-panel md5) |
| humanmine.org `/service/model?format=xml,json` | `fetch_inputs` | `cached_raw_data/humanmine-model/` |
| reactome.org `UniProt2Reactome[_All_Levels].txt` | `build_stock_sources` | `cached_raw_data/reactome-uniprot-map/` (keyed to `--reactome-levels`) |
| `--stock-sources` upstream files (UniProt, GO, NCBI, ...) | `fetch_stock_data` | `$RDFC2IM_STOCK_DIR/cache/stock-raw-<name>/` (keyed to URL and Last-Modified); not in `cached_raw_data/` |
| (derived) `--stock-sources` files cut to the panel | `subset_stock_data` | `cached_raw_data/stock-<name>/` (keyed to genes_md5, taxon, spec_md5); restricted data in the stock cache instead |
| GitHub: rdf-config, intermine, humanmine, humanmine-bio-sources | `fetch_inputs` | not in `cached_raw_data/`: the clones in `$UPSTREAM_CACHE` (default `in/.upstream`); `--use-cached-data` clones a missing one and never pulls, `--offline` makes no attempt and a missing clone stops the build |

Nothing else in those phases is networked (`rdfc2im project`, `check`, `tsv`, `items`,
`make fork-sync` are local). To be sure, `--offline` also exports `RDFC2IM_OFFLINE=1` for the
pipeline phase: any SPARQL request that is still attempted stops with `RDFC2IM_OFFLINE=1: refusing a
SPARQL request to <endpoint>`, and a gene-symbol lookup missing from the cache stops with the name of
the missing file. A fetch run sets `RDFC2IM_RESOLVER_REFRESH=1`, so its lookups are asked afresh (not
read from an older run's file) and then saved.

The lookup cache is on by default for `rdfc2im translate` too, outside `full-build.sh`: the answers
live in `$RDFC2IM_RESOLVER_CACHE`, else `out/_resolver/`, one file per resolver, taxon and symbol list
(`resolve_ncbigene_symbols-9606-<md5 of the sorted symbols>.txt`); delete the file to resolve again.
`full-build.sh` keeps that directory in step with `cached_raw_data/gene-id-lookup/`.

Layout: one directory per source (`go/`, `ncbigene/`, ...) plus `reactome-uniprot-map/`, `humanmine-model/` and `gene-id-lookup/`, each
holding `data/` (the files), `MD5SUMS` (`cd cached_raw_data/go && md5sum -c MD5SUMS` works) and
`META.json`. `python3 -m rdfc2im cache list|verify|save|restore` manages it directly.

Two guards, both because of failures this project has had:

- **Copies are verified.** Plain `cp` has silently turned a file into the same number of NUL bytes
  on the virtiofs workspace mount. Every copy into or out of the cache hashes what it read,
  re-reads what it wrote and compares before renaming into place; a bad copy is retried, then
  fails the build - it never leaves a wrong file under the real name. Restore also checks the
  cached files against `MD5SUMS` first.
- **A cache records what it was fetched for** - scope mode, taxon, and the md5 of the gene panel
  (for `pubmed`, of the cited-PMID list) - and a restore whose build needs something different is
  refused, rather than quietly building a different mine from the wrong data.

If the cache is missing, incomplete or corrupt, `--use-cached-data` stops with the reason; drop
the option to fetch afresh and re-save.

### The phases

| # | Phase | What it does |
|---|---|---|
| 1 | `check_prereqs` | Tool checks, JDK 8, `/micklem`, `~/.gradle/gradle.properties`, source-list and stock-source-list validation |
| 2 | `fetch_inputs` | `tools/make-inputs.sh`: clones rdf-config, intermine, humanmine, humanmine-bio-sources; fetches the live HumanMine model |
| 3 | `rdfc2im_pipeline` | Per source: `translate` → `fetch` → `tsv` → `items`. The RDF extraction. |
| 4 | `rdfc2im_project` | `project` → `check` → `make fork-sync` (project.xml, keys, additions, priorities) |
| 5 | `build_humanmine_items` | Builds and installs the `bio-source-humanmine-items` loader jar |
| 6 | `build_stock_sources` | Builds stock `bio-source-reactome` (converter only, for now) and downloads `UniProt2Reactome.txt`; then the `--stock-sources` jars (was `build_reactome_source`) |
| 7 | `fetch_stock_data` | `--stock-sources` only: downloads the upstream files into the stock cache |
| 8 | `subset_stock_data` | `--stock-sources` only: panel id sets, then the files cut to them (`tools/subset_raw.py`) |
| 9 | `prepare_mine_checkout` | Copies and patches the humanmine checkout; writes `~/.intermine/humanmine.properties`; trims project.xml to the sources actually loaded |
| 10 | `stage_src_data` | Symlinks each `out/<src>/items/<src>.xml` into `$RDFC2IM_DATA_ROOT/rdfc2im/<src>/` (default `/micklem/data`), and the `--stock-sources` files into HumanMine's own paths there |
| 11 | `start_databases` | `docker compose up -d postgres solr`; creates the three databases and two Solr cores |
| 12 | `build_dbmodel` | `:dbmodel:builddb` and `:dbmodel:buildUserDB`; the reduced-mine trims |
| 13 | `integrate_sources` | `:dbmodel:integrate` per source, in project.xml's own order |
| 14 | `postprocess` | `create-references`, `create-attribute-indexes`, `ReactomePostProcess`, the Solr index (build → schema fix → clear → rebuild), autocomplete, objectstore summary |
| 15 | `build_webapp` | `:webapp:war` |
| 16 | `resolve_bluegenes_deps` | Resolves `org.intermine:bluegenes:1.4.5` to its 178 runtime jars |
| 17 | `stage_artifacts` | `tools/trial-stage.sh`: explodes the war, patches its baked-in DB/Solr hosts to the compose network's |
| 18 | `start_mine_stack` | `docker compose up -d mine bluegenes`, then restarts the webapp and BlueGenes (it reads the DB once, at startup) |
| 19 | `apply_templates` | Loads `curation/demo_public_templates.sql` into the userprofile DB; restarts the webapp and BlueGenes |
| 20 | `apply_public_lists` | `--public-lists DIR` only: archives the mine's public lists, then makes the Genomics England PanelApp lists and HumanMine's 13 other public lists public lists of the mine (`tools/apply_public_lists.py`); a logged no-op without the flag |
| 21 | `verify` | `/service/version`, `/service/model`, BlueGenes' root |

Load order in phase 13 is read back out of `project.xml` rather than re-decided, because the
`alongside` sources (`uniprot`, `reactome`) must integrate *after* the stock source they
supplement or they duplicate instead of merging.

### Keeping restricted data out of a release asset [im-9n4.4]

The CI release tarball is made from `cached_raw_data/`, so nothing licence-restricted may be in it (plan 50
decision D-7: OMIM, DisGeNET, KEGG). Two commands enforce that, using the `redistributable` and `licence`
values every stock cache group carries in its META (from `rdfc2im/data/stock_sources.yaml`):

```
python3 -m rdfc2im cache save GROUP DIR --cache-dir cached_raw_data --for-release --meta ...   # refuses, writes nothing
python3 -m rdfc2im cache check-release --cache-dir cached_raw_data                              # run before tarring
```

`--for-release` stops with exit 1 when the META says `redistributable=false`, and also when a group has no
`redistributable=true` at all (fail closed). The only groups allowed without a flag are those named in
`rawcache.RELEASE_ALLOWED_UNFLAGGED`, an explicit list in code (the RDF panel sources, `gene-id-lookup`,
`humanmine-model`, `reactome-uniprot-map`, `grch38-chromosome-lengths`, `bluegenes-tools`,
`bluegenes-tools-patched`); a new group, and the rdfc2im `disgenet` source, are refused until someone adds a flag
or a name. A `redistributable=false` source's filtered group is already kept out of `cached_raw_data/` by
`subset_stock_data`; `check-release` is the check that this stayed true. `full-build.sh` does not call it:
run it in the release job.

## The patched BlueGenes tool set [im-9n4.7]

A BlueGenes started with `BLUEGENES_TOOL_PATH=<dir>` serves its tools from `<dir>/@intermine/<name>/` (the
unpacked npm package) and `<dir>/tools.edn` (name -> version). The 2021 tarballs cached as
`cached_raw_data/bluegenes-tools` are not usable as they stand on a 2026 mine: the protein visualizer
searches RCSB's retired v1 endpoint, the MSA viewer posts to a host InterMine no longer runs (and its bundled
`msa` library crashes in current browsers), and the JBrowse 2 tool is not on npm. HumanMine runs hand-patched
copies; `tools/stage-bluegenes-tools.sh` (logic in `rdfc2im/bgtools.py`, standard library only) makes the same
copies:

```
tools/stage-bluegenes-tools.sh --jbrowse2-src ../jbrowse2/bluegenes-tool --out $OUT/bluegenes-tools-patched \
                               --install-to $TOOLS_DIR            # $TOOLS_DIR = BLUEGENES_TOOL_PATH
```

* Input: `--src-cache` (default `cached_raw_data/bluegenes-tools/data`, restore it first with
  `rdfc2im cache restore bluegenes-tools <dir>` if it is not in place) plus the `repos/jbrowse2/bluegenes-tool`
  checkout (its committed `dist/` is used; `--build WORKDIR` rebuilds it with `npm ci && npm run build` in a copy
  and gives the same bytes).
* Patches (ids in `patches.json`): `rcsb-v1-to-v2` (protein visualizer, bundle and source), `msa-same-origin`
  (the aligner address becomes `""`, so the tool POSTs to `/align-sequence` on the BlueGenes origin),
  `msa-array-at-crash`, `msa-legacy-wheel`, `msa-skip-no-sequence` [im-9n4.32] (see below), `jbrowse2-same-origin` (the JBrowse 2 tool's `config.json`
  `jbrowse2Url` `https://jbrowse2.intermine.org/` becomes `/jbrowse2/`, the front's route; HumanMine's own copy
  has `https://www.humanmine.org/jbrowse2/`), and `version-bump` to `<version>-patched.1` for the patched
  packages, except the MSA viewer, whose patch list grew and which is `2.1.1-patched.2` (`PATCHED_SUFFIXES` in
  `bgtools.py`; the protein visualizer stays `2.1.1-patched.1`; the JBrowse 2 tool is packed from source first,
  then patched like the others, so its version is `0.1.0-patched.1`). Each edit names its anchor text and how often it must occur; any other count aborts with exit 1, so a
  silent no-op cannot happen.
* Output: 19 tarballs, `SHA256SUMS`, `patches.json`, byte-identical for the same inputs. The esyn viewer, which
  HumanMine does not list, is left out and removed from `--install-to` if present.
* The patched set is cached as `cached_raw_data/bluegenes-tools-patched` (`rdfc2im cache save`, META records source
  versions, patch ids and sha256), so a build can also restore it and run `--install-to` alone with `--out`
  pointing at the restored `data/` (install checks every tarball against `patches.json`).

Phase `stage_artifacts` calls it after `tools/trial-stage.sh` when `--jbrowse2-src DIR` (or env `JBROWSE2_SRC`) is
given, with `--src-cache $RAW_CACHE_DIR/bluegenes-tools/data`, `--out <artifacts>/bluegenes-tools-patched` and
`--install-to <artifacts>/bluegenes-tools` (`<artifacts>` is `RDFC2IM_ARTIFACTS`, default `trial/artifacts`); without
the option nothing changes. The command it runs is, for the BlueGenes container's tool directory, e.g. `tools/stage-bluegenes-tools.sh --jbrowse2-src "$JBROWSE2_SRC" --out "$RDFC2IM_ARTIFACTS/bluegenes-tools-patched"
--install-to "$RDFC2IM_ARTIFACTS/bluegenes-tools"` (and mount that directory at BlueGenes' `BLUEGENES_TOOL_PATH`; `trial/docker-compose.yml` does not do that yet).
The `msa-skip-no-sequence` patch: upstream, the MSA viewer asks for each of the gene's proteins' sequence by
accession and gives up for the whole panel at the first protein with none ("No protein found for UniProtKB
accession ..."), so it never calls the aligner. With the patch such a protein is dropped (the sequence query
resolves `null` instead of rejecting; bundle and shipped source are edited alike). With no sequence left the
panel says "No protein sequences are available for this gene, so there is nothing to align." (plain text, not
matched by the browser suite's error-text check) and the aligner is not called; with one left the viewer shows
it unaligned, as upstream does for a gene with a single protein. Today only the Swiss-Prot canonical proteins and
their isoforms have sequences in a hybrid mine (the RDF TrEMBL proteins carry none until the uniprot source maps
`core:sequence`), so the viewer aligns exactly those: PAX6 gets P26367 and P26367-2, CYP2D6 gets P10635 and
P10635-2, in about 2.5 s from page load (one sequence query per protein, 47 and 59, issued together). Once the
TrEMBL proteins get sequences the viewer will align all of them (47 and 59); whether to restrict it to
Swiss-Prot or canonical proteins, as HumanMine effectively does, is an open decision and is not implemented.
The MSA viewer still needs the aligner container and a `/align-sequence` route on the BlueGenes origin
(sequence-alignment-service), and the protein visualizer and JBrowse 2 tool need the mine's protein/location data.

## JBrowse 2 on the front [im-9n4.10]

`trial/front/up.sh` also serves JBrowse 2 at `http://localhost:15001/jbrowse2/`, on the BlueGenes origin as
HumanMine does (docker_template's nginx `location /jbrowse2/`), so the tool's iframe is same-origin and needs no new
published port. Parts:

* image `rdfc2im-jbrowse2:latest` from the `repos/jbrowse2` checkout (jbrowse-web 4.3.0, pinned by SHA-256 in that
  Dockerfile, plus the InterMine plugin built with `npm ci`), 112 MB in all (the `nginx:1.27.1-alpine` base is 52 MB of it). Behind
  a TLS-inspecting proxy (the sandbox) the repo's Dockerfile cannot download or `npm ci` ("self-signed certificate in
  certificate chain"), so `trial/front/build-jbrowse2.sh` builds from a copy of the committed tree
  (`git archive HEAD`) whose Dockerfile gets the host CA bundle after each `FROM`; the checkout is not touched.
  `build-jbrowse2.sh --smoke` then runs the repo's `docker/smoke-test.sh` from that copy (it checks the committed
  public-mines `config.json`, which has a `humanmine-9606` assembly, not the demo's).
* container `rdfc2im-ut-front-jbrowse2`, `127.0.0.1:14881` only, with `$FRONT_HOME/jbrowse2/config.json` mounted over
  the image's `/config.json`;
* `trial/front/gen-jbrowse-config.sh` writes that config with `repos/jbrowse2/config/generate.mjs
  http://localhost:18090/humanmine 9606`. The URL is what the BROWSER uses for the mine's web service (it is written
  into the adapters): `http://localhost:18090/humanmine` works from the Mac because that port is published, and the
  mine answers CORS. The mine must be up; when it is not, the last generated config stays (none yet: the committed
  public-mines config is copied as a placeholder, with a warning). Run it again after a rebuild changes the tracks.
* assembly and track names come from the mine's `/service/jbrowse/config/9606/trackList.json` `dataset_id`, i.e. the
  mine's `project.title` plus the taxon: `rdfc2im: 114 gene food/drug-metabolism panel-9606`, tracks
  `<assembly>-<Class>` (98 of them). JBrowse 2 accepts that name, with its spaces and colon, as long as the tool
  URL-encodes it, which it does (`assembly=rdfc2im%3A%20113%20gene...`); nothing needs to change in the title. A short
  title would be tidier (HumanMine's is `humanmine-9606`).
* the tool: `jbrowse2Url` is `/jbrowse2/` (patch `jbrowse2-same-origin`, above); no `jbrowse2ConfigUrl`, the site's own
  `config.json` is the demo's.

Why local and not jbrowse2.intermine.org: the shared site's `config.json` knows only the public mines. Its
`jbrowse2ConfigUrl` parameter would take a config for the demo, but that config (and the mine it points at) would have
to be reachable from the browser as https (mixed content), and Chrome's Private Network Access rules apply to a public
https page reading `http://localhost`; none of that is needed when the viewer is on the BlueGenes origin.

JBrowse 1 (`bluegenes-jbrowse-tool`): HumanMine's `/api/tools/all` lists it (19 tools, 18 Nov 2026) but its Gene
report layout does not show it, and the layout `tools/apply_report_layout.py` applies (from
`curation/humanmine_bluegenes_properties.json`) has only the JBrowse 2 tool, so no JBrowse 1 container is run and the
tool stays installed, unpatched (`jbrowseUrl` `https://jbrowse.intermine.org/?data=`), outside the layout.
Without a `layout.report` property BlueGenes lists every installed tool, including that one, so re-apply the layout
after a rebuild (`python3 tools/apply_report_layout.py curation/humanmine_bluegenes_properties.json`).

mine-tests: `[mines.local-hybrid].jbrowse2` (`MINE_TESTS_HYBRID_JBROWSE2`, default
`http://localhost:15001/jbrowse2/`) drives `test_jbrowse2_iframe_loads` and `test_jbrowse2_site`.

## The report layout and HumanMine's templates [im-9n4.16]

Without a `layout.report` property BlueGenes puts every tool of a report page under "Visualizations", collapsed, and a
collapsed tool never runs. `--report-layout curation/humanmine_bluegenes_properties.json` makes phase `apply_templates`
(after the demo templates and the restart, default off) run two standard-library tools through the mine's web service,
as the superuser (`superuser@intermine.org`, the demo's password; `--user`/`--password` override), waiting up to 5 minutes
for the mine:

- `tools/apply_humanmine_templates.py curation/humanmine_templates.xml`: HumanMine's public templates, kept when every
  path (view, sort order, constraints, loop paths, joins, subclass constraints) resolves in the mine's live
  `/service/model`; uploaded with `POST /service/templates` and tagged `im:public` (`POST /service/template/tags`). A name
  the mine already serves is left alone (the demo's nine, which Cypress specs and `mines.toml` count on, and earlier
  runs), so this adds to `demo_public_templates.sql` and does not replace it. Dropped ones are printed with the first
  path that fails.
- `tools/apply_report_layout.py curation/humanmine_bluegenes_properties.json`: HumanMine's Gene categories and order,
  keeping a class entry when `Gene.<name>` is a collection or reference in the model, a tool when BlueGenes lists it
  (`/api/tools/all`), accepts Gene, the classes it depends on are in the model and the paths it queries resolve
  (`TOOL_QUERIES`: the Cytoscape tool needs `Gene.interactions` and its query fails with a 400 without it), a template
  when the mine serves it;
  the rest are printed with the reason, and a category left empty goes. It sets `layout.report` (`POST` the first time,
  `PUT` after) and reads it back; a second run changes nothing. `--dry-run` prints without writing. Run it again after a
  build that loads more data: the dropped list shrinks.

Both read HumanMine's own responses, kept as reference input (fetched 2026-11-18, read-only, one request each):
`curation/humanmine_bluegenes_properties.json` is `/service/bluegenes-properties` of www.humanmine.org and
`curation/humanmine_templates.xml` is `/service/templates?format=xml` (its production templates live in its userprofile
database; the humanmine repository's `default-template-queries.xml` holds three). The property and the templates are in
the mine's userprofile database, so a rebuild removes them until `--report-layout` is passed again.

`--tools-url URL` (or `REPORT_LAYOUT_TOOLS_URL`) names the BlueGenes whose `/api/tools/all` the layout is checked against
[im-9n4.34]. The default is the stack's own BlueGenes (`http://localhost:$BG_PORT`), which has no patched tools, so every
tool was dropped from the layout of the ut demo; give it the front, `--tools-url http://localhost:15001`. After a rebuild
that is meant to show JBrowse 2, `trial/front/gen-jbrowse-config.sh` regenerates the JBrowse 2 config from the mine.

## Genomics England gene lists, and where `apply_public_lists` calls them [im-9n4.21]

`tools/panelapp_lists.py` (USAGE.md, "Genomics England gene lists") makes HumanMine's `PL_GenomicsEngland_GenePanel:<Panel_name>`
lists from the PanelApp. It reads the PanelApp and, in `resolve`, a mine's `/service/ids` (a read-only job); it never
writes to a mine. Phase `apply_public_lists` (T2.3, next section) does the writing with `tools/apply_public_lists.py`,
which imports this tool's code. What T2.2 planned for it was:

```
python3 -m rdfc2im cache restore panelapp $RAW_CACHE_DIR/panelapp-data    # or: tools/panelapp_lists.py fetch --out DIR
python3 tools/panelapp_lists.py lists   --in DIR --out $WORK/lists --mine $MINE
python3 tools/panelapp_lists.py resolve --in DIR --mine $MINE --out $WORK/resolve.json      # the unresolved report
# then, per $WORK/lists/index.json entry with genes > 0, as the superuser:
#   POST $MINE/service/lists?name=<name>&type=Gene&description=<description>&tags=Genomics England gene panel;im:public
#        &extraValue=H. sapiens&replaceExisting=true      (Authorization: Token ...; body text/plain, one identifier per line)
```

What the upload needs to know (read from the web service code, `ListUploadService`/`ListInput`; not yet exercised):

* `replaceExisting=true` deletes a list of that name first, so a re-run replaces and does not duplicate; without it an
  existing name is a 400. `tags` is semicolon-separated; the `im:` tag needs the superuser. A list that came out of a
  name change (`replaces` in the list definition) is retired by deleting the old name (`DELETE /service/lists?name=`).
* The upload treats identifiers like `/service/ids` does: a match on a key field is added; a match that the service
  files under an issue (a synonym match, `OTHER`; a gene matched twice, `DUPLICATE`) is *not* added unless the request
  says `add=OTHER` (and so on) and is returned as unmatched. Measured on the demo mine (18 Nov 2026): every HGNC id
  resolves as `OTHER` ("searching synonyms for all types"), every Ensembl GRCh38 id as a `MATCH` (`secondaryIdentifier`),
  symbols mostly `MATCH`. So upload either Ensembl ids (one gene each, 4,307 of 4,308 distinct genes; RMRP's differs in
  the mine) or, per gene, the Entrez `primaryIdentifier` that `resolve` chose (`resolve.json.genes.tsv`, all 4,308),
  which should be a key match and need no `add` (not tested: nothing was uploaded). Do not upload symbols: 29 gene entries are ambiguous and 6 genes resolve to a
  different gene than the HGNC id names.
* Empty lists (panels with no Green gene) cannot be uploaded; skip them (`index.tsv` has `genes` 0).
* The `--mine` option of `lists` reads `GET /service/lists` anonymously to mark lists the mine already has.

The cached group `panelapp` (`rdfc2im cache save panelapp DIR`) is `redistributable=false`. The PanelApp site says its
data is "publicly accessible ... also available for the scientific and clinical communities" and links Terms of Use
(`/media/files/GEL_-_PanelApp_Terms_of_Use_December_2019.pdf`, on `prod-media-panelapp.genomicsengland.co.uk`), but the
sandbox's firewall blocked that host, so the terms themselves were **not read**, and the API's OpenAPI document names
a terms URL (`/policies/terms/`) that answers 404. Nothing states a rate limit. Until someone reads the PDF, the group is
kept out of release assets (`cache check-release` reports it) and `panelapp` is not on `RELEASE_ALLOWED_UNFLAGGED`.

### `apply_public_lists`: the lists on the mine [im-9n4.22]

`--public-lists DIR --public-lists-archive DIR2` (`DIR` is the PanelApp cache group, `DIR2` the archive repository, a
`historic_artefacts` checkout with `scripts/`) makes phase `apply_public_lists` run, once, after `apply_templates`:

```
python3 tools/apply_public_lists.py --mine http://localhost:$MINE_PORT/humanmine --panelapp-cache DIR \
    --legacy curation/public_lists --archive-repo DIR2 --select all --keep-2021-names --report $LOG_DIR/public-lists-$RUN_ID.json --wait 300
```

Without the flag the phase logs that it did nothing, and every other phase is as before. The web-service calls, as
exercised on the ut demo (superuser token from `POST /service/login`, `Authorization: Token ...`):

* **Upload**: `POST /service/lists?name=&type=Gene&description=&tags=a;b&extraValue=H. sapiens&replaceExisting=true`,
  `Content-Type: text/plain`, one identifier per line. The answer is `{"listId","listName","listSize","type",
  "unmatchedIdentifiers":[...],"wasSuccessful":true}`. 0.25 to 0.5 s for a panel list.
* **Replace**: `replaceExisting=true` deletes a list of that name first, then makes the new one under a temporary name and
  renames it; without it an existing name is a 400 ("Attempt to overwrite an existing bag"). A re-run therefore gives
  new list ids and never a second list of the same name.
* **Tags and description**: `tags` is split on `;`; `im:public` (and any `im:` tag) needs the superuser, who is the owner,
  so the list is public at once. `description` is taken as given (a newline, `;`, quotes and `&` survive a round trip).
* **Names**: no character is refused. `:`, `/`, spaces, commas, `&` and brackets worked and read back unchanged (a legacy
  list is named `PL_Protein coding cancer genes containing probable driver mutations`). `panelapp_lists.py` still maps the
  one `/` of a current panel name to `_`, because BlueGenes puts the name in a URL.
* **Delete**: `DELETE /service/lists?name=` (400 "doesn't exists" for an unknown name). **Read back**: `GET /service/lists?format=json`,
  anonymous: the public lists, each with `name`, `type`, `size`, `description`, `tags`, `dateCreated`; a visitor and
  BlueGenes see exactly this.
* **Identifiers**: the Entrez `primaryIdentifier` of each gene as the mine resolved it (HGNC id, then Ensembl id, then
  symbol, as `panelapp_lists.py resolve`), so every identifier is a key match and nothing lands in `unmatchedIdentifiers`.
  On the demo every one of the 4,308 distinct Green genes resolved: 4,307 by HGNC id, one (RMRP) by Ensembl id.

What it does, in order:

1. **Archive first.** The mine's current public lists go to `<archive>/<mine-label>-public-lists/<YYYY-MM-DD>[-N]/` with
   the T2.1 script, `historic_artefacts/scripts/export_humanmine_public_lists.py`, imported (not copied; its 0.3 s pause is
   switched off for a local mine). The label is the last part of the mine URL (`humanmine`; `--mine-label` overrides it:
   give a demo a label of its own so that its archive is not taken for HumanMine's). A directory is created, never reused:
   the same day again is `-2`, `-3`. A mine with no public list gets an empty dated record (`lists.json` with no lists), and
   the run goes on. If the export fails or does not add up (a `MISMATCH` in its log, a missing member file) the directory
   keeps a `FAILED.txt`, and the run stops before it logs in. The tool adds `archive.json` (mine, date, count). The script's
   own `--help` text says it takes a service URL and an output directory; nothing in it had to change.
2. **Resolve and upload** the lists below, as the superuser; **read every list back** and print a table (name, type, size,
   expected, public, ok): size, type, tags and description must be what was sent, once.
3. **Remove stale lists**: a list that is public, named `PL_...` and tagged `Genomics England gene panel`, which this
   run does not produce (a retired panel, a panel renamed with `--current-names`, a narrower `--select`). Printed and
   in the report; nothing else is deleted.
4. A JSON **run report** (`--report`): the archive path, every list uploaded with its size, members in and unresolved
   members, the skipped lists with the reason, the lists removed, the read-back result.

Which lists:

* **PanelApp**: all 433 current panels, Green genes only, the panel version in the description, then the
  Genomics England attribution and usage limits (`ATTRIBUTION_TEXT` in `tools/panelapp_lists.py`: content authored by
  Genomics England and its contributors, PanelApp Terms of Use December 2019 s.1.4; non-commercial use only, not for
  diagnostic use or medical decision-making, s.1.1). The 13 other lists do not carry it. 8 panels have no Green
  gene and are skipped and reported (a list cannot be empty): Familial Neural Tube Defects, Testicular cancer pertinent
  cancer susceptibility, PHACE(S) syndrome, Ultra-rare undescribed monogenic disorders, Undiagnosed monogenic disorder
  seen in a specialist genetics clinic, Lung cancer pertinent cancer susceptibility, Juvenile dermatomyositis, Severe
  familial anorexia: 425 lists. `--public-lists-select 100k` is the 175 panels of HumanMine's 2021 scope.
* **Names**: the 17 panels renamed in PanelApp since 2021 keep the **2021 list name** (the name BlueGenes and users of
  the lists know) and the description says `PanelApp now names this panel "<current name>"; the list keeps the name it had
  in 2021.` (before the attribution). One switch: `--keep-2021-names` (default; `KEEP_2021_NAMES_DEFAULT` in the tool) or `--current-names`
  (`--public-lists-names 2021|current` in `full-build.sh`). Flipping it renames those 17 lists: the old names are public
  `PL_` panel lists the run no longer produces, so they are removed.
* **The 13 other HumanMine lists** (`curation/public_lists/`, from the 17 November 2026 archive; its README has the
  provenance): each with its original name, description and tags. The members are the archived identifiers (Entrez ids,
  UniProt accessions, SNP ids) and count only if the mine matches them to one object by a key field, the test the upload
  applies. A list that resolves partly is uploaded with ` [Note: this mine holds N of the M members of the original
  HumanMine list.]` appended; one that resolves to nothing, or whose class the model lacks, is skipped. On the ut demo
  12 of 13 resolve whole (the two Protein lists too) and `PL_T2DcandSNPs_Voight2010` holds 2 of 29 SNPs.

**A mine rebuild wipes the userprofile database**, and the lists live there: after a rebuild the phase has to run again
(`--public-lists`). `--from apply_public_lists` re-runs only it. The first run after a rebuild archives an empty mine.

**Production guard.** `--mine` on a host that is not local or private (`www.humanmine.org`, anything `*.org` or public)
is refused unless `--i-know-this-is-production` is given. Local means `localhost`, `127.0.0.0/8`, `::1`, private
addresses, `host.docker.internal`, single-label names (a compose service) and `.local`, `.internal`, `.localhost`, `.test`
and `.lan` names. `full-build.sh` only ever passes `http://localhost:$MINE_PORT/humanmine`.

Timing on the ut demo (4,308 genes, 438 lists, 35,670 members): 13 s to resolve everything, about 2.5 minutes in all for
a run, the archive of 438 lists included. `GET /service/lists` with 438 public lists: 270 KB, 70 ms. The BlueGenes lists
page shows the first rows 0.3 to 0.6 s after load (22 pages of 20).

## Data-source status pages [im-9n4.42]

`--source-pages DIR` adds a last phase, `write_source_manifest`, after `verify`: `tools/source_manifest.py` writes the build
manifest `out/_mine/source_manifest.json` and `tools/source_pages.py pages` turns it into one Markdown page per source plus
an index `README.md` in DIR. For the demo the pages are committed to the humanmine repository (gmicklem/humanmine,
`docs/data-sources/`), where GitHub shows them as they are. Without the flag the phase list and every phase's dry run are
as before. USAGE.md, "Data-source status pages", has the commands and the mapping file format.

Where each value of the manifest comes from:

| Value | Stock source | RDF source |
|---|---|---|
| URL | `stock_sources.yaml` `files[].url` (and the raw group's `url.<id>`) | the endpoint and `FROM` graphs of `out/<src>/queries/*.sparql` |
| release / version | what the file states (`release:` probes in the mapping file: GAF `!date-generated`, GFF `#!annotation-source`, IntAct `releaseDate`, the BioGRID member name, the OBO `data-version`, Orphanet `JDBOR version`, HPO `#version`, the GTEx URL) | not in the SPARQL results |
| Last-Modified | the raw group's `META.json` `last_modified.<id>` (what the server sent at the download) | none |
| fetched at (UTC) | the raw group's `saved_at` (written right after the download) | the cache group's `saved_at` |
| size, sha256 | the cached raw file (sha256 computed, cached by path, size and mtime) | each cached TSV |
| licence (name, status, URL, date read, wording, conditions), redistributable | `stock_sources.yaml` (stock reactome: `other_licences.yaml`) | `sources.yaml`: the upstream's licence and `rdfportal_licence` (RDF Portal's own data set page); docs/LICENCES.md [im-9n4.45] |
| scope | `idsets/idsets.json` (panel size), `--gene-identifiers` | the cache group's `scope` (none, panel, full, pmid) |
| filter | `stock_sources.yaml` `filter`, in one sentence | none (the SPARQL query is the cut) |
| records read, kept | `field_counts.py` over the raw file and over the filtered file the loader read, with `subset_raw.py`'s record definitions; the filter's own JSON line from the build log as `filter_log` where the log has one | rows per cached table |
| objects loaded | the mine: one count query per class (with a `dataSets` collection) and data set | the same, plus objects per class in the items file |
| field counts | `field_counts.py` over the whole raw file and the filtered file | the cached extract's columns; `--endpoint-counts` for the whole endpoint |

What was missing, and how the build now captures it: the filter statistics (`subset_raw.py filter`'s JSON line) were only
in the log of the build that cut the file, and a build that restores the filtered group from the cache prints none. Rather
than change `subset_raw.py` or the cache metadata, the manifest counts the records of the raw file and of the filtered file
itself, with the same record definitions, so every build has them (a GAF row: 906,445 read, 9,121 kept); the log's line, when
present, is kept beside them. The release a file states was recorded nowhere; it is now read from the file. Objects loaded
per class and data set were never recorded; `--mine` adds them.

DataSet links: `--data-set-links URL` makes `prepare_mine_checkout` write `$RDFC2IM_DATA_ROOT/rdfc2im/_data-set-links/data_set_links.xml`
(one DataSet item per data set the selected sources write: `name`, `url` = URL/`<kind>-<source>.md`, `description`) and
add a last source `data-set-links` (type `humanmine-items`, which keys DataSet on `name`) after the trimmed project.xml's
others, with `DataSet.url = data-set-links, *` and `DataSet.description = data-set-links, *` in the priorities. No Java
change: HumanMine did the same with its `humanmine-static` source and a `datasets.xml` (that source in
humanmine-bio-sources is only keys and `have.file.xml.tgt`; the datasets.xml repository is lost). In this build no loader
sets DataSet.url or description (the demo mine's 30 data sets have neither), so nothing is overwritten. The data set names
come from the stock mapping files (`data_sets`, read from each converter) and `sources.yaml` (`data_set_title`).

## Watching a build

Every log line goes to the terminal and to `.build-logs/build-<run-id>.log` (in the repository,
gitignored; override with `LOG_DIR`), timestamped
and tagged with the current phase. Alongside it the script writes `build-<run-id>.status` (one
line: the current phase) and `build-<run-id>.timing.tsv` (one row per completed phase).

```sh
tail -f .build-logs/build-*.log                           # raw
tools/watch-build.sh                                      # per-phase dashboard
```

`tools/watch-build.sh` reads only those files and the phase order from `full-build.sh
--list-phases`, so it cannot drift from the build or affect it. It takes `--run-id`, `--once`
and `--interval N`. Because the logs live in the repository, the same command works from a host
terminal watching a build that runs in a sandbox sharing the checkout. If the build used a
different `LOG_DIR`, set the same one when you watch.

Every run ends by printing its own phase timings, longest first.

## Time and resources

### Timings

These are real numbers from 2026-09-21, from a run whose Maven, Gradle and Docker caches were
already warm. **A first-ever run is substantially slower**, because phases 2, 5, 6, 13 and 14
are then downloading the upstream checkouts, the Gradle wrapper distribution, the InterMine jar
tree, BlueGenes' 178 jars and four Docker images rather than finding them cached.

The mine build and load, `--from prepare_mine_checkout` through `verify`, took **4 minutes**
end to end (`build-20260921T134218Z`):

```
125s  integrate_sources
 68s  postprocess
 17s  build_dbmodel
 12s  build_webapp
  7s  verify
  4s  stage_artifacts
  1s  each: start_databases, start_mine_stack, resolve_bluegenes_deps, apply_templates, check_prereqs
  0s  stage_src_data, prepare_mine_checkout
```

On the first full-scale integrate of all ten sources the same two phases took 234 s and 176 s
respectively - `integrate_sources` and `postprocess` dominate in every run.

`rdfc2im_pipeline` (phase 3, the RDF extraction) is the other big one, and is almost entirely
time spent waiting on remote SPARQL endpoints. From the run that exercised it, eight of the nine
sources took **10 min 24 s** between them, with `pubmed`'s PMID-scoped fetch on top - call it
about a quarter of an hour:

```
clinvar      4m39s        reactome     1m13s        ncbigene       20s
gwascatalog  1m15s        go           1m03s        ensembl         8s
uniprot        56s        hgnc           50s        pubmed       (varies with the cited-PMID set)
```

### A second, from-scratch run

Run on 2026-09-21 in a sandbox whose only carry-over was the repository and the package caches.
It reached `verify` after **ten** fixes, each with a test that failed beforehand
(`make test`: 108 passed / 6 failed at the start; 152 passed / 17 skipped at the end), and the
result passed all 17 checks of `make test-live`: 113 genes, 2,883 pathways, 50,283
pathway-protein rows, 450 gene-pathway rows. Phase timings from the runs that completed them:

```
530s  rdfc2im_pipeline    (network: 9 sources, 10 min)      75s  postprocess
233s  integrate_sources                                       29s  resolve_bluegenes_deps
 15s  build_dbmodel        11s  build_webapp                   8s  verify / 8s fetch_inputs
```

What it found - most of it invisible to every earlier run, because those had been run once and
then resumed, or on a workspace already in the right state:

- **Copying on the workspace mount.** `make-inputs.sh` died in phase 2 twice: `cp -r` of a clone
  failed on its read-only `.git` pack, and its replacement `tar | tar` failed with "Directory
  renamed before its status could be extracted". It now copies through `tools/copy_tree.py`,
  which re-reads what it wrote.
- **`rdfc2im fetch` exited 0 when queries failed**, so a missing or truncated table went on to
  the mine (and would have been cached). It now exits 1.
- **`--sources` did not reach `rdfc2im project`**, so stale derived output from sources nobody
  asked for (six, in this workspace) landed in `project.xml` and the mine's model.
- **`Gene.pathways` without its `Pathway.genes` end** made phase 5's isolated `mergeModels` fail;
  `rdfc2im check` now flags any reverse-reference whose other end is missing.
- **Link fields were never carried**, so `Protein.keywords` (declared by the stock uniprot
  source that a reduced mine drops) did not exist when uniprot loaded. The general fix replaces
  three earlier hand-patches (`Protein.ecNumbers`, `Allele.diseases`, `Pathway.dataSets`).
- **A stale generated model looked like success.** Gradle called `:dbmodel:builddb` up to date
  after the loader jar's *content* changed, so a resume kept the old model. Phase 10 now deletes
  `dbmodel/build` first.
- **The first `:webapp:war` of a fresh checkout deleted its own `web.xml`** (Gradle's stale-output
  cleanup on a task with no history), and passed on the second try. Phase 13 now runs
  `copyWebappContent` once first.
- **Test tooling:** `make test` ran the live tests against any mine that happened to be
  listening, and `make` re-ran failed tests under a runner that cannot skip.

Reusing the fetched data: the same phase 3 with `--use-cached-data` took **73 s instead of 530 s**,
made no network requests, and produced items files byte-identical to the fresh fetch's (all nine).

### A third run: one command, start to finish, entirely from the cache

Every run above was assembled from `--from`/`--only` segments, resumed after each fix - useful for
isolating a bug, but not proof the *whole* script runs clean in one go. On 2026-09-22, a single
`tools/full-build.sh --use-cached-data` (no `--from`/`--only`, a brand new `TRIAL_HOME`) went from
nothing to a verified mine in **12 min 5 s**, all fetched data restored from `cached_raw_data/`
with no network requests beyond `fetch_inputs`' git pulls and the live model, and passed all 17
`make test-live` checks with the same counts as the from-scratch run above:

```
354s  postprocess           24s  build_dbmodel          3s  stage_artifacts
229s  integrate_sources     14s  build_humanmine_items   2s  start_mine_stack
 64s  rdfc2im_pipeline       9s  build_webapp             1s  each: build_reactome_source,
 12s  fetch_inputs           6s  verify                     resolve_bluegenes_deps, start_databases
  4s  rdfc2im_project        1s  prepare_mine_checkout      0s  each: check_prereqs, stage_src_data,
                                                               apply_templates
```

One real bug surfaced getting here, worth recording because it can recur whenever a cache's `--meta`
contract changes: `cached_raw_data/reactome-uniprot-map/` had been saved by an earlier commit,
before `--meta levels=...` existed. The very first single-command attempt died in phase 6 -
`rdfc2im cache: reactome-uniprot-map: cached data was fetched for levels=None, but this build needs
levels='default' - refusing to restore it` - correct behaviour (the recorded meta genuinely didn't
say what level it was), but with no migration path for a cache saved before the key existed. Since
`cached_raw_data/` is gitignored and local to each sandbox, this cannot affect a fresh clone (every
future save already includes `levels`) - only this one already-fetched entry needed a one-time fix:
its `META.json` was hand-edited to add `"levels": "default"`, true of the data it actually held (its
own recorded `url` ends in `UniProt2Reactome.txt`, the default file), then `rdfc2im cache verify`
confirmed the entry still checksums correctly before trusting it.

### A fourth run, same day, warm caches

Immediately after the run above, another single `tools/full-build.sh --use-cached-data` (fresh
`TRIAL_HOME` again, same sandbox) went from nothing to a verified mine in **5 min 18 s** - about
44% of the third run's time - with zero fixes needed. The difference is caches, not the script:
the Docker images, the Gradle 4.9 dependency cache (`~/.gradle`) and the JDK were already warm from
the run immediately before it, whereas the third run's 12 m 5 s included their one-time download
cost. Slowest phases: `integrate_sources` 109 s, `postprocess` 67 s, `rdfc2im_pipeline` 57 s (all
nine sources restored from `cached_raw_data/`), `build_dbmodel` 14 s; everything else finished in
9 s or less. All 17 `make test-live` checks passed again.

One thing this run's cleanup surfaced, worth recording since it looks like success but isn't:
`gradle --stop` (the standalone Gradle 4.9 launcher, not a project's own `./gradlew`) printed "1
Daemon stopped" and exited 0, but the daemon process (`ps aux | grep GradleDaemon`) was still
running several seconds later and did not respond to `kill` (`SIGTERM`) either - only `kill -9`
actually ended it. If you need a build's Gradle daemon gone (freeing its ~4 GB heap, or before
removing the `TRIAL_HOME`/launcher it was started from), verify with `ps`, don't trust the exit
code.

### Disk

Budget **5 GB**, and leave real headroom on whichever filesystem holds `/var/lib/docker`.
Measured after a complete build:

| | |
|---|---|
| `in/.upstream` (upstream checkouts) | 150 MB |
| `out/` (generated items, TSV, queries) | 257 MB |
| `trial/artifacts`, or `$TRIAL_HOME/artifacts` per named stack (exploded war + BlueGenes jars) | 177 MB |
| `$TRIAL_HOME` (mine checkout, bgdeps, logs) | 264 MB |
| `/micklem` (staged source data) | 42 MB |
| Docker images (postgres 14, solr 8.6.2, tomcat 8.5, temurin 17) | ~2.5 GB |
| Docker volumes (`rdfc2im-pgdata`, `rdfc2im-solrdata`) | 1-1.6 GB |

### Memory

Peak around **9 GB of 15 GB** during `integrate_sources`. The Gradle daemon is given 4 GB, the
Tomcat container 3 GB (`-Xmx3g`), and Postgres runs with `max_connections=2000` - InterMine's
XML loader opens far more concurrent connections than you would expect, and the long-lived
Gradle daemon does not appear to release them between per-source `integrate` invocations.

## Verifying the result

`phase_verify` only checks that the three services answer. The real check is:

```sh
make test-live
```

`tests/test_live_mine.py` asks the running mine real questions - autocomplete populated for
Gene and Protein, keyword search returning a real panel gene, a panel-sized Gene table (not
~193,000 genes, which is what the full-vs-panel scope bug looked like), cross-source identifier
merge on one gene, `Pathway` → `Protein` participants and `Gene.pathways`, the organism's names
(`Homo sapiens`, `H. sapiens`, `Homo`, `sapiens`), one data set per pathway, one `Chromosome` per
chromosome number with its organism, and the classic UI's webconfig validity. Each check is anchored to a specific bug found on 2026-09-21 and named in
its docstring.

This suite exists because of the failure mode this project kept hitting: **a step that reports
success while silently doing nothing.** A Gradle task returning SUCCESS having indexed nothing;
a source postprocessor whose failure `PostProcessPlugin` catches, prints as one line, and
carries on from with exit code 0; an `integrate` loop whose regex silently skipped the stock
reactome source entirely, so nine sources loaded cleanly and reactome's data simply never
arrived. None of those are visible to an offline test, and several of them survived every
dry run. The live tests are opt-in - `make test-live` sets `RDFC2IM_LIVE=1`, and they skip if no
mine is reachable - so plain `make test` stays green offline and ignores a stale mine left
running from an earlier session. Point them elsewhere with
`MINE_BASE=http://host:8090/humanmine SOLR_BASE=http://host:8983 make test-live`.
The live tests need `lxml`: `make` uses `/home/agent/venvs/mine-tests/bin/python` when that venv
exists (the sandbox's), else `python3`; `make test-live PY=/path/to/python` overrides it.

Then look at it: `http://localhost:8090/humanmine` (classic UI, with the demo templates on the
home page) and `http://localhost:5000` (BlueGenes).

## Troubleshooting

**`FATAL: JAVA8_HOME not set and no JDK 8 found under /usr/lib/jvm`** - exactly what it says,
and it aborts in phase 1 before any work. Install `openjdk-8-jdk-headless`, or set `JAVA8_HOME`
if your JDK 8 is somewhere non-standard. If you get past this phase but a Gradle call later
reports it cannot start a daemon, you are running Gradle 4.9 under a newer JVM anyway - check
that `JAVA8_HOME` really points at an 8.

**`FATAL: no .venv at ... - create one with pyyaml+lxml first`** - see Prerequisites. The venv
must be at the repository root.

**`/service/model` shows `"term": ""` on some classes (GWAS, GWASResult, GOTerm, Disease, ECNumber,
PathwayReaction on the demo mine).** The model is generated at build time, so a mine only drops
those blank class terms (im-jqz.58) after it **rebuilds `bio/model`**: `publish_intermine` with
`--intermine-src`, then `build_dbmodel`. Upgrading or restarting the webapp does not change them.
The data is unaffected.

**`Web config contains a bad path!` / `PathException: ... GWAS.firstAuthor` in the mine log
(thousands of lines, one per summary request).** `webconfig-model.xml` still names a field the
reduced model lacks (`GWAS.firstAuthor`, `GWASResult.study.firstAuthor`: the GWAS Catalog has no
author, see `accepted_gaps` in `rdfc2im/data/sources.yaml`). The template SQL is not the cause;
`tests/test_templates_model.py` checks `curation/demo_public_templates.sql` against the model.
`tools/reduce_mine.py webconfig` now drops such `fieldconfig` entries (im-ore.22; before, it looked
for a `<classes>` wrapper the file does not have and checked nothing). A running mine keeps the old
file until `build_dbmodel` and `build_webapp` run again and the webapp is restarted.

**Gradle appears to hang during `integrate_sources`, CPU pinned, no log output.** That is the
OOM death-spiral: an `OutOfMemoryError` in a background prefetch thread that the daemon never
surfaces. Check `~/.gradle/gradle.properties` actually contains
`org.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8`. The script only writes that file if it has
no `org.gradle.jvmargs` line at all, so a pre-existing line with a smaller heap is left alone
and is the thing to fix.

**`invalid byte sequence for encoding UTF8: 0x00` during reactome's load** - the same file, the
`-Dfile.encoding=UTF-8` half. See Prerequisites.

**Postgres dies mid-build and will not restart; `No space left on device` in its log.** The
Docker filesystem filled. This happened for real on 2026-09-21: an invalid `webconfig-model.xml`
made every classic-UI page log a full Struts/Tiles stack trace and every failing DWR call log
another, Tomcat's logs in the `rdfc2im-mine` container reached 3.5 GB
(`localhost.<date>.log` 2.3 GB, `ddi-ws.log` 1.3 GB), `/var/lib/docker` hit 100%, and Postgres
died mid-WAL-redo and could not come back until space was freed. Both causes are now fixed -
`reduce_mine.py webconfig` trims the widgets that cannot resolve, and
`/usr/local/tomcat/logs` is a 512 MB tmpfs so an error storm fails at the cap instead of eating
the host disk - but the log directory is still the first place to look if the mine starts
misbehaving:

```sh
docker exec rdfc2im-mine du -sh /usr/local/tomcat/logs
docker exec rdfc2im-mine ls -lS /usr/local/tomcat/logs | head
df -h /var/lib/docker
```

Those logs are deliberately not durable across a container restart.

**Every request 500s with `ContextNotInitialisedException`, however long you wait.** The
userprofile database has no schema, so the webapp's `ActionServlet` never initialises
(`userprofileOSW is null`). `:dbmodel:buildUserDB` is a separate task from `:dbmodel:builddb`;
re-run `--only build_dbmodel`.

**The webapp deploys, Tomcat logs success, and every request 404s.** The war was built without
`WEB-INF/web.xml`, so it has no servlet mappings and nothing logs an error.
`phase_prepare_mine_checkout` patches `webapp/build.gradle` to fix this; if you are working from
a hand-made checkout, that patch is the thing to reproduce.

**Phase 2 (`fetch_inputs`) dies copying a clone: `cp: failed to extend ... .git/objects/pack/...:
Permission denied`, or `tar: .: Directory renamed before its status could be extracted`.** You are on
a virtiofs-backed workspace mount, where `cp` and `tar` are not trustworthy for trees. `make-inputs.sh`
no longer uses either - it copies through `tools/copy_tree.py`, which re-reads and compares every file
- so this means an older copy of the script. If you write your own copy step on such a mount, do the
same; see `RESTART.md`.

**`--use-cached-data` stops with `cached data ... refusing to restore it`, `... is corrupt in the
cache`, or `no cached data for ...`.** Working as intended: the cache was fetched for a different gene
panel, taxon, scope or `--reactome-levels` than this build needs, a cached file no longer matches its
`MD5SUMS`, or nothing was cached yet. `python3 -m rdfc2im cache list` and `cache verify` show what is
there. Run once without the option to fetch afresh (which re-saves) - or, if the entry's actual data is
right and only its recorded `META.json` predates a newer `--meta` key rdfc2im/rawcache.py now checks
(confirmed live for `levels`, see "A third run" above), edit `META.json`'s `meta` object by hand to add
the missing key with its true value, then confirm with `cache verify` before trusting it.

**`--offline` stops with `OFFLINE=1 and no clone .../in/.upstream/rdf-config`.** The upstream clones are
not in `cached_raw_data/`. Run once with `--use-cached-data` (or with neither option) to make them, then
`--offline` works. A CI runner that has the network should use `--use-cached-data`, not `--offline`.

**`--use-cached-data` stops with `no cached data for gene-id-lookup` or `humanmine-model`.** The cache
was filled before those two entries existed. Add them without re-fetching the sources: run
`tools/full-build.sh --only fetch_inputs` (no `--use-cached-data`; it saves the model), and for the
lookups
`RDFC2IM_RESOLVER_CACHE=/tmp/lookup python3 -m rdfc2im translate --source ncbigene --source ensembl --taxon 9606 --genes @curation/demo_gene_panel.txt`
followed by `python3 -m rdfc2im cache save gene-id-lookup /tmp/lookup --meta taxon=9606 --meta genes_md5=$(md5sum curation/demo_gene_panel.txt | cut -d' ' -f1)`
(the `--meta` keys are the ones `lookup_meta` in `tools/full-build.sh` uses).

**Something reported success but the data is not there.** Assume this is happening rather than
assume it is not - it was the single most common failure of the first real build. Run
`make test-live`, and check the claim directly with a query or a row count before believing it.

**Resuming.** Fix the cause, then `tools/full-build.sh --from <phase>`. The phases are designed
to be resumable: the reactome data download, the upstream checkouts and the mine checkout copy
are all skipped when already present.

## What the demo mine does not have

Checked on the maint-2026 (6.0 line) testbed stack, 16 Nov 2026.

- **GO annotations, so no GO enrichment widget.** `go_enrichment_for_gene` is in HumanMine's
  `webconfig-model.xml` but is dropped by `tools/reduce_mine.py webconfig` (build log:
  `dropped ... go_enrichment_for_gene`): its paths (`goAnnotation.ontologyTerm.parents...`) go through
  `GOAnnotation`, a class of the `go-annotation` source, which this mine does not load, and the
  mine holds no annotation at all (`ontologyannotation` has 0 rows, 78,100 `GOTerm`s). The `go`
  source loads the ontology only; the UniProt `core:classifiedWith` GO column is `todo`
  (SPEC-DECISIONS.md D4) and is not even fetched. Adding the widget takes: a UniProt SPARQL table of
  protein-to-GO links (a new fetch, so `cached_raw_data/uniprot` and the CI release asset must be
  regenerated); `items.py` synthesising the intermediate `OntologyAnnotation` item (subject = the
  gene or protein, `ontologyTerm` = the `GOTerm`, one item per pair, keyed on both - the one-hop
  `via` cannot express it); the GO term closure in `GOTerm.parents` (the widget enriches on
  `parents`, so the `go` table must carry the transitive closure or a postprocess must fill it);
  and the widget's paths rewritten from `goAnnotation` to `ontologyAnnotations` (the 6.0 model has
  `OntologyAnnotation`, not `GOAnnotation`) with the genes reached through their proteins.
- **Location and Sequence objects** (without `--stock-sources ... ncbi-gff`, which loads locations,
  transcripts, exons and chromosome lengths, and `--with-genome-sequence`, which adds sequence: see
  "Locations and gene models" above). Chromosomes exist, one per chromosome now (the sources name
  them by number alone; `items.py` gives each the organism of its genes, which is what InterMine
  keys one on), but they have no length, and no `Location` (`location` has 0 rows) or `Sequence`
  exists. The 23 Cypress skips for region search and sequence export wait on this. Locations need
  coordinates the pipeline never fetches: the Ensembl RDF carries FALDO positions
  (`knowledge.yaml` has the `faldo:position` row, status `todo`), but the `ensembl` queries do not
  ask for them (a new location table, so a new fetch and a regenerated cache), then a mapping to `Location.start/end/strand` with
  `Location.feature` = the gene and `Location.locatedOn` = the chromosome, which needs an
  intermediate object like the GO annotation above. Chromosome lengths are in the cache
  already (`cached_raw_data/grch38-chromosome-lengths`, HumanMine's JBrowse `refSeqs.json`) but
  nothing in the pipeline reads them. Sequences are not in RDF Portal at
  all: `Gene.sequence` / `Chromosome.sequence` would come from a genome FASTA through the stock
  `fasta` source, and the `transfer-sequences` / `create-chromosome-locations-and-lengths`
  postprocesses need both. A contained change it is not: it is a new data source, a regenerated
  cache and an `items.py` feature, so it is left as a follow-up.

## The hybrid testbed in one command [im-9n4.19]

Two templates in `trial/` hold the recipe that built the milestone 1 hybrid mine ("ut" stack: stock HumanMine sources
plus the rdfc2im RDF sources, every human gene) so that it does not live only on one machine's scratch disk:

* `trial/fb-env-ut-hybrid.sh.example`: the environment (private `HOME`, `TRIAL_HOME`, JDK 8, Gradle 4.9, stock-data
  directories, the InterMine checkout, the RDF cache). The four lines under "Paths" are the only ones to edit.
* `trial/drive-ut-hybrid.sh.example`: the driver. It runs `tools/full-build.sh --only PHASE` for each phase in turn,
  with a memory gate (6 GB available) in front of the heavy ones, a disk check after each, a 15-second memory sampler
  and per-phase logs. Its header comment says what it builds and how to resume.

```sh
cp trial/fb-env-ut-hybrid.sh.example $D/fb-env-ut-hybrid.sh     # edit WORKTREE, D, INTERMINE_SRC and the cache path
cp trial/drive-ut-hybrid.sh.example  $D/drive-ut-hybrid.sh
bash $D/drive-ut-hybrid.sh                     # check_prereqs to verify, about 24 minutes warm
bash $D/drive-ut-hybrid.sh integrate_sources   # resume from a phase (earlier phases must have passed)
```

The driver finds its environment file by its own name (`drive-ut-NAME.sh` reads `fb-env-ut-NAME.sh`), so a copy for
another worktree is two `cp` commands and a different `NAME`/`WORKTREE`. What it passes to `full-build.sh` (without the
phase selection) is the one command:

```sh
tools/full-build.sh --offline --intermine-src $INTERMINE_SRC --stack-name ut \
  --stock-sources "uniprot uniprot-fasta uniprot-keywords ncbi-gff go-annotation interpro-go panther mgi-identifiers \
                   psi-mi-ontology psi-intact biogrid protein-atlas protein-atlas-rna gtex atlas-express \
                   hpo-annotation orphanet" \
  --report-layout curation/humanmine_bluegenes_properties.json --tools-url http://localhost:15001 \
  --sources "go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed hpo" \
  --cache-dir $RDF_CACHE_ALL_GENES --gene-identifiers all
```

`$RDF_CACHE_ALL_GENES` is the RDF cache of an all-genes build (the panel's release cache with the scope=full `ncbigene`
and `hgnc` groups: the asset `cached_raw_data_allgenes-*.tar.gz` holds exactly those two). `--tools-url` names the front
(`trial/front/`), whose BlueGenes lists the patched tools the report layout may keep. The front itself is not part of the
mine build; after a rebuild run `trial/front/gen-jbrowse-config.sh`.

## Milestone 1 build, 18 Nov 2026 [im-9n4.19]

The merged integration branch built from a clean start, from the caches only, with the command above.

**What "clean" meant.** A fresh `$TRIAL_HOME` (the old one moved aside, removed after the pass); empty Postgres and
Solr volumes (the ut containers stopped, their bind-mounted `volumes_ut` moved aside, so `start_databases` created the
three databases and two cores from nothing); the stock working directories derived from the caches (`subset`,
`unpacked`, `whole`, `idsets`, `resolver`) and the worktree's `out/` removed; the resolver cache in `$HOME` removed. Kept:
the caches themselves (`cached_raw_data.allgenes-*`, `stock_ut/cache`, `stock_ut/filtered-cache`), `in/.upstream` (the
upstream clones, which `--offline` needs), Gradle's dependency cache, the Docker images and the private Maven repository
that `publish_intermine` rebuilds. The `--offline` flag was on for every phase, `check_prereqs` to `verify`: none stopped
for want of the network. Only the data phases are *guaranteed* network-free (`RDFC2IM_OFFLINE=1`); Gradle, Maven and Docker
ran from warm caches and were not tried with the network cut.

**Found and fixed** (the first clean run passed every phase and still produced a mine whose autocomplete index was empty):

* `create-autocomplete-index` failed on `ProteinDomain.shortName`. `interpro-go` declares `ProteinDomain` without that
  field, and `reduce_mine.py objectstoresummary` trimmed only absent classes, so the stock line `ProteinDomain.autocomplete =
  name shortName` stayed. `AutoCompleter.buildIndex` threw, the Gradle task printed `POSTPROCESS create-autocomplete-index
  FAILED.` and exited 0, the phase passed, and 5 of the 56 `make test-live` checks failed. The previous build (im-9n4.40)
  has the same line in its log; it had been put right by hand. Now `objectstoresummary` also drops, from each `*.autocomplete`
  line, the fields the class lacks (and the line when none is left), and says so; `phase_postprocess` ends by requiring a
  non-empty `humanmine-autocomplete` core and stops the build otherwise. Test: `test_objectstoresummary_drops_autocomplete_fields_the_class_lacks`.

**Timings** (the driver's `phases.tsv`, run 2, which is the clean run with the fix; 10:00:44 to 10:24:34, **23 min 50 s**
wall; run 1, without the fix, took 24 min 38 s):

| Phase | s | Phase | s |
|---|---|---|---|
| check_prereqs | 0 | stage_src_data | 2 |
| fetch_inputs | 2 | start_databases | 7 |
| publish_intermine | 199 | build_dbmodel | 20 |
| rdfc2im_pipeline | 108 | **integrate_sources** | **781** |
| rdfc2im_project | 8 | **postprocess** | **191** |
| build_humanmine_items | 11 | build_webapp | 14 |
| build_stock_sources | 22 | resolve_bluegenes_deps | 4 |
| fetch_stock_data | 6 | stage_artifacts | 3 |
| subset_stock_data | 15 | start_mine_stack | 12 |
| prepare_mine_checkout | 1 | apply_templates / verify | 13 / 6 |

Integrate, per source (s): humanmine-ncbigene 163, humanmine-hgnc 153 (both every human gene), humanmine-clinvar 29,
psi-intact 28, humanmine-go 26, biogrid 26, humanmine-gwascatalog 23, humanmine-pubmed 23, humanmine-uniprot 22, go-annotation 20,
interpro-go 20, humanmine-hpo 20, reactome 19, hpo-annotation 17, panther 16, ncbi-gff 16, uniprot 14, protein-atlas 14, psi-mi-ontology 14,
protein-atlas-rna, atlas-express, gtex, orphanet 13 each, humanmine-ensembl 12, humanmine-reactome 12, ncbi-gff-lengths 12,
uniprot-keywords 12, mgi-identifiers 10, uniprot-fasta 7.

**Objects**: 1,120,120 in all (`intermineobject`). Per class: Synonym 232,023; CrossReference 221,697; OntologyTermSynonym
108,909; Gene 65,467 (64,470 human); Allele 59,031; GOTerm 48,348; GOAnnotation 40,516; InteractionDetail 37,826; Author
37,247; Publication 32,794; GWASResult 30,832; Protein 22,630; Interaction 22,351; HPOTerm 20,413; Location 16,603;
ProteinDomain 14,776; Disease 12,654; RNASeqResult 11,970; ProteinAtlasExpression 8,390; UniProtFeature 8,105; Exon 7,466;
MeshTerm 6,604; GWAS 6,175; Homologue 3,166; Pathway 2,883; AtlasExpression 1,824; CDS 604; MRNA 604; Sequence 254.

**Size**: Postgres 3.4 GB on disk (`humanmine-production` 2,188 MB; userprofile 11 MB; items 13 MB); Solr 299 MB (autocomplete
core 356,523 documents); `$TRIAL_HOME` 1.2 GB; stock raw groups 1.7 GB (psi-intact 1,013 MB, biogrid 199 MB, uniprot 167 MB,
mgi-identifiers 76 MB, ncbi-gff 75 MB, hpo-annotation 55 MB, orphanet 52 MB, go-annotation 15 MB, atlas-express 13 MB,
uniprot-fasta 8 MB, gtex 7 MB, panther 6 MB, protein-atlas 5 MB, protein-atlas-rna 5 MB, interpro-go 3 MB, psi-mi-ontology 0.7 MB;
resolver groups 10 MB) and filtered groups 397 MB (psi-intact 317 MB, biogrid 60 MB, uniprot 13 MB, ncbi-gff 4.7 MB, go-annotation
1.7 MB, the rest under 1 MB).

**Memory** (16 GB, no swap; `memlog.tsv`, every 15 s): lowest available during `integrate_sources` 6.3 GB (peak used 9.9 GB), during
`postprocess` 5.1 GB (11.1 GB used), overall lowest 5.0 GB at the start of `build_webapp`. The machine's other containers are
included in "used".

**Report page, PAX6 and CYP2D6 against public HumanMine** (counts of `Gene.<collection>` through the web service):

| Section | HumanMine PAX6 | This mine PAX6 | This mine CYP2D6 |
|---|---|---|---|
| goAnnotation | 79 | 57 | 33 |
| chromosomeLocation | 1 | 1 | 1 |
| exons / transcripts | 637 / 53 | 638 / 53 | 17 / 2 |
| introns, UTRs, CDSs | n/a | 0 | 0 |
| proteins | 5 | 47 (TrEMBL included) | 59 |
| protein sequences | 5 | 2 | 2 |
| homologues | 10 | 12 | 67 |
| pathways | 10 | 5 | 6 |
| atlasExpression | 376 | 16 | 16 |
| proteinAtlasExpression | 90 | 137 | 97 |
| rnaSeqResults | 97 | 105 | 105 |
| interactions | 156 | 361 | 4 |
| alleles | 522 | 996 | 356 |
| diseases | 8 | 15 | 1 |
| protein features / comments / publications | n/a | 62 / 15 / 39 | 97 / 9 / 25 |

HumanMine's own CYP2D6: 2 proteins, 22 domain regions, 96 UniProt features.

**Known gaps**, each with the nearest reference (this file and plan 50 name tasks and sections, not open beads; the orchestrator owns the bead ids):

* ArrayExpress tools (three of them, `atlasExpression.tStatistic`): the data is the owner's `/micklem` copy of E-MTAB-62 (plan 50, T1.9); the layout drops them and `test_tool_panels_match_reference` fails on them until the owner decides.
* Genome sequence: `--with-genome-sequence` (im-9n4.9) is off; `Chromosome.sequence` is absent and `test_reference_sequence_fetch` fails.
* CDS/UTR per gene: CDS and MRNA exist (604) but the gene collections `CDSs`, `UTRs`, `introns` are empty (the ncbi-gff loader, im-9n4.9).
* OMIM disease names: OMIM is licensed and kept out (plan 50 D-7, T1.10).
* RGD symbols: closed by im-9n4.35 (see "Partner genes and symbols"); the milestone build above did not have them. Its licence wording is still unverified.
* TrEMBL protein sequences: closed by im-9n4.32 (see "TrEMBL sequences from RDF" below).
* GTEx eQTL: only the median-TPM file is loaded; `Gene_SigSNP` is dropped from the layout (plan 50, T1.10 optional).

**Release assets** (prepared, not uploaded; the owner approves uploads): all three are checked with `python -m rdfc2im cache
check-release` on the extracted content.

* `cached_raw_data-2026-11-18b.tar.gz`: the panel cache with the `hpo` and `bluegenes-tools-patched` groups added (16 groups, top directory
  `cached_raw_data/`); restore with `tar -xzf` in the repository root.
* `stock_filtered-2026-11-18.tar.gz`: the 13 redistributable filtered stock groups under `filtered-cache/`, with
  `LICENCES-stock-filtered.txt` (as first prepared it said Human Protein Atlas was CC BY-SA 4.0 share-alike; that was wrong, the
  Atlas states CC BY 4.0. im-9n4.45 read every source's own licence statement: corrected text in `docs/LICENCES-stock-filtered.txt`,
  and the second pass (im-9n4.45, 18 Nov) read the terms of all but PANTHER: leave `stock-panther` out, the other twelve groups may be published with the notice; see docs/LICENCES.md, "Release assets"). Extract into the directory above `RDFC2IM_STOCK_FILTERED_CACHE`. Not in it: groups for whole-file
  sources (interpro-go, psi-mi-ontology, uniprot-keywords, orphanet), which stay raw groups in `stock_ut/cache`.
* `cached_raw_data_allgenes-2026-11-18.tar.gz`: the two RDF groups that differ in an all-genes build (`ncbigene`, `hgnc`, scope=full).
  `hgnc` holds HGNC's own `main_see_also_omim.tsv` (OMIM ids as HGNC publishes them, no OMIM data).
  Both are verified (NCBI: no restrictions; HGNC: CC0); the notice text is in `docs/LICENCES-panel-cache.txt`. That file is also
  the notice for the published panel cache (release `demo-data-2026-11-18`), which had none.

## TrEMBL sequences from RDF [im-9n4.32]

Until im-9n4.32 the RDF `uniprot` source loaded the panel's 1,547 UniProt entries (Swiss-Prot and TrEMBL, linked to
genes by symbol) without sequences; only the 114 Swiss-Prot canonical proteins (stock uniprot) and their 140 isoforms
(uniprot-fasta) had one, so the MSA viewer aligned two sequences for PAX6 (47 proteins) and CYP2D6 (59).

**What is loaded.** For each entry, its own canonical sequence: `rdf:value` -> `Sequence.residues` (linked by
`Protein.sequence`), `core:md5Checksum` -> `Sequence.md5checksum`, `core:fragment` -> `Protein.isFragment` ("single" or
"multiple" -> true; absent -> false, transform `default:false`), and `Sequence.length` / `Protein.length` = the number of
residues (`items.complete_sequences`: the RDF states no length). `core:mass` already gave `Protein.molecularWeight`.

* **Which sequence.** `core:sequence` names every isoform of an entry (P26367-1 `Simple_Sequence`, -2
  `Modified_Sequence` `basedOn` -1, -3 `Unknown_Sequence`) and, for P01308, another entry's canonical sequence
  (F8WCM5-1, typed `Simple_Sequence` and `External_Sequence`). The entry's own is the `Simple_Sequence` named
  `isoforms:<accession>-N`: sources.yaml `node_constraints` puts that type triple and a `STRSTARTS` filter inside the
  OPTIONAL that reaches the node. Exactly one per panel entry (1,547 of 1,547); it also gives P01308 one molecular
  weight instead of two (items conflicts 11 -> 10, the rest are `Protein.name`).
* **Predicates rdf-config's model lacks.** Its UniProt model gives a sequence node only `rdf:value`, `core:mass` and
  `core:name`; `core:md5Checksum` and `core:fragment` are added by sources.yaml `model_additions`
  (`rdfconfig.add_predicates`), then mapped in knowledge.yaml like any other row.
* **Isoforms.** The RDF holds the isoform sequences too (140 `Modified_Sequence` nodes of 63 panel entries, as many as the
  varsplic FASTA gives; the 2 `External_Sequence` and 1 `Unknown_Sequence` nodes are other entries' or have none), but this source models proteins by accession, not isoform; they stay with
  uniprot-fasta.
* **Fragments.** 376 of the 1,547 canonical sequences (all "single"; no "multiple" on the panel).

**Keys: one Protein per accession.** Stock uniprot keys Protein on `md5checksum, organism`, and the type's keys file
(`humanmine-items_keys.properties`) carries that key for every RDF source. On the panel 36 md5s are shared by 72 entries:
20 TrEMBL entries have exactly a Swiss-Prot canonical's sequence (A3KPE2 = P02656, A0A384NPN7 = P05091, ...), 9 a
Swiss-Prot isoform's (F1T0F8 = P26367-2, ...), the rest TrEMBL with TrEMBL. Had this source written
`Protein.md5checksum`, those 20 would have merged into the Swiss-Prot proteins. So:

* `Protein.md5checksum` is not written (stock's 254 values are the only ones), and sources.yaml `own_keys` gives the
  source its own keys file (`humanmine-uniprot_keys.properties`) with Protein keyed on `primaryAccession` only.
* `Sequence` has no key in any keys file, so a Swiss-Prot entry's RDF sequence would have stood, orphaned, beside the one
  stock stored (Protein.sequence resolves to stock's by priority); this is why `rdf:value` was dropped before.
  `own_keys` keys this source's Sequence on `md5checksum` (`project.source_keys` now names a key no file declares): stock
  stores one Sequence per md5 and loads first, so the RDF item merges into it. Identical sequences share one Sequence,
  as in stock. uniprot-fasta (later, keys Protein on accession, no Sequence key) still makes its own isoform Sequences.

**Fetch.** Only `out/uniprot/queries/main.sparql` changed. Count query first (1 request, 3 s): 1,547 rows, 658,052
residues. Then the allgenes cache copied to `repos/rdfc2im/cached_raw_data.trembl-seq-2026-11-18` (`tools/copy_tree.py`,
136 files, every group verified), the uniprot group restored and `main` alone fetched again: 1,547 rows, 963,910 B, one
page, 12.4 s, 18 Nov 2026 21:58 UTC; the group saved back with the same meta (13 files, 14,448,719 B). The other 12 tables
are the 18 Nov 00:34 ones. A cache group records scope, taxon and panel but not the query, so the old group restored for
the new query would have loaded the sequence columns empty: `rdfc2im tsv` now exits non-zero when a raw table lacks a
column its query selects. **The canonical driver** (`fb-env-ut-hybrid.sh`) must point `DRIVE_CACHE_DIR` at a cache whose
uniprot group holds the new `main` table: `cached_raw_data.trembl-seq-2026-11-18`, or the allgenes cache with that one
group copied in; every other group is identical. The panel release asset `cached_raw_data-*.tar.gz` needs the same group.

**The cited-PMID set.** The pubmed scope is every 4-9 digit attribute value of the hgnc (panel cut), uniprot,
gwascatalog and reactome items; the new lengths of 1,000 and over joined it, `pmids_md5` changed and the cached pubmed
group was refused (the first run stopped at `rdfc2im_pipeline`). `length` lines are now left out: the set is again the
6,890 numbers the cached group was fetched for. Only 3,930 of them are `pubMedId` values (the rest are masses,
identifiers, years, pages); taking `pubMedId` alone is the fix, left for a task of its own since it changes the PubMed
records loaded and needs the pubmed group fetched again.

**Build** (`drive-ut-9n4.32.sh`, the canonical driver with this worktree, the cache above and `pages-9n4.32`; resumed at
`rdfc2im_pipeline` after the PMID fix): `rdfc2im_pipeline` 111 s, `integrate_sources` 934 s (9n4.35: 786 s;
humanmine-uniprot 22 s against 21 s, the rest is run-to-run variation), `postprocess` 201 s (169 s; create-search-index 59
s and 55 s, it runs twice as before; autocomplete 18 s), `apply_public_lists` 183 s, `write_source_manifest` 551 s. Lowest
available memory 5.5 GB in integrate, 4.3 GB at the start of `build_webapp` (the ut mine was stopped before the build: 9.9
GB available at the start). `/` 4.2 GB free before and after.

| | before | after |
|---|---|---|
| Protein | 22,630 | 22,630 |
| with `sequence` (and `length`) | 254 | 1,687 |
| with a sequence and no stock record (TrEMBL, Swiss-Prot fragments) | 0 | 1,433 |
| `isFragment` true / false | 0 / 254 | 376 / 1,311 |
| with `md5checksum` | 254 | 254 |
| Sequence objects (distinct md5) | 254 (254) | 1,651 (1,642: 9 RDF sequences equal a varsplic isoform's) |
| Sequences shared by two or more proteins / referenced by none | 0 / 0 | 36 / 0 |
| duplicate `primaryAccession`; `Protein.length` != `sequence.length`; dangling `sequence` | 0; 0; 0 | 0; 0; 0 |
| canonical / isoforms / isoforms with `canonicalProtein` / dangling | 114 / 140 / 140 / 0 | 114 / 140 / 140 / 0 |
| UniProtFeature; Gene-Protein pairs | 8,105; 21,950 | 8,105; 21,950 |
| all objects | 1,120,890 | 1,122,286 |
| Postgres `humanmine-production` | 2,238 MB | 2,209 MB (a fresh database) |
| PAX6 proteins with a sequence (fragments, length) | 2 of 47 | 47 of 47 (34; 12-473) |
| CYP2D6 proteins with a sequence (fragments, length) | 2 of 59 | 59 of 59 (2; 117-520) |

The 254 stock proteins have exactly the records they had (md5, sequence md5 and length, length, isFragment,
isUniprotCanonical, canonicalProtein, feature count), and no protein gained or lost a gene. The RDF UniProt data set
carries its licence (CC BY 4.0, im-9n4.45).

**How it looks** (Chromium 1600 px wide; screenshots in `repos/.sandbox-disk/rdfc2im/screenshots-9n4.32/`):

| | PAX6 before | PAX6 after | CYP2D6 before | CYP2D6 after | HumanMine PAX6 / CYP2D6 |
|---|---|---|---|---|---|
| rows aligned | 2 | 47 | 2 | 59 | 5 / 2 |
| page load to alignment drawn | 1.9 s | 7.2 s | 2.4 s | 3.9 s | 9.5 s / 10.8 s |
| sequence queries (one per protein) | 47 | 47 | 59 | 59 | 5 / 2 |
| `/align-sequence` POST: request, response, time | 895 B, 949 B, 0.08 s | 13 kB, 26 kB, 3.3 s | 980 B, 1 kB, 0.1 s | 27 kB, 34 kB, 1.7 s | 2 kB, 0.6 s / 1 kB, 0.4 s |

* The panel is 294 px tall whatever the number of sequences and shows 15 rows at a time; the rest are reached by
  dragging inside the alignment (the mouse wheel does nothing; enlarging the panel from its corner does not show more
  rows). Labels are accessions only, so nothing tells a Swiss-Prot entry from a TrEMBL fragment.
* PAX6 (`PAX6-msa.png`, `-dragged-right`, `-dragged-down`): fragments dominate. In the first 55 columns 5 of the first
  15 rows are only gaps (Q8IVH0, Q6RYC5, A0A1W2PSB5 ...), and further on short fragments (the shortest 12 residues) sit as
  islands in long gap runs; the full-length entries line up cleanly. Readable for someone looking for a particular
  fragment, a lot of grey for anyone wanting the gene's protein.
* CYP2D6 (`CYP2D6-msa.png`, `-dragged-down`): dozens of near-identical full-length TrEMBL entries (most of them
  A0ACI8...), so the panel looks like the canonical sequence repeated; variant columns stand out, and one entry
  (A0ACI8QI16) runs off into a different C-terminus. Two fragments.
* The aligner (`trial/front`, 127.0.0.1:13000) copes: no timeout or error, 3.3 s for PAX6's 47 sequences.
* Protein Visualizer (`*-protein-visualizer.png`): unchanged, it shows the canonical entry's PDB structures (2CUE/6PAX
  for PAX6, 2F9Q ... for CYP2D6). Proteins table (`*-proteins-table.png`): TrEMBL rows now have a length; their
  Primary Identifier stays NO VALUE (only stock sets it).
* HumanMine (`*-humanmine.png`): PAX6 5 rows (P26367, P26367-2 and three full-length TrEMBL), CYP2D6 2. Stock loads
  no fragments (`loadfragments` false) and drops a TrEMBL entry whose sequence another entry already has.

Whether to show only reviewed proteins by default is the owner's decision; nothing filters them here.

## Persistence, and what does not survive

**The loaded mine lives in Docker volumes** - `rdfc2im-pgdata` and `rdfc2im-solrdata` (named
volumes, or bind mounts of `RDFC2IM_PGDATA` / `RDFC2IM_SOLRDATA` when those are set).
`docker compose -f trial/docker-compose.yml down` stops the containers and keeps the volumes;
`down -v` throws them away, and so does destroying the machine. There is no other copy: the
mine is not backed up anywhere, and rebuilding it means running this script again. (The
Makefile's `up`/`down`/`status`/`logs`/`trial-destroy` targets do the same things but default to
`podman compose`; pass `COMPOSE="docker compose -f trial/docker-compose.yml"` to use them here.)

To keep the loaded data independently of the containers:

```sh
docker exec rdfc2im-postgres pg_dump -U intermine humanmine-production      > humanmine-production.sql
docker exec rdfc2im-postgres pg_dump -U intermine humanmine-userprofile     > humanmine-userprofile.sql
```

The userprofile dump is the one that carries the public demo templates; `humanmine-items` is
scratch and not worth keeping. The Solr index is derived data - rebuild it with
`--only postprocess` rather than dumping it.

## See also

- `tools/full-build.sh` header - the authoritative option and environment reference, plus a
  comment per phase explaining why each workaround exists.
- `LOAD-TRIAL.md` - the chronological record of every one of those findings being made by hand.
- `USAGE.md` - the `rdfc2im` command reference, and build-scope flags in detail.
- `STATUS.md` - per-source state, mapping decisions, and what is still open.
- `RESTART.md` - how to pick this project up cold.

## Aligner and imjs front (im-9n4.8)

`trial/front/` is a separate compose project, `rdfc2im-ut-front` (aligner on 127.0.0.1:13000, nginx
on :15001 with host networking). It is not part of `trial/docker-compose.yml`, so rebuilding the
`rdfc2im-ut` stack does not affect it. To start it from `start_mine_stack`, after the BlueGenes
jar moves to :15011 (stop any bare jar on :15001 first), run `trial/front/up.sh` (idempotent;
needs network for the first imjs fetch, and builds the aligner image on first use). `trial/front/down.sh` removes it.
See `trial/front/README.md`.

`tools/full-build.sh --with-front` (off by default) runs `trial/front/up.sh` at the end of `start_mine_stack`, after the
restart of the mine and BlueGenes containers. The front's ports and container names are its own (compose project
`rdfc2im-ut-front`, origin `localhost:15001`), not derived from `--stack-name`.
