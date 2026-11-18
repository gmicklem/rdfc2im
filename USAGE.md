# rdfc2im - usage

*Maintained alongside the code; regenerated docs are in `out/_docs/`. Version: 0.2.5 (Items XML route).*

## Setup

```
git clone <this repo> && cd rdfc2im
pip install -r requirements.txt        # pyyaml, lxml (a venv is fine)
make inputs                            # clone/refresh upstream into in/  (~150 MB, gitignored)
```

`make inputs` (= `tools/make-inputs.sh`) assembles this layout; place the files yourself instead
if you already have the checkouts (edit `rdfc2im.yaml` if your paths differ):

```
in/config/<source>/model.yaml ...        rdf-config configs      config_root
in/intermine/bio/model/core.xml ...      intermine bio sources   model_dirs[0]
in/humanmine-bio-sources/<src>/...       humanmine bio sources   model_dirs[1]
in/humanmine_project.xml                 project_xml
in/humanmine_model.xml                   live_model
in/humanmine_model.json                  model_json (only for `rdfc2im linkml`)
```

`rdfc2im` aborts with a list of missing paths if any of these is absent.

## Commands

| command | does | reads | writes (under `out/`) |
|---|---|---|---|
| `make allow` | scope the model from project.xml (+ `curation/extra_allow.txt`) | project.xml | `humanmine.allow` |
| `make translate` | build/merge the mappings, generate queries | `in/`, `knowledge.yaml`, `sources.yaml`, your edits | `<src>/mapping_*.tsv`, `columns.tsv`, `queries/*.sparql`, `sparql.yaml`, `additions.xml`, `report.txt` |
| `make fetch` | POST each query to its endpoint (needs network) | `queries/` | `<src>/raw/*.tsv` |
| `make tsv` | clean SPARQL-TSV, apply transforms/filters/constants | `raw/`, `columns.tsv` | `<src>/tsv/*.tsv` |
| `make items` | merge a source's tables by key into Items XML | `tsv/`, `columns.tsv` | `<src>/items/<src>.xml` |
| `make project` | mine configuration | all `columns.tsv`, `curation/extensions_additions.xml` | `_mine/project.xml`, `humanmine-items_keys.properties`, `humanmine-items_additions.xml`, `genomic_priorities.properties`, `replaced_sources.xml`, `links_report.txt` |
| `make check` | validate mappings vs model, `via` ranges, items ref_ids, keys, duplicate loads | `_mine/`, `columns.tsv`, `items/` | (report to stdout; exit 1 on hard problems) |
| `make docs` | status + curation guide | everything above | `_docs/STATUS.md`, `_docs/CURATION_GUIDE.md` |
| `make all` | one process running allow → translate → tsv → items → project → check → docs; add `FETCH=1` to include fetch | | |
| `make linkml` | HumanMine LinkML schema with corrected field terms | `model_json`, `live_model` | `curation/linkml/humanmine.yaml` |
| `make fork-sync` | copy generated keys/additions into `humanmine-items/` | `_mine/` | `humanmine-items/resources/` |
| `make test` | unit tests (pytest if present, else `tests/run.py`); the live checks in `tests/test_live_mine.py` are skipped unless you ran `make test-live` | | |

Variables: `SRC=ncbigene` (repeatable) restricts to sources; `LIMIT=0` removes the SPARQL LIMIT (default 20) - it applies to `translate` (written into `queries/`) and to `fetch` (overrides at send time, so `make fetch LIMIT=0 FORCE=1` does a full extract);
`GUESS=--no-guess` excludes `guess` rows. Every target is `python3 -m rdfc2im <cmd> [flags]`; `python3 -m rdfc2im <cmd> -h` lists flags
(`--source/-s`, `--limit`, `--no-guess`, `--types root|union|all`, `--no-from`, `--dry-run`, `--force`, `--sleep`, `--timeout`).
`ITERATE=n` pages every query (`LIMIT n OFFSET k`, `ORDER BY` the root variable) until a short page comes back - default 5000, `0` = one request per query; `SLEEP=s` waits between requests (default 1). Fetch also honours the environment variables `DRY_RUN=1`, `FORCE=1`, `SLEEP`, `ITERATE`. Typical full extract: `make fetch LIMIT=0 FORCE=1` (add `SRC=<source>` to do one at a time). A failing endpoint is logged and skipped (POST then GET; SPARQL-JSON, then TSV, then CSV are tried - JSON first because it is dialect-free; all are converted to W3C TSV in raw/); a query that returns no rows is flagged `<-- no rows`. Re-fetch one source with `make fetch SRC=<source> FORCE=1`.

