"""im-9n4.55: Ensembl genes join NCBI genes by a stable cross-reference, not by symbol.

The ensembl source's Gene items carry an Ensembl gene id (secondaryIdentifier) and a label
(symbol) but no Entrez id, so with the Gene keys of the type file they merged into whatever NCBI
gene had the same symbol or the same Ensembl id.  At full scope 845 labels are shared by several
Ensembl genes and many have none.  items.join_on_xref gives each Ensembl gene the Entrez id the
cross-references name (HGNC first, then NCBI, then Ensembl's own ncbigene xref), and ensembl's own
keys are then the Entrez id alone."""
import os
import random
import textwrap

import yaml

from rdfc2im.model import InterMineModel
from rdfc2im.items import ItemStore, emit_items, join_on_xref, xref_pairs_from_items, xref_pairs_from_raw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL = """<model name="genomic" package="org.intermine.model.bio">
<class name="BioEntity" is-interface="true">
  <attribute name="primaryIdentifier" type="java.lang.String"/>
  <attribute name="secondaryIdentifier" type="java.lang.String"/>
  <attribute name="symbol" type="java.lang.String"/>
  <reference name="organism" referenced-type="Organism"/>
  <collection name="synonyms" referenced-type="Synonym" reverse-reference="subject"/>
</class>
<class name="Gene" extends="BioEntity" is-interface="true">
  <attribute name="typeOfGene" type="java.lang.String"/>
</class>
<class name="Organism" is-interface="true"><attribute name="taxonId" type="java.lang.String"/></class>
<class name="Synonym" is-interface="true"><attribute name="value" type="java.lang.String"/><reference name="subject" referenced-type="BioEntity"/></class>
</model>"""
KEYS = ("Gene.key_primaryidentifier=primaryIdentifier\nGene.key_secondaryidentifier=secondaryIdentifier\n"
        "Organism.key=taxonId\nSynonym.key_synonym=subject, value\n")


def model(tmp_path):
    (tmp_path / "core.xml").write_text(MODEL)
    (tmp_path / "x_keys.properties").write_text(KEYS)
    m = InterMineModel(); m.load_xml(str(tmp_path / "core.xml")); m.load_keys(str(tmp_path / "x_keys.properties"))
    m.finalize(); m.live = None
    return m


def store_of(m, genes):
    """genes: [(ensembl id, symbol or None)] -> an ItemStore of ensembl-like Gene items."""
    st = ItemStore(m)
    org = st.get("Organism", {"taxonId": "9606"})
    for ensg, sym in genes:
        k = st.get("Gene", {"secondaryIdentifier": ensg, "symbol": sym or ""})
        st.link(k, "organism", org)
    return st


def gene(st, ensg):
    return next((it for it in st.items.values() if it.cls == "Gene" and it.attrs.get("secondaryIdentifier") == ensg), None)


KNOWN = {"3105", "3106", "5080", "1565", "54658", "54576", "7", "8", "9"}


def test_a_shared_symbol_joins_only_the_gene_the_cross_reference_names(tmp_path):
    """HLA-A: the primary-assembly gene and an alternative-haplotype copy carry the same label.
    The old symbol key put both on Entrez 3105; the cross-reference names only one."""
    st = store_of(model(tmp_path), [("ENSG00000206503", "HLA-A"), ("ENSG00000223980", "HLA-A")])
    rep = join_on_xref(st, levels=[("hgnc", [("ENSG00000206503", "3105")])], known=KNOWN)
    assert gene(st, "ENSG00000206503").attrs["primaryIdentifier"] == "3105"
    assert gene(st, "ENSG00000223980") is None, "the haplotype copy is not merged and not loaded"
    row = next(r for r in rep if r["ensembl_id"] == "ENSG00000223980")
    assert row["status"] == "unmatched" and row["symbol"] == "HLA-A"


def test_a_symbol_alone_never_joins(tmp_path):
    """No cross-reference, but its symbol is an NCBI gene's: still not joined (the finding)."""
    st = store_of(model(tmp_path), [("ENSG00000007372", "PAX6")])
    rep = join_on_xref(st, levels=[("hgnc", []), ("ncbigene", [])], known=KNOWN)
    assert gene(st, "ENSG00000007372") is None
    assert [r["status"] for r in rep] == ["unmatched"]


