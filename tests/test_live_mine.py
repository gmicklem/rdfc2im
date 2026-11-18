"""Live integration checks against a running demonstration mine.

Unlike every other file in tests/ - which runs offline against synthetic fixtures - these
assert on a mine that tools/full-build.sh has actually built and started. They exist because
essentially every bug this project hit during its first real end-to-end build was invisible
offline: a Gradle task that reports SUCCESS while silently indexing nothing, a postprocessor
whose failure the plugin swallows so the exit code stays 0, a priority rule that drops an
attribute only when two sources overlap. None of those can be caught by a unit test on a
fixture; all of them are caught by asking the running system a question and checking the answer.

Every check here is anchored to a real bug found on 2026-09-21, named in each test's docstring,
so a regression tells you not just "this broke" but "this specific thing broke again, here is
what it was last time".

Running them (opt-in - see live_enabled):
    make test-live                       # or:
    RDFC2IM_LIVE=1 python3 -m pytest tests/test_live_mine.py -v

Unless RDFC2IM_LIVE=1 every test SKIPS, and with it set they still SKIP if no mine is reachable,
so `make test` stays green on a machine that has only ever checked out the repo - including one
where a stale mine from an earlier session happens to still be running. Point them somewhere
else with:
    MINE_BASE=http://host:8090/humanmine SOLR_BASE=http://host:8983 make test-live
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

MINE_BASE = os.environ.get("MINE_BASE", "http://localhost:8090/humanmine")
SOLR_BASE = os.environ.get("SOLR_BASE", "http://localhost:8983")
TIMEOUT = int(os.environ.get("MINE_TIMEOUT", "30"))

# The demo panel's own worked example, used as the spot-check throughout LOAD-TRIAL.md: a
# drug-metabolising cytochrome P450 that every gene-centric source in the build carries.
EXAMPLE_GENE = "CYP2D6"
EXAMPLE_GENE_ID = "1565"          # NCBI Gene id; ncbigene is the source every other merges onto
EXAMPLE_PROTEIN = "P10635"        # its UniProt accession
EXAMPLE_PATHWAY = "R-HSA-9749641"  # "Aspirin ADME" - CYP2D6 is one of its participants


class SkipTest(Exception):
    """Raised when there is no mine to talk to - see _skip."""


def _skip(reason: str):
    """Skip under pytest if it is installed, otherwise degrade to a no-op for tests/run.py.

    run.py treats any exception as a failure, so it must NOT see SkipTest propagate; pytest
    has a real skip mechanism and should use it. Returning a sentinel the caller `return`s
    keeps both runners honest without run.py needing to know about skipping at all.
    """
    try:
        import pytest  # noqa: PLC0415 - optional dependency, deliberately imported lazily
        pytest.skip(reason, allow_module_level=False)
    except ImportError:
        print(f"  SKIP: {reason}")


def _get(url: str, timeout: int = TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _get_json(url: str, timeout: int = TIMEOUT):
    return json.loads(_get(url, timeout))


def live_enabled() -> bool:
    """Live checks are opt-in. A reachable mine is not consent to test it: a stale mine left
    running from an earlier session made plain `make test` fail (tests/test_live_gating.py)."""
    return os.environ.get("RDFC2IM_LIVE") == "1"


def mine_up() -> bool:
    if not live_enabled():
        return False
    try:
        _get(f"{MINE_BASE}/service/version", timeout=5)
        return True
    except Exception:
        return False


def solr_up() -> bool:
    if not live_enabled():
        return False
    try:
        _get(f"{SOLR_BASE}/solr/admin/cores?action=STATUS", timeout=5)
        return True
    except Exception:
        return False


def query_rows(view: str, path: str, op: str, value: str):
    """Run a real PathQuery through the REST API and return its rows.

    Deliberately goes through /service/query/results rather than straight to Postgres: it
    exercises the model, the webapp and the object store together, which is where several of
    this project's bugs actually lived (a collection present in the database but absent from
    the served model still breaks every user-facing query).
    """
    q = (f'<query name="" model="genomic" view="{view}">'
         f'<constraint path="{path}" op="{op}" value="{value}"/></query>')
    url = f"{MINE_BASE}/service/query/results?query={urllib.parse.quote(q)}&format=json"
    payload = _get_json(url)
    if not payload.get("wasSuccessful", False):
        raise AssertionError(f"query failed: {payload.get('error')!r}\n  view={view} {path}{op}{value}")
    return payload["results"]


def solr_count(core: str, q: str = "*:*") -> int:
    url = f"{SOLR_BASE}/solr/{core}/select?q={urllib.parse.quote(q)}&rows=0&wt=json"
    return _get_json(url)["response"]["numFound"]


def autocomplete_classes() -> dict:
    """className -> document count in the autocomplete core, via a Solr facet."""
    url = (f"{SOLR_BASE}/solr/humanmine-autocomplete/select"
           f"?q=*:*&rows=0&facet=true&facet.field=className&wt=json")
    f = _get_json(url)["facet_counts"]["facet_fields"]["className"]
    return {k: v for k, v in zip(f[::2], f[1::2]) if v}


# ----------------------------------------------------------------- service reachability
def test_mine_serves_version():
    """The webapp answers at all.

    Regression guard for the 2026-09-21 'war built with no WEB-INF/web.xml' bug: Tomcat
    deployed it with no error logged anywhere and every request 404'd, and for the follow-on
    'no userprofile schema' bug, where every request 500'd with ContextNotInitialisedException.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    assert _get(f"{MINE_BASE}/service/version").strip(), "version endpoint returned nothing"


