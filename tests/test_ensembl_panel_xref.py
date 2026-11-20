"""im-9n4.59: the gene-panel build picks its Ensembl genes by cross-reference, not by label.

scope.resolve_ensembl_symbols took the first Ensembl gene whose rdfs:label is the panel symbol.  For
UGT1A1 (NCBI 54658, Ensembl ENSG00000241635) that was ENSG00000242366, which Ensembl's RDF labels
"UGT1A1" but which is UGT1A8 (NCBI 54576).  Since im-9n4.55 the Ensembl genes join NCBI genes by
cross-reference (items.join_on_xref), so that gene's data went to UGT1A8 and UGT1A1 had no Ensembl
data at all.  The panel's Ensembl ids are now the ones the same rule pairs with the panel's NCBI
genes: HGNC's Ensembl id, then NCBI's, then Ensembl's own ncbigene cross-reference, one-to-one at the
level that decides.  Nothing here touches the network."""
import os
import random
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from rdfc2im import scope  # noqa: E402
from rdfc2im.items import ItemStore, join_on_xref, xref_ids_for  # noqa: E402
from rdfc2im.scope import ensembl_ncbigene_xrefs, ensembl_xref_resolver, resolve_gene_ids  # noqa: E402

from test_ensembl_xref import model  # noqa: E402