def test_a_gene_without_a_symbol_joins_by_its_cross_reference(tmp_path):
    st = store_of(model(tmp_path), [("ENSG00000100197", None)])
    rep = join_on_xref(st, levels=[("ncbigene", [("ENSG00000100197", "1565")])], known=KNOWN)
    assert gene(st, "ENSG00000100197").attrs["primaryIdentifier"] == "1565"
    assert rep[0]["status"] == "joined" and rep[0]["via"] == "ncbigene"


def test_disagreeing_sources_hgnc_first_then_ncbi_then_ensembl(tmp_path):
    """The precedence is the order of Gene.secondaryIdentifier in priorities_override: the
    Entrez gene that ends up showing this Ensembl id is the one it joins."""
    st = store_of(model(tmp_path), [("ENSG_A", "A"), ("ENSG_B", "B")])
    rep = join_on_xref(st, levels=[("hgnc", [("ENSG_A", "7")]),
                                   ("ncbigene", [("ENSG_A", "8"), ("ENSG_B", "9")]),
                                   ("ensembl", [("ENSG_B", "7")])], known=KNOWN)
    assert gene(st, "ENSG_A").attrs["primaryIdentifier"] == "7", "hgnc over ncbigene"
    assert gene(st, "ENSG_B").attrs["primaryIdentifier"] == "9", "ncbigene over Ensembl's own xref"
    by = {r["ensembl_id"]: r for r in rep}
    assert by["ENSG_A"]["via"] == "hgnc" and "ncbigene: 8" in by["ENSG_A"]["disagree"]
    assert by["ENSG_B"]["via"] == "ncbigene" and "ensembl: 7" in by["ENSG_B"]["disagree"]


def test_one_ensembl_gene_to_several_ncbi_genes_is_not_joined(tmp_path):
    st = store_of(model(tmp_path), [("ENSG_A", "A")])
    rep = join_on_xref(st, levels=[("ensembl", [("ENSG_A", "7"), ("ENSG_A", "8")])], known=KNOWN)
    assert gene(st, "ENSG_A") is None
    assert rep[0]["status"] == "ambiguous" and rep[0]["entrez"] == "7,8"


def test_several_ensembl_genes_to_one_ncbi_gene(tmp_path):
    """Within one source: none wins (no principled choice).  Across sources: the higher one's
    pair stands, and the lower one's second Ensembl gene is not put on the same NCBI gene."""
    st = store_of(model(tmp_path), [("ENSG_A", "A"), ("ENSG_B", "A"), ("ENSG_C", "C"), ("ENSG_D", "C")])
    rep = join_on_xref(st, levels=[("hgnc", [("ENSG_C", "8")]),
                                   ("ensembl", [("ENSG_A", "7"), ("ENSG_B", "7"), ("ENSG_D", "8")])], known=KNOWN)
    by = {r["ensembl_id"]: r for r in rep}
    assert by["ENSG_A"]["status"] == by["ENSG_B"]["status"] == "ambiguous"
    assert gene(st, "ENSG_A") is None and gene(st, "ENSG_B") is None
    assert gene(st, "ENSG_C").attrs["primaryIdentifier"] == "8"
    assert gene(st, "ENSG_D") is None and by["ENSG_D"]["status"] == "unmatched"
    assert "ENSG_C" in by["ENSG_D"]["reason"]


def test_a_cross_reference_to_an_ncbi_gene_not_in_the_build_is_unmatched(tmp_path):
    st = store_of(model(tmp_path), [("ENSG_A", "A")])
    rep = join_on_xref(st, levels=[("ensembl", [("ENSG_A", "999999")])], known=KNOWN)
    assert gene(st, "ENSG_A") is None
    assert rep[0]["status"] == "unmatched" and "999999" in rep[0]["reason"]