def test_mine_serves_model():
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    _get(f"{MINE_BASE}/service/model")


# ----------------------------------------------------------------- autocomplete
def test_autocomplete_index_is_populated():
    """create-autocomplete-index actually indexed something.

    Regression guard for the 2026-09-21 bug where objectstoresummary.config.properties named
    classes this reduced build does not load (HPOTerm/InteractionTerm/ProteinDomain);
    AutoCompleter.buildIndex threw on the first absent class and the Gradle plugin swallowed
    the exception, so the task printed FAILED, left an EMPTY index, and still exited 0. It had
    been broken in five consecutive builds without anyone noticing, which is precisely why this
    asserts on document count rather than on the absence of an error message.
    """
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    n = solr_count("humanmine-autocomplete")
    assert n > 0, "humanmine-autocomplete core is empty - create-autocomplete-index did nothing"


def test_autocomplete_covers_gene():
    """Gene is autocompleted.

    Gene is the demo panel's organising class (113 food/drug-metabolism genes), so a user
    typing a gene symbol into a form is the single most likely autocomplete interaction.
    HumanMine's stock objectstoresummary.config.properties does NOT include Gene, so this is
    an addition this project makes deliberately, not an upstream default to fall back on.
    """
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    classes = autocomplete_classes()
    assert "gene" in {c.lower() for c in classes}, (
        f"Gene missing from the autocomplete index; indexed classes were {sorted(classes)}. "
        "Check Gene.autocomplete in objectstoresummary.config.properties, and that the "
        "objectstoresummary trim did not strip it.")


def test_autocomplete_covers_protein():
    """Protein is autocompleted - same reasoning as Gene; also not an upstream default."""
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    classes = autocomplete_classes()
    assert "protein" in {c.lower() for c in classes}, (
        f"Protein missing from the autocomplete index; indexed classes were {sorted(classes)}.")


def test_autocomplete_covers_configured_ontology_classes():
    """The classes HumanMine's own config asks for are all present.

    These come from upstream objectstoresummary.config.properties. Pathway in particular is a
    good canary: it is populated by two different sources in this build, so it disappearing
    would point at the source-priority machinery rather than at the indexer.
    """
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    classes = {c.lower() for c in autocomplete_classes()}
    for expected in ("goterm", "pathway", "disease"):
        assert expected in classes, f"{expected} missing from autocomplete index ({sorted(classes)})"


def test_autocomplete_finds_a_real_gene_symbol():
    """A real panel gene symbol is actually retrievable, not merely 'some Gene rows exist'.

    Asserting on a known symbol rather than a count catches the case where the index is full
    of the right class but the wrong field - e.g. indexing Gene.primaryIdentifier only, so
    typing 'CYP2D6' finds nothing while the doc count still looks healthy.

    Queries the `symbol` field explicitly. A bare `"CYP2D6"` term query matches nothing here
    no matter how healthy the index is: the autocomplete core stores one document per
    (class, field, value) with the value under its own field name, and has no default search
    field configured for a fieldless query to fall back on. Getting that wrong is how this
    test first failed against an index that was in fact entirely correct.
    """
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    if "gene" not in {c.lower() for c in autocomplete_classes()}:
        return _skip("Gene not yet in the autocomplete index (see test_autocomplete_covers_gene)")
    n = solr_count("humanmine-autocomplete", f'symbol:"{EXAMPLE_GENE}"')
    assert n > 0, (
        f"{EXAMPLE_GENE} not found under `symbol` in the autocomplete index - check that "
        "Gene.autocomplete in curation/autocomplete_override.properties still lists `symbol`")