## Build scope: taxon and gene list

By default every source builds for human (NCBI taxon 9606) with no gene restriction - this is
`translate`'s only behaviour if you never touch scope, and it is exactly what is committed under
`out/*/queries/`. Two flags on `translate` (and therefore `all`) narrow that, for a smaller or
faster demo build, or a genuinely different organism:

- `--taxon 9606,10090` - one or more NCBI taxon ids. Applies only to sources whose own SPARQL can
  actually filter by species (currently `ncbigene`, `uniprot`, `reactome` - each already restricts
  itself to human this way). A source that is human-only *by definition*, with no other species in
  its upstream data at all (`hgnc`, `clinvar`, `gwascatalog`), is **skipped** rather than
  mislabelled if you ask for anything other than the default - there is nothing in its own data to
  restrict, and stamping it with a different taxon would be actively wrong. A source with no
  organism dimension at all (the ontologies, `pubmed`) is left untouched either way.
- `--genes CYP2D6,TP53` or `--genes @path/to/list.txt` (one symbol per line) - restrict to a gene
  list. Only sources declaring `gene_scope_field` in `rdfc2im/data/sources.yaml` support this
  today (`ncbigene`, resolving symbols to NCBI Gene ids via a live lookup against the same
  endpoint it fetches from); a source without a resolver wired up is skipped with a message rather
  than silently ignoring the restriction. Extending this to another source means adding its
  `gene_scope_field` (the `Gene.<field>` it maps with `required=yes` - so the restriction reaches
  every one of its tables, not just the one that happens to carry a human-readable label) and a
  resolver from gene symbol into that source's own identifier scheme, in `rdfc2im/scope.py`.

Neither flag ever changes what lands in the committed `mapping_predicates.sssom.tsv` files - both
are applied in memory, after `translate` has already written the mapping to disk, purely to shape
the SPARQL this one run generates. `rdfc2im.yaml`'s `scope: {taxon: [...]}` sets a workspace-wide
default; `--taxon` on the command line overrides it for one run.

## The workflow

```
make all                       # first pass: everything auto-mapped
$EDITOR out/<source>/mapping_subjects.tsv out/<source>/mapping_predicates.sssom.tsv
make translate SRC=<source>    # apply edits; read out/<source>/report.txt and queries/*.sparql
make fetch LIMIT=20            # networked machine; inspect out/<source>/raw/*.tsv (LIMIT=0 FORCE=1 for the full extract)
make tsv items check docs
make fork-sync                 # then install humanmine-items/ and use out/_mine/project.xml
```

Curation never blocks later steps: rows with `ext_status` `sure`, `human` or `guess` are used, `todo` and `drop` are not.
Running `make all` on a curated `out/` merges; only `rm -rf out` (or `rm -rf out/<source>`) throws edits away.
`make clean` removes only `out/_mine` and `out/_docs`. Keep `out/*/mapping_*.tsv` and the hidden `.mapping_*.base.*`
snapshots under version control - they are the state.

## What you edit

- `out/<source>/mapping_subjects.tsv` - one row per rdf-config subject: `im_class` (InterMine class), `role` (`root` | `node` | `skip`), `status`, `note`.
- `out/<source>/mapping_predicates.sssom.tsv` - one row per (subject, predicate, column), SSSOM layout. Editable:
  `object_id` (`intermine:Class.field`), `comment`, `ext_table`, `ext_status`, `ext_transform`, `ext_filter`, `ext_value`, `ext_required`.
  Leave the commented YAML header alone.
- `curation/extra_allow.txt` - extra source dirs whose additions/keys should enter the model (e.g. `/uberon/`).
- `curation/extensions_additions.xml` - approved new fields/classes (spec section 8 + `MeshTerm.identifier`).
- `rdfc2im/data/knowledge.yaml` - my subject/predicate proposals; edit to change defaults for every run.
- `rdfc2im/data/sources.yaml` - per-source `replaces`, `consts`, `roots`, DataSet/DataSource names, scope.

Statuses: `sure` (evidence in the uploads; `ext_basis` says which) · `guess` (my proposal) · `todo` (you decide) ·
`human` (your edit) · `drop` (not loaded) · `link` (structural). `out/_docs/CURATION_GUIDE.md` lists the open items
per source with literal example lines.