def test_an_unmatched_gene_goes_with_the_items_that_hang_only_off_it(tmp_path):
    m = model(tmp_path)
    st = store_of(m, [("ENSG_A", "A"), ("ENSG_B", "B")])
    for ensg in ("ENSG_A", "ENSG_B"):
        gk = next(k for k, it in st.items.items() if it.attrs.get("secondaryIdentifier") == ensg)
        sk = st.get("Synonym", {"value": f"syn-{ensg}"})
        st.link(gk, "synonyms", sk)
    join_on_xref(st, levels=[("hgnc", [("ENSG_A", "7")])], known=KNOWN)
    vals = {it.attrs.get("value") for it in st.items.values() if it.cls == "Synonym"}
    assert vals == {"syn-ENSG_A"}
    assert any(it.cls == "Organism" for it in st.items.values()), "shared items stay"


def test_the_alternative_keeps_unmatched_genes_as_genes_of_their_own(tmp_path):
    """unmatched: keep (Gos's decision, not the default): a Gene keyed on its Ensembl id."""
    st = store_of(model(tmp_path), [("ENSG_A", "A"), ("ENSG_B", "B")])
    rep = join_on_xref(st, levels=[("hgnc", [("ENSG_A", "7")])], known=KNOWN, unmatched="keep")
    assert gene(st, "ENSG_B").attrs["primaryIdentifier"] == "ENSG_B"
    assert {r["ensembl_id"]: r["status"] for r in rep} == {"ENSG_A": "joined", "ENSG_B": "kept"}


def test_the_join_is_deterministic(tmp_path):
    genes = [(f"ENSG_{i}", f"S{i % 3}") for i in range(12)]
    pairs = [(f"ENSG_{i}", str(i % 5 + 1)) for i in range(12)] + [("ENSG_3", "9")]
    outs = []
    for seed in range(4):
        g, p = genes[:], pairs[:]
        random.Random(seed).shuffle(g); random.Random(seed + 10).shuffle(p)
        st = store_of(model(tmp_path), g)
        rep = join_on_xref(st, levels=[("ensembl", p)], known={str(i) for i in range(1, 10)})
        joined = sorted((it.attrs["secondaryIdentifier"], it.attrs.get("primaryIdentifier"))
                        for it in st.items.values() if it.cls == "Gene")
        outs.append((joined, rep))
    assert all(o == outs[0] for o in outs)
    assert [r["ensembl_id"] for r in outs[0][1]] == sorted(r["ensembl_id"] for r in outs[0][1])


def test_pairs_are_read_from_the_written_items_and_the_raw_xref_table(tmp_path):
    items = tmp_path / "hgnc.xml"
    items.write_text('<?xml version="1.0"?>\n<items>\n'
                     '<item id="0_1" class="Gene" implements=""><attribute name="primaryIdentifier" value="5080"/>'
                     '<attribute name="secondaryIdentifier" value="ENSG00000007372"/></item>\n'
                     '<item id="0_2" class="Gene" implements=""><attribute name="primaryIdentifier" value="6052"/></item>\n'
                     '<item id="0_3" class="Protein" implements=""><attribute name="primaryIdentifier" value="P1"/>'
                     '<attribute name="secondaryIdentifier" value="X"/></item>\n</items>\n')
    pairs, known = xref_pairs_from_items(str(items), "Gene", "primaryIdentifier", "secondaryIdentifier")
    assert pairs == [("ENSG00000007372", "5080")] and known == {"5080", "6052"}
    raw = tmp_path / "main_ensg_xref.tsv"
    raw.write_text('?ensg_id\t?ensg_taxonomy\t?ensg_xref\n'
                   '"ENSG00000007372"\t<http://identifiers.org/taxonomy/9606>\t<http://identifiers.org/ncbigene/5080>\n'
                   '"ENSG00000007372"\t<http://identifiers.org/taxonomy/9606>\t<http://identifiers.org/hgnc/HGNC:8620>\n')
    assert xref_pairs_from_raw(str(raw), "ensg_id", "ensg_xref", "http://identifiers.org/ncbigene/") == \
        [("ENSG00000007372", "5080")]
    assert xref_pairs_from_raw(str(tmp_path / "missing.tsv"), "ensg_id", "ensg_xref", "x") == []