# ----------------------------------------------------------------- keyword search
def test_keyword_search_endpoint_responds():
    """/service/search answers rather than 500ing.

    Separate machinery from autocomplete (humanmine-search core, not humanmine-autocomplete),
    and separately broken on 2026-09-21 - but NOT for the reason it first appeared to be. The
    symptom was read as "the core's 176,794 documents carry only id/Category/facet_Category, so
    there is no content to match". That reading is wrong, and re-reading it that way will send
    the next person down the same dead end: InterMine indexes every content field with
    stored=false (SolrIndexHandler/SolrObjectHandler both pass stored=false), so Solr's
    select() NEVER returns them, in a broken mine or a perfectly healthy one. `id` is the only
    stored field; Category/facet_Category come back only because they are type `string`, which
    the _default configset backs with docValues. Confirm with a field query instead -
    `gene_symbol:cyp2d6` matches whether or not select() shows you anything.

    The actual cause was a stale index. :dbmodel:builddb drops and recreates the production
    schema, renumbering every intermineobject.id, and the humanmine-search core keeps the
    PREVIOUS build's documents until phase_postprocess re-runs create-search-index. In that
    window every hit id is dead, and InterMine does not degrade - it dies:
    SolrKeywordSearchHandler.getSearchHits() does objMap.get(id) with no null guard (objMap
    comes from Objects.getObjects, which simply omits ids the objectstore cannot resolve), the
    null object reaches SearchUtils.parseResults, which calls getObject().getClass() on it, and
    the NPE surfaces as 500 'Service failed. Please contact support.'. Proven live by injecting
    one document with an unresolvable id into a healthy core: the endpoint 500'd immediately and
    recovered the moment that single document was deleted.

    See test_keyword_search_index_is_in_sync_with_the_database for the guard on that cause.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    try:
        payload = _get_json(f"{MINE_BASE}/service/search?q={EXAMPLE_GENE}&size=5")
    except urllib.error.HTTPError as e:
        raise AssertionError(f"/service/search returned HTTP {e.code} for '{EXAMPLE_GENE}'") from e
    assert payload.get("wasSuccessful", False), (
        f"/service/search failed: {payload.get('error')!r}")


def test_keyword_search_finds_the_example_gene():
    """Searching a panel gene symbol returns at least one hit."""
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    try:
        payload = _get_json(f"{MINE_BASE}/service/search?q={EXAMPLE_GENE}&size=5")
    except urllib.error.HTTPError as e:
        raise AssertionError(f"/service/search returned HTTP {e.code}") from e
    if not payload.get("wasSuccessful", False):
        raise AssertionError(f"/service/search failed: {payload.get('error')!r}")
    assert payload.get("results"), f"no search hits for {EXAMPLE_GENE}"


def test_keyword_search_matches_partial_words():
    """A bare prefix matches, with no trailing wildcard - the EdgeNGram fix is still live.

    Guards tools/solr-search-schema-fix.sh. Solr's _default schemaless configset guesses a
    plain whitespace+lowercase type for InterMine's content fields, which gives no partial-word
    matching at all, and InterMine's quicksearch never appends a wildcard server-side (the raw
    query string reaches Solr unmodified - SolrKeywordSearchHandler.performSearch). Real symptom
    on 2026-09-21: `q=cyp` returned one near-random low-relevance Gene instead of the CYP family.

    The fix puts an EdgeNGramFilter on the INDEX analyzer only (minGram 3), so this asserts the
    property a user actually cares about rather than the schema JSON: typing three characters
    finds the genes that start with them. Asserted as a prefix relationship rather than a hit
    count so it does not become a brittle restatement of the current panel's contents.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    prefix = EXAMPLE_GENE[:3].lower()          # "cyp"
    payload = _get_json(f"{MINE_BASE}/service/search?q={prefix}&size=20")
    if not payload.get("wasSuccessful", False):
        raise AssertionError(f"/service/search failed for '{prefix}': {payload.get('error')!r}")
    symbols = [
        r.get("fields", {}).get("symbol", "")
        for r in payload.get("results", [])
        if r.get("type") == "Gene"
    ]
    assert symbols, f"bare prefix '{prefix}' returned no Gene hits at all"
    assert any(s.lower().startswith(prefix) for s in symbols), (
        f"no Gene symbol starting with '{prefix}' in the hits for '{prefix}' ({symbols}) - "
        "the EdgeNGram index analyzer is probably missing, so only whole-word matches survive; "
        "re-run tools/solr-search-schema-fix.sh AND then create-search-index (the schema change "
        "is not retroactive)")