## Delivering to HumanMine

**All four steps below are automated by `tools/full-build.sh` - see `BUILD.md`.** They are kept
here because they are what the script does, and you need them if you are delivering into an
existing mine by hand rather than building one from scratch.

1. `make fork-sync`; copy `humanmine-items/` into `humanmine-bio-sources/`, register it as `':bio-source-humanmine-items'` with `projectDir` `./humanmine-items` in `settings.gradle` (the `bio-source-` prefix is how the mine resolves the artifact - see `humanmine-items/README.md`), then `./gradlew :bio-source-humanmine-items:install`.
2. Use `out/_mine/project.xml` (HumanMine's project.xml with `humanmine-<source>` sources inserted; superseded originals are in `replaced_sources.xml`).
3. Put each `out/<source>/items/<source>.xml` at the `src.data.file` path (`src_data_dir` in `rdfc2im.yaml`).
4. Review `out/_mine/humanmine-items_keys.properties` (DRAFT keys are marked) and `genomic_priorities.properties` (HumanMine's own, with our sources merged in; it replaces `dbmodel/resources/genomic_priorities.properties`) before building.

## Building and testing a whole mine

| command | does |
|---|---|
| `tools/full-build.sh` | RDF to a running, fully-configured mine in 20 phases. `--dry-run`, `--list-phases`, `--from PHASE`/`--only PHASE` to resume, `--sources`/`--genes`/`--taxon` to rescope, `--use-cached-data`/`--cache-dir` to reuse the previous build's fetched data, `--stock-sources "a b"` (and `--stock-local DIR`) to load stock HumanMine/InterMine sources beside the rdfc2im ones, cut to the gene panel (6.0 line only). With stock sources the build also gives the mine's ID resolver the NCBI human `gene_info` as `resolver.file.rootpath/entrez` (`--resolver-scope taxon` the default, all human genes; `panel` only the panel's), and deletes a stale `idresolver.cache`. `--jbrowse2-src DIR` (or env `JBROWSE2_SRC`) makes `stage_artifacts` also stage the patched BlueGenes tool set; `--with-front` starts `trial/front/up.sh` after the stack is up. See `BUILD.md` for prerequisites, the stock-source phases and troubleshooting. |
| `python3 -m rdfc2im cache save\|restore\|verify\|list` | the checksummed `cached_raw_data/` that `full-build.sh` fills and `--use-cached-data` reads: `cache save GROUP SRC_DIR [--meta K=V]...`, `cache restore GROUP DEST_DIR [--meta K=V]...` (refuses on any `--meta` that differs from what was saved, or on a corrupt entry), `cache verify [GROUP...] [--meta K=V]...` (the `--meta` check as on restore, for data used where it lies in the cache), `cache list`; `cache save ... --for-release` refuses (exit 1, nothing written) a group whose `--meta` says `redistributable=false`, or that has no `redistributable=true` and is not one of the known pre-flag groups (rawcache.RELEASE_ALLOWED_UNFLAGGED: the RDF panel sources, gene-id-lookup, humanmine-model, bluegenes-tools, bluegenes-tools-patched); `cache check-release --cache-dir DIR` lists every group with its `redistributable` and `licence` and exits 1 if any group may not go into a release asset (run it before making the CI release tarball); all take `--cache-dir`. `rdfc2im fetch` exits 1 if any query failed or came back partial. |
| `python3 -m rdfc2im stock list\|check\|jars\|files\|postprocess\|size\|meta` | the stock-source table `rdfc2im/data/stock_sources.yaml` (one entry per HumanMine source: type, jar origin, HumanMine's data path, upstream files and their filters, licence and `redistributable`, `after`/`needs`/`postprocess`), as `full-build.sh --stock-sources` reads it: `stock check NAME... [--sources "..."] [--local DIR]` validates a list and prints it in HumanMine's project.xml order (exit 1 with the reasons otherwise); the others print tab-separated rows. `rdfc2im project --stock-source NAME` keeps and rewrites those `<source>` entries. |
| `tools/watch-build.sh` | live per-phase dashboard for a build in progress (read-only; `LOG_DIR=<dir>` if the logs are elsewhere) |
| `make test` | offline unit tests on synthetic fixtures |
| `make test-live` | integration checks against a *running* mine - real REST queries and Solr assertions. Opt-in (`make test-live` sets `RDFC2IM_LIVE=1`) and skips when no mine is reachable, so plain `make test` stays green on a fresh checkout and ignores any stale mine left running. |

`make test-live` exists because most of the bugs found when this build was first run end to end
were invisible offline: a Gradle task reporting SUCCESS while silently indexing nothing, a
postprocessor whose failure the plugin swallows so the exit code stays 0, a source-priority rule
that drops an attribute only where two sources overlap. Each test in `tests/test_live_mine.py`
names the specific bug it guards against.

## Pre-filtering raw files to the gene panel (tools/subset_raw.py)

The stock InterMine loaders (UniProt XML, GO annotation GAF, NCBI GFF3, FASTA, interaction and
orthologue tab files) have no gene filter, so their raw files are cut down to the panel first.
Python 3 standard library only, streaming, `.gz` read and written by suffix.

```
tools/subset_raw.py idsets --genes curation/demo_gene_panel.txt --out DIR [--items-root out] [--lookup-dir cached_raw_data/gene-id-lookup]
tools/subset_raw.py filter --format gaf|gff3|uniprot-xml|fasta|tab|gene_info --in PATH --out PATH
                           [--ids FILE] [--column N[,N...]] [--taxon ID] [--keep-comments]
```

`idsets` writes `entrez.txt`, `ensembl.txt`, `uniprot.txt`, `symbol.txt` (sorted, one id per line)
and `idsets.json` (counts, md5 of the panel file, the inputs used). The ids come from the generated
`<items-root>/{ncbigene,hgnc,ensembl,uniprot}/items/*.xml` (panel genes only) and the gene-id lookup
cache. No `uniprot_reviewed.txt` is written, because the items do not say which proteins are
Swiss-Prot.

`filter` prints one JSON line (`format`, `records_in`, `records_out`, `ids_given`, `ids_matched`)
and exits 0; a missing input, unknown format, or a format that needs `--ids` without one exits 2
with a message on stderr. Output is written to a temporary name and renamed, so a failed run never
leaves a half-written file.

- `gaf`: `!` header lines, and rows whose column 2 is in `--ids` (an isoform id matches its base accession).
- `gff3`: all `#` lines, features whose `Dbxref` has `GeneID:<id>`, plus every descendant by `Parent`
  (even when children come first) and the ancestors of matching features. An embedded `##FASTA`
  section is dropped. Two passes over the input.
- `uniprot-xml`: root element, every `<entry>` with any `<accession>` in `--ids`, and the trailing
  `<copyright>`. Entries are copied as text, so the output is byte-faithful and well-formed.
- `fasta`: records whose header accession (`>sp|P10635-2|...` or `>ACC ...`) is in `--ids`; isoforms match on the base accession too.
- `tab`: `--column` is 1-based; a row is kept when any listed column holds an id (whole cell, or one
  of its `|`, `;`, `,` separated parts, with or without a `db:` prefix). Lines starting `#` are always kept;
  `--keep-comments` also keeps the first line.
- `gene_info`: header kept; `--taxon` keeps that tax_id; `--ids` (optional) also restricts the GeneID.
  `--taxon 9606` alone gives the all-human-genes resolver file.

Tests: `tests/test_subset_raw.py`, with fixtures and the sources of the real samples in `tests/fixtures/subset_raw/`.

## Genomics England gene lists (tools/panelapp_lists.py) [im-9n4.21]

HumanMine has public lists `PL_GenomicsEngland_GenePanel:<Panel_name>`, made in December 2021 from the Genomics England
PanelApp (Green genes only). `tools/panelapp_lists.py` (standard library only) makes them again from whatever the
PanelApp serves today. It fetches, maps and reports; it writes to no mine. Uploading the lists is phase
`apply_public_lists` (BUILD.md, "Genomics England gene lists").

```
python3 tools/panelapp_lists.py fetch   --out DIR [--cache-dir CACHE]    # every current panel, raw JSON + META.json
python3 tools/panelapp_lists.py lists   --in DIR --out LISTS [--mine URL] [--select all|100k] [--keep-2021-names]
python3 tools/panelapp_lists.py resolve --in DIR --mine URL --out FILE [--organism "H. sapiens"] [--select all|100k]
```

* `fetch` walks `https://panelapp.genomicsengland.co.uk/api/v1/panels/` (100 a page, `next`), `.../panels/signedoff/`
  and `.../panels/<id>/` for each panel: 445 requests (433 panels), sequential, at most two a second, User-Agent
  `rdfc2im-panelapp-lists/1.0`, back-off on 429 and 5xx; the whole fetch took about 9 minutes and the raw JSON is 108 MB. `DIR` gets `panels/<id>.json` (raw), `panels-index.json`, `signedoff-index.json` and `META.json` (fetch
  date, counts, each panel's id, name, version, `version_created`). A rerun into the same `DIR` fetches only the
  panels whose version changed (`--no-resume` fetches all). `--cache-dir` saves `DIR` as the rdfc2im cache group
  `panelapp`, `redistributable=false` (BUILD.md says why).
* `lists` writes `LISTS/lists/<name>.json` (`:` as `__`), `index.json` and `index.tsv`. A list is: name, type `Gene`,
  tags `Genomics England gene panel` and `im:public`, a description (the 2021 text, "Decemeber" corrected, plus
  `Panel <id>, version <v> (created <date>), fetched <date>`), the panel, `replaces` (the 2021 list name, for the 17
  panels renamed since) and the Green genes with HGNC id, symbol and Ensembl GRCh38 id. Naming rule: the panel name with
  spaces as `_` and every other character kept, except `/` as `_`; the test reproduces 154 of the 171 names of 2021
  and the other 17 are the renamed panels. STRs and regions are counted, not listed. `--select 100k` keeps the
  panels of type `rare-disease-100k`, which is what the 2021 set was. `--mine` marks which lists the mine already has
  (one anonymous `GET /service/lists`).
* `resolve` asks the mine's id resolution service (`POST /service/ids`, poll, read, delete the job; read-only) three
  times, once per identifier type, over the distinct identifiers of all panels (1000 a job): HGNC id, Ensembl GRCh38
  id, symbol. `FILE` (JSON) has the counts for each type alone and for the chain HGNC id, then Ensembl id, then symbol,
  overall and per panel; `FILE.genes.tsv` gives, per distinct gene, the mine
  gene the chain chose (object id, Entrez `primaryIdentifier`, symbol); `FILE.unresolved.tsv` lists every gene that is unresolved, ambiguous (several genes),
  resolved only by a fallback identifier, or placed on different genes by different identifiers, with the outcome per
  identifier type and the reasons PanelApp's own data suggests. If the mine does not answer it waits (up to 40
  minutes); an outage is never reported as a result.

Tests: `tests/test_panelapp_lists.py` (recorded panels in `tests/fixtures/panelapp/`, no network).

## Public lists on a mine (tools/apply_public_lists.py) [im-9n4.22]

Makes the PanelApp lists above and HumanMine's 13 other public lists (`curation/public_lists/`) public lists of a mine, as
the superuser, through its web service. It archives the mine's current public lists first, and a re-run replaces the lists
without duplicates (BUILD.md, "`apply_public_lists`", has the service calls and the rules). Standard library only.

```
python3 tools/apply_public_lists.py --mine http://localhost:18090/humanmine \
    --panelapp-cache CACHE_GROUP_DIR --legacy curation/public_lists \
    --archive-repo /path/to/historic_artefacts [--mine-label ut-demo] [--select all|100k] [--keep-2021-names|--current-names] \
    [--user superuser@intermine.org --password intermine] [--wait SECONDS] [--report run.json] [--dry-run]
```

* `--panelapp-cache`: the rdfc2im cache group `panelapp` (its `data/` holds `META.json` and `panels/`; a directory that
  holds them itself works too). The group's md5s are checked unless `--dry-run`.
* `--archive-repo`: each run adds `<mine-label>-public-lists/<date>[-N]/` (the layout of `historic_artefacts`: `lists.json`,
  `lists.tsv`, `members/`, `export.log`, plus `archive.json`). The export script is
  `<archive-repo>/scripts/export_humanmine_public_lists.py`, or `--export-script` / `PUBLIC_LISTS_EXPORT_SCRIPT`. Existing
  directories are never overwritten; if the archive step fails nothing is uploaded or removed.
* `--dry-run` resolves (read-only `/service/ids` jobs) and prints what would happen: lists to upload with sizes, lists
  skipped with the reason, public panel lists that would be removed. No archive, no login, no write.
* `--i-know-this-is-production`: without it a mine on a public host (`www.humanmine.org`, any `*.org`) is refused.
* Exit code 0 when every list uploaded and read back as sent; 1 otherwise (the report says which).

In `tools/full-build.sh`: `--public-lists CACHE_GROUP_DIR --public-lists-archive ARCHIVE_REPO [--public-lists-select all|100k]
[--public-lists-names 2021|current]` (phase `apply_public_lists`, off without the flag).

Tests: `tests/test_apply_public_lists.py` (the web service and the export script injected, no network),
`tests/test_full_build_public_lists.py` (dry-run), and three live checks in `tests/test_live_mine.py` that skip unless the
mine has the Genomics England lists.

## Data-source status pages [im-9n4.42]

One Markdown page per source of a build, and an index: where the data came from (URL, release, Last-Modified, fetch
time, size, sha256, licence), the scope and the filter, records read and kept, objects loaded, and a table of every field
of the source with what it maps to and whether it is loaded, with the number of records that carry it. Three tools,
run in this order (BUILD.md, "Data-source status pages", has the sources of every value and the timings):

```
python3 tools/source_manifest.py --out out/_mine/source_manifest.json --sources "go ncbigene ..." \
    --stock-sources "uniprot go-annotation ..." --cache-dir cached_raw_data --stock-dir $RDFC2IM_STOCK_DIR \
    [--filtered-cache DIR] [--logs LOG_DIR] [--count-cache DIR] [--max-seconds 300] [--mine URL] \
    [--reference-datasets curation/humanmine_2022_datasets.json] [--endpoint-counts SRC ... --sleep 1]
python3 tools/source_pages.py pages --manifest out/_mine/source_manifest.json --out DIR
python3 tools/field_counts.py count --format tab|gff3|xml|obo|fasta --in FILE [...]   # one file, by hand
```

* `source_manifest.py` works from the caches, `out/` and the build logs; `--mine` adds the objects loaded per class and
  data set (read-only count queries). Field counts stream the raw files (`field_counts.py`) and are cached in
  `--count-cache` (default `$RDFC2IM_STOCK_DIR/field-counts`) under each file's sha256; a count that passes
  `--max-seconds` stops, and its page says what share of the file it saw.
* `--endpoint-counts SRC` (off by default) asks an RDF source's SPARQL endpoint one `COUNT` query per predicate of
  the root subject, one at a time, `--sleep` seconds apart: counts over the whole endpoint, not the build's extract.
* The field tables of the stock sources come from `rdfc2im/data/stock_mappings/<source>.yaml` (format in
  `tools/field_counts.py` and below); those of the RDF sources from `out/<source>/mapping_predicates.sssom.tsv`.
  Known gaps per source: `rdfc2im/data/source_gaps.yaml` (only what BUILD.md or the expert review log records).
* `pages` output is deterministic: the same manifest and mapping files give byte-identical pages.

A stock mapping file says, for each input file of a loader (`files[].id` as in `stock_sources.yaml`): its `format`, how
to count it (`comment`, `skip_lines`, `header_line` N / `first` / `match:TEXT`, `record_key` for XML), where the file
states its `release`, and one entry per field: `key` (tab `col:N`; gff3 `col:N`, `attr:NAME`, `attr:Dbxref:PREFIX`;
xml the element path, `/@name` for an attribute; obo `Term/TAG`; fasta `header:OS` ..., `sequence`), the source's `name`
and `description`, `maps_to` (strict `Class.field` of the model), `status` (`loaded`, `not loaded` or `unknown`), a
short `reason`, and `code` (file:line in the loader). `unlisted` says what a key found in the file but not listed means.
Every file records the loader commit it was read at.

In `tools/full-build.sh`: `--source-pages DIR` adds the last phase `write_source_manifest` (after `verify`);
`--data-set-links URL` makes `prepare_mine_checkout` add a last source, `data-set-links`, that sets `DataSet.url` (the
page) and `DataSet.description` on every data set of the build. Both are off without the flag.

Tests: `tests/test_source_pages.py` (counters, manifest, a golden page, the link items and project wiring),
`tests/test_full_build_source_pages.py` (dry-run).

## Not yet exercised

`linkml-validate` is not wired into `check`. (`fetch` against the real endpoints and a real
InterMine load of an items file were both unexercised when this file was first written; both
have since been done repeatedly - see `BUILD.md` and `LOAD-TRIAL.md`.)