def _ensembl_out(tmp_path, ncbi_items):
    """An out/ tree with ncbigene items written and an ensembl source ready for emit_items."""
    (tmp_path / "out" / "ncbigene" / "items").mkdir(parents=True)
    (tmp_path / "out" / "ncbigene" / "items" / "ncbigene.xml").write_text(ncbi_items)
    out = tmp_path / "out" / "ensembl"
    (out / "tsv").mkdir(parents=True); (out / "raw").mkdir()
    (out / "columns.tsv").write_text(textwrap.dedent("""\
    table\tposition\tcolumn\tvariable\tim_class\tim_field\ttransform\tfilter\tvalue\tkind\tvia\tstatus\trequired
    main\t0\tid\tid\tGene\tsecondaryIdentifier\t\t\t\tliteral\t\tsure\tyes
    main\t1\tsym\tsym\tGene\tsymbol\t\t\t\tliteral\t\tsure\tno
    main\t2\tc\t\tOrganism\ttaxonId\t\t\t9606\tconst\tGene.organism\tsure\tno
    """))
    (out / "tsv" / "main.tsv").write_text("Gene.secondaryIdentifier\tGene.symbol\tOrganism.taxonId\n"
                                          "ENSG00000206503\tHLA-A\t9606\nENSG00000223980\tHLA-A\t9606\n"
                                          "ENSG00000242366\tUGT1A1\t9606\n")
    (out / "raw" / "main_ensg_xref.tsv").write_text(
        '?ensg_id\t?ensg_xref\n"ENSG00000242366"\t<http://identifiers.org/ncbigene/54576>\n')
    return out


def test_emit_items_joins_writes_the_report_and_counts_it(tmp_path):
    m = model(tmp_path)
    out = _ensembl_out(tmp_path, '<?xml version="1.0"?>\n<items>\n'
                       '<item id="0_1" class="Gene" implements=""><attribute name="primaryIdentifier" value="3105"/>'
                       '<attribute name="symbol" value="HLA-A"/><attribute name="secondaryIdentifier" value="ENSG00000206503"/></item>\n'
                       '<item id="0_2" class="Gene" implements=""><attribute name="primaryIdentifier" value="54576"/>'
                       '<attribute name="symbol" value="UGT1A8"/></item>\n'
                       '<item id="0_3" class="Gene" implements=""><attribute name="primaryIdentifier" value="54658"/>'
                       '<attribute name="symbol" value="UGT1A1"/></item>\n</items>\n')
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml")))["ensembl"]
    notes = []
    emit_items(m, str(out), "ensembl", cfg, log=notes.append)
    xml = (out / "items" / "ensembl.xml").read_text()
    assert 'value="ENSG00000223980"' not in xml, "the unmatched haplotype copy is left out"
    assert 'name="primaryIdentifier" value="3105"' in xml
    # ENSG00000242366 is labelled UGT1A1 but is UGT1A8 (its own description says so): by symbol it
    # went onto UGT1A1, by its cross-reference onto UGT1A8, and it does not carry the other's symbol
    chunk = xml[xml.index('value="ENSG00000242366"'):]
    chunk = chunk[:chunk.index("</item>")]
    assert 'name="primaryIdentifier" value="54576"' in chunk and "UGT1A1" not in chunk
    rep = (out / "items" / "ensembl_xref_join.tsv").read_text().splitlines()
    assert rep[0].split("\t")[:3] == ["ensembl_id", "symbol", "status"]
    assert len(rep) == 4 and sum("\tunmatched\t" in r for r in rep) == 1
    assert any("1 of 3 Ensembl genes not joined" in n for n in notes), notes


def test_ensembl_is_keyed_on_the_entrez_id_alone():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml")))["ensembl"]
    assert cfg["own_keys"] == {"Gene": ["primaryIdentifier"]}
    assert cfg["xref_join"]["sources"] == ["hgnc", "ncbigene"]
    assert cfg["xref_join"].get("unmatched", "drop") == "drop"


def test_full_build_no_longer_warns_ensembl_off_at_full_scope():
    sh = open(os.path.join(ROOT, "tools", "full-build.sh")).read()
    assert "leave it out of --sources for now" not in sh