def test_keyword_search_index_is_in_sync_with_the_database():
    """Search-index ids still resolve to real objects in the CURRENT database.

    This is the guard on the actual 2026-09-21 cause (see
    test_keyword_search_endpoint_responds): a humanmine-search core left over from a previous
    database, holding ids that no longer resolve. :dbmodel:builddb renumbers every
    intermineobject.id, so from the moment it runs until create-search-index re-runs, the core
    is pointing at objects that no longer exist. One unresolvable id anywhere in a 100-row
    result page NPEs the whole request, so the damage is invisible until a query happens to
    reach the affected page - which is exactly how the two tests above can pass while search is
    rotten.

    Checked exactly rather than by sampling, for Gene: the panel is small enough (~113) to
    compare the index against the database in full, and Gene is the class every quicksearch
    actually cares about. Comparing ids is what makes this a *sync* test - a doc count would
    look perfectly healthy on an index built against a previous database, because the count is
    right and only the ids are wrong.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not solr_up():
        return _skip(f"live checks off or no solr at {SOLR_BASE} (make test-live)")
    if solr_count("humanmine-search", "*:*") == 0:
        raise AssertionError(
            "humanmine-search is empty - create-search-index has not run against this database")

    indexed = solr_count("humanmine-search", "Category:Gene")
    assert indexed > 0, "no Gene documents in humanmine-search at all"
    url = (f"{SOLR_BASE}/solr/humanmine-search/select"
           f"?q={urllib.parse.quote('Category:Gene')}&fl=id&rows={indexed}&wt=json")
    indexed_ids = {int(d["id"]) for d in _get_json(url)["response"]["docs"]}
    live_ids = {int(row[0]) for row in query_rows("Gene.id", "Gene.id", "!=", "0")}

    dangling = indexed_ids - live_ids
    assert not dangling, (
        f"{len(dangling)} of {len(indexed_ids)} indexed Gene ids do not exist in the database "
        f"(e.g. {sorted(dangling)[:5]}). The search index was built against a DIFFERENT "
        "database - :dbmodel:builddb renumbers every id - or those rows are orphans. Any "
        "quicksearch whose result page includes one of them returns HTTP 500. Fix by re-running "
        ":dbmodel:postProcess -Pprocess=create-search-index against the CURRENT database.")


# ----------------------------------------------------------------- loaded data invariants
def test_gene_panel_is_panel_sized():
    """The build is gene-panel scoped, not a full genome load.

    Regression guard for the scope bug fixed on 2026-09-21: ncbigene was configured `full`
    rather than `panel`, so the first build loaded every human gene (~193,000) instead of the
    113-gene demo panel. The upper bound is what matters here; the exact count is asserted
    loosely because a source legitimately contributing a few extra Gene stubs is not a bug.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Gene.primaryIdentifier", "Gene.primaryIdentifier", "!=", "__none__")
    assert 0 < len(rows) < 1000, (
        f"expected a panel-sized Gene table, got {len(rows)} - is a source unscoped?")


def test_example_gene_resolves_with_cross_source_identifiers():
    """One gene carries identifiers merged from several sources.

    ncbigene supplies primaryIdentifier, ensembl supplies secondaryIdentifier, hgnc supplies
    the symbol - so this failing means the cross-source merge by integration key broke, not
    that one source failed to load.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Gene.primaryIdentifier Gene.symbol Gene.organism.taxonId",
                      "Gene.symbol", "=", EXAMPLE_GENE)
    assert rows, f"{EXAMPLE_GENE} not found"
    assert rows[0][0] == EXAMPLE_GENE_ID, f"expected NCBI id {EXAMPLE_GENE_ID}, got {rows[0][0]}"
    assert rows[0][2] == "9606", f"expected taxon 9606, got {rows[0][2]}"


# ----------------------------------------------------------------- reactome connectivity
def test_pathways_have_protein_participants():
    """Pathway connects to Protein.

    rdfc2im's own reactome mapping only ever writes Pathway description/name/organism - the
    pathwayComponent branch that would carry participants is unmapped and pruned. Protein
    links come from the stock reactome source loaded alongside it, so this failing most
    likely means that source stopped being built, staged, or integrated.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Pathway.name Pathway.proteins.primaryAccession",
                      "Pathway.identifier", "=", EXAMPLE_PATHWAY)
    assert rows, f"{EXAMPLE_PATHWAY} has no protein participants"
    accessions = {r[1] for r in rows}
    assert EXAMPLE_PROTEIN in accessions, (
        f"{EXAMPLE_PROTEIN} ({EXAMPLE_GENE}'s protein) missing from {EXAMPLE_PATHWAY}")