UGT_HGNC = [("ENSG00000241635", "54658"), ("ENSG00000242366", "54576")]
KNOWN = {"54658", "54576", "1565", "7", "8", "9"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RDFC2IM_OFFLINE", "RDFC2IM_RESOLVER_REFRESH", "RDFC2IM_RESOLVER_CACHE"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- the rule

def test_ugt1a1_gets_its_own_ensembl_gene_not_the_one_labelled_with_its_symbol():
    levels = [("hgnc", UGT_HGNC), ("ncbigene", UGT_HGNC), ("ensembl", UGT_HGNC)]
    assert xref_ids_for(levels, KNOWN, {"54658"}) == ["ENSG00000241635"]
    assert xref_ids_for(levels, KNOWN, {"54658", "54576"}) == ["ENSG00000241635", "ENSG00000242366"]


def test_hgnc_then_ncbi_then_ensembls_own_cross_reference():
    levels = [("hgnc", [("ENSG_A", "7")]),
              ("ncbigene", [("ENSG_B", "7"), ("ENSG_C", "8")]),
              ("ensembl", [("ENSG_D", "8"), ("ENSG_E", "9")])]
    assert xref_ids_for(levels, KNOWN, {"7"}) == ["ENSG_A"], "hgnc over ncbigene"
    assert xref_ids_for(levels, KNOWN, {"8"}) == ["ENSG_C"], "ncbigene over Ensembl's own"
    assert xref_ids_for(levels, KNOWN, {"9"}) == ["ENSG_E"], "Ensembl's own when nothing higher names one"


def test_an_ambiguous_cross_reference_selects_nothing():
    one_to_two = [("ensembl", [("ENSG_A", "7"), ("ENSG_A", "8")])]
    two_to_one = [("ensembl", [("ENSG_A", "7"), ("ENSG_B", "7")])]
    assert xref_ids_for(one_to_two, KNOWN, {"7"}) == []
    assert xref_ids_for(two_to_one, KNOWN, {"7"}) == []


def test_a_cross_reference_to_a_gene_not_in_the_build_selects_nothing():
    assert xref_ids_for([("ensembl", [("ENSG_A", "999999")])], KNOWN, {"999999"}) == []


def test_the_selection_is_deterministic():
    pairs = [(f"ENSG_{i}", str(i % 5 + 1)) for i in range(12)] + [("ENSG_3", "9")]
    outs = set()
    for seed in range(5):
        p = pairs[:]
        random.Random(seed).shuffle(p)
        outs.add(tuple(xref_ids_for([("ensembl", p)], {str(i) for i in range(1, 10)}, {"1", "2", "9"})))
    assert len(outs) == 1


def test_the_selected_genes_are_exactly_those_the_join_puts_on_panel_genes(tmp_path):
    """The fetch and the join use one rule: every gene fetched joins a panel gene, and every
    Ensembl gene the join would put on a panel gene is fetched."""
    rnd = random.Random(7)
    known = {str(i) for i in range(1, 30)}
    for _ in range(20):
        levels = [(name, [(f"ENSG_{rnd.randrange(40)}", str(rnd.randrange(1, 35))) for _ in range(25)])
                  for name in ("hgnc", "ncbigene", "ensembl")]
        panel = {str(i) for i in rnd.sample(range(1, 30), 8)}
        chosen = xref_ids_for(levels, known, panel)
        st = ItemStore(model(tmp_path))
        for g in sorted({g for _, ps in levels for g, _ in ps}):
            st.get("Gene", {"secondaryIdentifier": g})
        rows = join_on_xref(st, levels, known)
        joined = sorted(r["ensembl_id"] for r in rows if r["status"] == "joined" and r["entrez"] in panel)
        assert chosen == joined


# ---------------------------------------------------------------- Ensembl's own cross-references

def test_ensembls_own_cross_references_come_from_one_query_by_ncbi_gene(monkeypatch):
    seen = {}

    def fake(q, ep, timeout):
        seen.update(q=q, ep=ep)
        return (b'"ensg_id"\t"xref"\n"ENSG00000242366"\t"http://identifiers.org/ncbigene/54576"\n'
                b'"ENSG00000241635"\t"http://identifiers.org/ncbigene/54658"\n', "text/tab-separated-values", None)
    monkeypatch.setattr(scope, "_fetch_once", fake)
    got = ensembl_ncbigene_xrefs(["54658", "54576"], "9606")
    assert got == [("ENSG00000241635", "54658"), ("ENSG00000242366", "54576")]
    assert seen["ep"] == scope.ENSEMBL_ENDPOINT
    q = seen["q"]
    assert "<http://identifiers.org/ncbigene/54576> <http://identifiers.org/ncbigene/54658>" in q, "sorted VALUES"
    assert "taxonomy:9606" in q and "FROM" not in q, "no FROM: the endpoint's VALUES + taxonomy quirk"
    assert "rdfs:label" not in q, "never by label"
    assert ensembl_ncbigene_xrefs([], "9606") == []


def test_a_failed_query_is_an_error_not_an_empty_answer(monkeypatch):
    monkeypatch.setattr(scope, "_fetch_once", lambda q, ep, t: (None, None, "HTTP 503"))
    with pytest.raises(RuntimeError, match="503"):
        ensembl_ncbigene_xrefs(["54658"], "9606")


# ---------------------------------------------------------------- the resolver the build uses

def _items(path, pairs, extra_known=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [f'<item id="0_{i}" class="Gene" implements=""><attribute name="primaryIdentifier" value="{e}"/>'
            + (f'<attribute name="secondaryIdentifier" value="{g}"/>' if g else "") + "</item>"
            for i, (g, e) in enumerate(list(pairs) + [(None, k) for k in extra_known], 1)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?>\n<items>\n' + "\n".join(rows) + "\n</items>\n")


def test_the_resolver_reads_hgnc_and_ncbigene_items_and_asks_ensembl_for_the_rest(tmp_path):
    out = str(tmp_path / "out")
    _items(os.path.join(out, "hgnc", "items", "hgnc.xml"), UGT_HGNC)
    _items(os.path.join(out, "ncbigene", "items", "ncbigene.xml"), [("ENSG00000100197", "1565")], ["54658", "54576"])
    asked = []

    def own(entrez, taxon):
        asked.append((sorted(entrez), taxon))
        return [("ENSG_OWN", "7"), ("ENSG00000242366", "54658")]   # a lower level that disagrees: hgnc stands
    r = ensembl_xref_resolver(["54658", "1565", "7"], out, ["hgnc", "ncbigene"], own=own)
    assert r.__name__ == "resolve_ensembl_xref"
    # 7 is not a gene of the build (no ncbigene/hgnc item has it): Ensembl's own pair cannot target it
    assert r(["UGT1A1", "CYP2D6", "X"], taxon="9606") == ["ENSG00000100197", "ENSG00000241635"]
    assert asked == [(["1565", "54658", "7"], "9606")]


def test_the_resolver_goes_through_the_lookup_cache_under_its_own_name(tmp_path):
    out, d = str(tmp_path / "out"), str(tmp_path / "lookup")
    _items(os.path.join(out, "hgnc", "items", "hgnc.xml"), UGT_HGNC)
    r = ensembl_xref_resolver(["54658"], out, ["hgnc", "ncbigene"], own=lambda e, t: [])
    assert resolve_gene_ids(r, ["UGT1A1"], "9606", d) == ["ENSG00000241635"]
    (name,) = os.listdir(d)
    assert name.startswith("resolve_ensembl_xref-9606-"), "a new cache file: the old symbol answers are not reused"


def test_the_build_wires_the_cross_reference_resolver_for_ensembl(monkeypatch, tmp_path):
    from rdfc2im import cli
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml")))
    assert cfg["ensembl"]["gene_scope_resolver"] == "xref_join"
    calls = []

    def resolve_ncbigene_symbols(symbols, taxon="9606"):
        return ["54658"]
    monkeypatch.setattr(cli, "resolve_ncbigene_symbols", resolve_ncbigene_symbols)
    monkeypatch.setattr(cli, "ensembl_ncbigene_xrefs", lambda e, t: calls.append(e) or [])
    out = str(tmp_path / "out")
    _items(os.path.join(out, "hgnc", "items", "hgnc.xml"), UGT_HGNC)
    ids = cli.source_gene_ids("ensembl", cfg["ensembl"], ["UGT1A1"], "9606", str(tmp_path / "lookup"), out)
    assert ids == ["ENSG00000241635"] and calls == [["54658"]]
    names = sorted(os.listdir(tmp_path / "lookup"))
    assert [n.split("-")[0] for n in names] == ["resolve_ensembl_xref", "resolve_ncbigene_symbols"]


def test_the_other_sources_keep_their_resolvers(monkeypatch, tmp_path):
    from rdfc2im import cli
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml")))
    def resolve_ncbigene_symbols(symbols, taxon="9606"):
        return ["1"]

    def resolve_ensembl_symbols(symbols, taxon="9606"):
        return ["ENSG_SYM"]
    monkeypatch.setattr(cli, "resolve_ncbigene_symbols", resolve_ncbigene_symbols)
    monkeypatch.setattr(cli, "resolve_ensembl_symbols", resolve_ensembl_symbols)
    lk, out = str(tmp_path / "lookup"), str(tmp_path / "out")
    assert cli.source_gene_ids("ncbigene", cfg["ncbigene"], ["A"], "9606", lk, out) == ["1"]
    assert cli.source_gene_ids("gwascatalog", cfg["gwascatalog"], ["A"], "9606", lk, out) == ["ENSG_SYM"]
    assert cli.source_gene_ids("uniprot", cfg["uniprot"], ["A"], "9606", lk, out) == ["A"]
    assert cli.source_gene_ids("go", cfg["go"], ["A"], "9606", lk, out) == []


# ---------------------------------------------------------------- the cache and the stock id sets

def test_the_ensembl_panel_group_is_keyed_on_the_selection_rule():
    """The cached ensembl group of a panel build was fetched for the label-chosen ids: its key must
    change, or a --use-cached-data build restores the old cut under the new rule."""
    sh = open(os.path.join(ROOT, "tools", "full-build.sh"), encoding="utf-8").read()
    assert "[ensembl]=xref" in sh
    body = sh[sh.index("cache_meta_for() {"):]
    body = body[:body.index("\n}\n")]
    assert "gene_select=" in body and "GENE_SELECT" in body


def test_the_stock_id_sets_read_the_cross_reference_answer_too(tmp_path):
    import hashlib
    import subset_raw
    key = hashlib.md5("A\nB".encode()).hexdigest()
    (tmp_path / f"resolve_ensembl_xref-9606-{key}.txt").write_text("ENSG_X\n")
    (tmp_path / f"resolve_ensembl_symbols-9606-{key}.txt").write_text("ENSG_S\n")
    found = subset_raw._read_lookup(str(tmp_path), ["B", "A"], "9606")
    assert found["ensembl"][1] == {"ENSG_X", "ENSG_S"}