def test_genes_have_pathways():
    """Gene.pathways is populated.

    Regression guard for the 2026-09-21 gap: Gene.pathways is not loaded by any converter -
    it is derived by reactome's own ReactomePostProcess ("Copy over Protein.pathways to
    Gene.pathways"), which was never run, leaving the collection empty while Protein.pathways
    was fully populated. A gene-centric mine wants the gene-level link most of all.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Gene.symbol Gene.pathways.identifier Gene.pathways.name",
                      "Gene.symbol", "=", EXAMPLE_GENE)
    assert rows, (f"{EXAMPLE_GENE} has no pathways - has the reactome source postprocess "
                  "(-Pprocess=do-sources -Psource=reactome) run?")
    assert any(r[1] == EXAMPLE_PATHWAY for r in rows), (
        f"expected {EXAMPLE_PATHWAY} among {EXAMPLE_GENE}'s pathways, got {[r[1] for r in rows]}")


def test_pathway_descriptions_are_not_starved_by_source_priority():
    """A pathway carrying protein participants also carries its description.

    Regression guard for the source-priority bug fixed on 2026-09-21: genomic_priorities
    ranked the stock reactome source first for Pathway.description, but that source's
    converter never sets the field at all, so every pathway the stock source also touched
    silently lost the description that only rdfc2im's source provides - 2344 of 2883 pathways
    had none. Checking a pathway that BOTH sources contribute to is the whole point; a
    pathway only one source knows about would pass even with the bug present.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Pathway.identifier Pathway.name Pathway.description",
                      "Pathway.identifier", "=", EXAMPLE_PATHWAY)
    assert rows, f"{EXAMPLE_PATHWAY} not found"
    assert rows[0][2], (
        f"{EXAMPLE_PATHWAY} has protein participants but no description - "
        "check Pathway.description ordering in curation/priorities_override.properties")


def test_the_organism_has_its_names():
    """Organism 9606 carries name, shortName, genus and species (im-ore.16).

    The RDF Portal data gives a taxon id and nothing else, and stock reactome (loaded alongside
    ours) writes an Organism with a taxon id only; at the top rank of Organism.name its null
    stood over our value, so every list-widget title and the organism filter were blank.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Organism.taxonId Organism.name Organism.shortName Organism.genus Organism.species",
                      "Organism.taxonId", "=", "9606")
    assert len(rows) == 1, f"expected exactly one Organism 9606, got {rows}"
    assert rows[0] == ["9606", "Homo sapiens", "H. sapiens", "Homo", "sapiens"], rows[0]


def test_each_pathway_is_in_one_data_set():
    """A pathway belongs to one data set, not one per source that loads it (im-ore.10).

    rdfc2im's reactome source used its own data set title while stock reactome used
    "Reactome pathways data set", and DataSet merges on name, so every pathway sat in two: each
    enrichment row appeared twice and a data set filter matched half of them.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Pathway.identifier Pathway.dataSets.name", "Pathway.identifier", "=", EXAMPLE_PATHWAY)
    assert [r[1] for r in rows] == ["Reactome pathways data set"], rows


def test_each_chromosome_is_one_object_with_its_organism():
    """Chromosome 1 exists once, with an organism (im-ore.10).

    InterMine keys a chromosome on primaryIdentifier+organism and the sources gave none, so
    ncbigene's and ensembl's chromosome 1 never merged: the mine held every chromosome twice.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    rows = query_rows("Chromosome.primaryIdentifier Chromosome.organism.taxonId",
                      "Chromosome.primaryIdentifier", "=", "1")
    assert rows == [["1", "9606"]], rows


# ----------------------------------------------------------------- classic webapp UI
def test_classic_ui_webconfig_is_valid():
    """The classic webapp renders without the webconfig validation error.

    Not cosmetic: on 2026-09-21 this error threw a full Struts/Tiles stack trace on EVERY
    classic-UI page load, growing Tomcat's localhost log to 2.3GB, filling the Docker disk,
    and crashing Postgres mid-WAL-redo so it could not restart. A reduced mine must have its
    webconfig-model.xml trimmed of widgets whose data it does not load.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    try:
        body = _get(f"{MINE_BASE}/begin.do")
    except urllib.error.HTTPError as e:
        raise AssertionError(f"begin.do returned HTTP {e.code}") from e
    assert "webconfig-model.xml file is not valid" not in body, (
        "classic UI reports an invalid webconfig-model.xml - trim the widgets referencing "
        "classes/paths this build does not load (tools/reduce_mine.py webconfig)")


# ----------------------------------------------------------------- stock UniProt (--stock-sources) [im-9n4.6]
SWISSPROT_DATA_SET = "Swiss-Prot data set"   # UniprotConverter's own data set title


def stock_uniprot_loaded() -> bool:
    """The mine was built with the stock uniprot source: only its additions give Protein the
    isUniprotCanonical attribute. Without it these checks have nothing to check and skip."""
    try:
        cls = _get_json(f"{MINE_BASE}/service/model?format=json")["model"]["classes"]["Protein"]
    except Exception:
        return False
    return "isUniprotCanonical" in cls.get("attributes", {})


def query_rows_q(xml: str):
    """query_rows for a whole <query> (several constraints, outer joins)."""
    url = f"{MINE_BASE}/service/query/results?query={urllib.parse.quote(xml)}&format=json"
    payload = _get_json(url)
    if not payload.get("wasSuccessful", False):
        raise AssertionError(f"query failed: {payload.get('error')!r}\n  {xml}")
    return payload["results"]


def _swissprot_proteins(canonical: bool):
    return query_rows_q(
        '<query model="genomic" view="Protein.primaryAccession Protein.uniprotAccession Protein.isFragment '
        'Protein.canonicalProtein.primaryAccession Protein.sequence.length Protein.sequence.residues" '
        'sortOrder="Protein.primaryAccession asc">'
        '<join path="Protein.canonicalProtein" style="OUTER"/><join path="Protein.sequence" style="OUTER"/>'
        f'<constraint path="Protein.dataSets.name" op="=" value="{SWISSPROT_DATA_SET}"/>'
        f'<constraint path="Protein.isUniprotCanonical" op="=" value="{str(canonical).lower()}"/></query>')


def test_stock_uniprot_gives_a_swissprot_data_set():
    """The stock UniProt loader ran beside rdfc2im's uniprot (sources.yaml `alongside: [uniprot]`).

    Until im-9n4.6 the alongside declaration was not true: phase 7 kept only humanmine-items and
    reactome, so the DataSets listed only the RDF UniProt set.
    """
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_uniprot_loaded():
        return _skip("mine built without --stock-sources uniprot")
    rows = query_rows("DataSet.name DataSet.dataSource.name", "DataSet.name", "=", SWISSPROT_DATA_SET)
    assert rows == [[SWISSPROT_DATA_SET, "UniProt"]], rows


def test_swissprot_canonical_proteins_have_their_sequence():
    """Every Swiss-Prot canonical protein carries its sequence, is not a fragment, and is its own
    UniProt accession (the MSA viewer reads sequence.residues; it was empty before im-9n4.6).
    Canonical entries have no canonicalProtein, as on HumanMine (P10635 there has none)."""
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_uniprot_loaded():
        return _skip("mine built without --stock-sources uniprot")
    rows = _swissprot_proteins(True)
    assert len(rows) >= 100, f"only {len(rows)} Swiss-Prot canonical proteins for the panel"
    assert EXAMPLE_PROTEIN in {r[0] for r in rows}
    bad = [r[:5] for r in rows if not r[5] or r[4] != len(r[5]) or r[2] is not False or r[1] != r[0] or r[3]]
    assert not bad, f"{len(bad)} canonical proteins without sequence or with wrong flags: {bad[:5]}"


def test_swissprot_isoforms_point_at_their_canonical_protein():
    """Each isoform names its canonical protein (Protein.canonicalProtein, which the protein
    visualizer selects) and has the sequence uniprot-fasta loads from the varsplic file."""
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_uniprot_loaded():
        return _skip("mine built without --stock-sources uniprot")
    rows = _swissprot_proteins(False)
    assert rows, "no Swiss-Prot isoforms"
    assert f"{EXAMPLE_PROTEIN}-2" in {r[0] for r in rows}
    bad = [r[:5] for r in rows if r[3] != r[0].split("-")[0] or r[1] != r[3] or not r[5]]
    assert not bad, f"{len(bad)} isoforms with no canonical protein or no sequence: {bad[:5]}"


def test_the_example_protein_has_features_comments_and_keywords():
    """The stock loader's own content: features, comments and keywords (none come from RDF)."""
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_uniprot_loaded():
        return _skip("mine built without --stock-sources uniprot")
    for view in ("Protein.features.type", "Protein.comments.type", "Protein.keywords.name"):
        rows = query_rows(f"Protein.primaryAccession {view}", "Protein.primaryAccession", "=", EXAMPLE_PROTEIN)
        assert rows and any(r[1] for r in rows), f"{EXAMPLE_PROTEIN} has no {view}"


def test_one_protein_per_accession_and_one_gene_per_identifier():
    """Stock uniprot keys Protein on md5checksum+organism and Gene on the XML's GeneID; rdfc2im's
    hgnc and uniprot key Protein on primaryAccession and link genes by symbol (plan 50 risk 3).
    The merge must leave one object per key."""
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    for view, path in (("Protein.primaryAccession", "Protein.primaryAccession"),
                       ("Gene.primaryIdentifier", "Gene.primaryIdentifier"),
                       ("Gene.symbol", "Gene.organism.taxonId")):
        op, value = ("=", "9606") if path.endswith("taxonId") else ("IS NOT NULL", "")
        rows = query_rows_q(f'<query model="genomic" view="{view}">'
                            f'<constraint path="{path}" op="{op}"{f" value={chr(34)}{value}{chr(34)}" if value else ""}/>'
                            '</query>')
        seen, dups = set(), set()
        for (v,) in rows:
            if v is not None:
                (dups if v in seen else seen).add(v)
        assert not dups, f"{len(dups)} duplicate {view}: {sorted(dups)[:10]}"


# ----------------------------------------------------------------- stock ncbi-gff (--stock-sources) [im-9n4.9]
GFF_DATA_SET = "ncbi-gff"                    # project.xml gff3.dataSetTitle
RDF_GENE_DATA_SET = "NCBI Gene (RDF Portal)"  # the panel genes: rdfc2im's ncbigene source
# GRCh38 chromosome lengths (the RefSeq GFF's ##sequence-region lines; identical to HumanMine's own
# refSeqs.json, checked 18 Nov 2026)
GRCH38_LENGTHS = {
    "1": 248956422, "2": 242193529, "3": 198295559, "4": 190214555, "5": 181538259, "6": 170805979,
    "7": 159345973, "8": 145138636, "9": 138394717, "10": 133797422, "11": 135086622, "12": 133275309,
    "13": 114364328, "14": 107043718, "15": 101991189, "16": 90338345, "17": 83257441, "18": 80373285,
    "19": 58617616, "20": 64444167, "21": 46709983, "22": 50818468, "X": 156040895, "Y": 57227415}
# Panel genes the GRCh38 primary assembly does not carry: GSTT1 is annotated only on the alternate
# locus NT_187633.1 (the primary chr22 has the deletion allele), whose rows the loader drops.
NO_PRIMARY_LOCATION = {"GSTT1"}
PAX6 = ("PAX6", "5080", "11", 31789026, 31817961)


def stock_gff_loaded() -> bool:
    try:
        return bool(query_rows("DataSet.name", "DataSet.name", "=", GFF_DATA_SET))
    except Exception:
        return False


def _gff_skip():
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_gff_loaded():
        return _skip("mine built without --stock-sources ncbi-gff")
    return None


def test_every_panel_gene_has_a_chromosome_location():
    """Gene.chromosomeLocation for the panel (T1.4 gate): what JBrowse and the report page's
    location read. The only exceptions are genes the primary assembly lacks."""
    if (s := _gff_skip()) is not None:
        return s
    rows = query_rows_q(
        '<query model="genomic" view="Gene.symbol Gene.chromosomeLocation.start Gene.chromosome.primaryIdentifier">'
        '<join path="Gene.chromosomeLocation" style="OUTER"/><join path="Gene.chromosome" style="OUTER"/>'
        f'<constraint path="Gene.dataSets.name" op="=" value="{RDF_GENE_DATA_SET}"/></query>')
    assert len(rows) >= 100, f"only {len(rows)} panel genes"
    missing = {r[0] for r in rows if r[1] is None}
    assert missing == NO_PRIMARY_LOCATION, f"panel genes without a location: {sorted(missing)}"
    assert all(r[2] in GRCH38_LENGTHS for r in rows if r[1] is not None)


def test_chromosomes_have_their_grch38_lengths_and_no_refseq_names():
    """Chromosome.length comes from the GFF's ##sequence-region lines (ncbi-gff-lengths), one
    Chromosome per name: the loader's 1..22, X, Y merged with the rdfc2im ones, no NC_ accession
    names and no MT (the loader maps none)."""
    if (s := _gff_skip()) is not None:
        return s
    rows = query_rows("Chromosome.primaryIdentifier Chromosome.length", "Chromosome.organism.taxonId", "=", "9606")
    names = [r[0] for r in rows]
    assert len(names) == len(set(names)), f"duplicate chromosomes: {sorted(names)}"
    assert {r[0]: r[1] for r in rows} == GRCH38_LENGTHS, rows


def test_the_example_gene_model_has_transcripts_and_exons():
    """PAX6 at HumanMine's coordinates, with its RefSeq transcripts and exons (HumanMine, RefSeq
    2021: 53 transcripts, 637 exons)."""
    if (s := _gff_skip()) is not None:
        return s
    sym, pid, chrom, start, end = PAX6
    loc = query_rows("Gene.primaryIdentifier Gene.chromosome.primaryIdentifier Gene.chromosomeLocation.start "
                     "Gene.chromosomeLocation.end Gene.chromosomeLocation.strand", "Gene.symbol", "=", sym)
    assert loc == [[pid, chrom, start, end, "-1"]], loc
    tx = query_rows("Gene.transcripts.primaryIdentifier", "Gene.symbol", "=", sym)
    ex = query_rows("Gene.transcripts.exons.primaryIdentifier", "Gene.symbol", "=", sym)
    assert len(tx) >= 40 and len({r[0] for r in ex}) >= 300, (len(tx), len(ex))


def test_jbrowse_serves_the_chromosomes_and_the_example_gene():
    """/service/jbrowse/config/9606/seq/refSeqs.json lists the chromosomes with a length > 0
    (Config.serveRefSeqs; it was a 404 "No Chromosomes on 9606" before), and a features request
    for PAX6's region returns the gene."""
    if (s := _gff_skip()) is not None:
        return s
    refs = _get_json(f"{MINE_BASE}/service/jbrowse/config/9606/seq/refSeqs.json")
    assert {r["name"]: r["end"] - r["start"] for r in refs} == GRCH38_LENGTHS, refs
    sym, pid, chrom, start, end = PAX6
    feats = _get_json(f"{MINE_BASE}/service/jbrowse/9606/features/{chrom}?start={start}&end={end}&type=Gene")
    names = {f.get("symbol") or f.get("name") for f in feats.get("features", [])}
    assert sym in names, feats


# ----------------------------------------------------------------- stock go-annotation, interpro-go [im-9n4.11]
GO_DATA_SET = "GO Annotation data set"       # GoConverter's data set title


def stock_go_loaded() -> bool:
    try:
        return bool(query_rows("DataSet.name", "DataSet.name", "=", GO_DATA_SET))
    except Exception:
        return False


def _go_skip():
    if not mine_up():
        return _skip(f"live checks off or no mine at {MINE_BASE} (make test-live)")
    if not stock_go_loaded():
        return _skip("mine built without --stock-sources go-annotation")
    return None


def test_the_example_genes_have_go_annotations_copied_from_their_proteins():
    """GoPostprocess (do-sources) copies Protein annotations to the Gene: CYP2D6 has 33 distinct terms in
    goa_human, PAX6 57 (HumanMine's 79 is an older release)."""
    if (s := _go_skip()) is not None:
        return s
    for sym, floor in ((EXAMPLE_GENE, 25), ("PAX6", 40)):
        rows = query_rows("Gene.symbol Gene.goAnnotation.ontologyTerm.identifier", "Gene.symbol", "=", sym)
        assert len({r[1] for r in rows}) >= floor, (sym, len(rows))


def test_go_terms_are_not_duplicated_beside_the_rdf_go_source():
    """go-annotation and interpro-go key GOTerm on identifier, as the RDF go source does: one object each."""
    if (s := _go_skip()) is not None:
        return s
    ids = [r[0] for r in query_rows("GOTerm.identifier", "GOTerm.identifier", "CONTAINS", "GO:")]
    assert len(ids) > 40000 and len(ids) == len(set(ids)), (len(ids), len(set(ids)))


def test_go_annotation_makes_no_stub_proteins():
    """The loader also creates a Protein for every UniProt 'with' value; none may lack an organism."""
    if (s := _go_skip()) is not None:
        return s
    rows = query_rows_q('<query model="genomic" view="Protein.primaryAccession"><join path="Protein.organism" style="OUTER"/>'
                        '<constraint path="Protein.organism" op="IS NULL"/></query>')
    assert rows == [], rows[:5]


def test_the_go_enrichment_widget_is_served_and_enriches_a_list_of_panel_genes():
    """go_enrichment_for_gene stayed dropped from the web config of a rebuilt mine until build_dbmodel put the
    upstream file back before reducing it."""
    if (s := _go_skip()) is not None:
        return s
    import base64
    widgets = {w["name"] for w in _get_json(f"{MINE_BASE}/service/widgets?format=json")["widgets"]}
    assert "go_enrichment_for_gene" in widgets, widgets
    auth = {"Authorization": "Basic " + base64.b64encode(b"superuser@intermine.org:intermine").decode()}
    name = "tmp_live_go_enrichment"

    def call(url, data=None, method=None):
        req = urllib.request.Request(url, data=data, method=method, headers={**auth, "Content-Type": "text/plain"})
        return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())

    try:
        r = call(f"{MINE_BASE}/service/lists?" + urllib.parse.urlencode({"name": name, "type": "Gene", "format": "json"}),
                 b"CYP2D6\nCYP2C9\nCYP2C19\nCYP3A4\nCYP1A2\nPAX6", "POST")
        assert r["wasSuccessful"] and r["listSize"] == 6, r
        e = call(f"{MINE_BASE}/service/list/enrichment?" + urllib.parse.urlencode(
            {"widget": "go_enrichment_for_gene", "list": name, "correction": "Holm-Bonferroni", "maxp": "0.05",
             "filter": "biological_process", "format": "json"}))
        assert e["wasSuccessful"] and e["results"], e
    finally:
        try:
            call(f"{MINE_BASE}/service/lists?" + urllib.parse.urlencode({"name": name, "format": "json"}), None, "DELETE")
        except Exception:
            pass
