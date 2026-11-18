"""RDF UniProt sequences [im-9n4.32]: model additions, node constraints, the `default:` transform,
sequence lengths in the items, a source's own keys for a class no keys file declares, and the
guards that keep a TrEMBL entry from merging into another protein with the same sequence."""
import hashlib
import os
import textwrap

import yaml

from rdfc2im.items import ItemStore
from rdfc2im.mapping import Knowledge, translate
from rdfc2im.model import InterMineModel
from rdfc2im.project import source_keys
from rdfc2im.rdfconfig import add_predicates, load_config
from rdfc2im.sparql import QueryBuilder, query_rows
from rdfc2im.tsv import apply_transform

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL = """<model name="genomic" package="org.intermine.model.bio">
<class name="Protein" is-interface="true">
  <attribute name="primaryAccession" type="java.lang.String"/>
  <attribute name="md5checksum" type="java.lang.String"/>
  <attribute name="length" type="java.lang.Integer"/>
  <attribute name="isFragment" type="java.lang.Boolean"/>
  <attribute name="molecularWeight" type="java.lang.Integer"/>
  <reference name="sequence" referenced-type="Sequence"/>
  <reference name="organism" referenced-type="Organism"/>
</class>
<class name="Sequence" is-interface="true">
  <attribute name="residues" type="java.lang.String"/>
  <attribute name="length" type="java.lang.Integer"/>
  <attribute name="md5checksum" type="java.lang.String"/>
</class>
<class name="Organism" is-interface="true"><attribute name="taxonId" type="java.lang.String"/></class>
</model>"""
KEYS = ("Protein.key_primaryacc=primaryAccession\nProtein.key_md5=md5checksum, organism\n"
        "Organism.key_taxonid=taxonId\n")


def make_model(tmp_path):
    (tmp_path / "core.xml").write_text(MODEL)
    (tmp_path / "x_keys.properties").write_text(KEYS)
    m = InterMineModel(); m.load_xml(str(tmp_path / "core.xml")); m.load_keys(str(tmp_path / "x_keys.properties"))
    m.finalize(); m.live = None
    return m


def make_cfg(tmp_path):
    d = tmp_path / "cfg" / "up"; d.mkdir(parents=True)
    (d / "model.yaml").write_text(textwrap.dedent("""\
    - UniProt up:P1:
      - a: core:Protein
      - core:sequence:
        - simple_sequence: SimpleSequence
    - SimpleSequence isoforms:P1-1:
      - a: core:Simple_Sequence
      - rdf:value:
        - seq: "MKV"
      - core:mass:
        - seq_mass: 100
    """))
    (d / "prefix.yaml").write_text("core: <http://purl.uniprot.org/core/>\nup: <http://purl.uniprot.org/uniprot/>\n"
                                   "isoforms: <http://purl.uniprot.org/isoforms/>\n"
                                   "rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n")
    (d / "endpoint.yaml").write_text("endpoint:\n  - https://ep/sparql\n")
    return str(d)


def make_knowledge(tmp_path):
    p = tmp_path / "kn.yaml"
    p.write_text(textwrap.dedent("""\
    subjects:
      - {source: up, subject: UniProt, im_class: Protein, status: sure, basis: test}
      - {source: up, subject: SimpleSequence, im_class: Sequence, status: sure, basis: test}
    predicates:
      - {source: up, pred: "-self-", subject: UniProt, im: Protein.primaryAccession, status: sure, basis: test, transform: iri_localname, required: "yes"}
      - {source: up, subject: SimpleSequence, pred: rdf:value, im: Sequence.residues, status: sure, basis: test}
      - {source: up, subject: SimpleSequence, pred: core:mass, im: Protein.molecularWeight, status: sure, basis: test}
      - {source: up, subject: SimpleSequence, pred: core:md5Checksum, im: Sequence.md5checksum, status: sure, basis: test}
      - {source: up, subject: SimpleSequence, pred: core:fragment, im: Protein.isFragment, status: sure, basis: test,
         transform: "replace:single:true,replace:multiple:true,default:false"}
    """))
    return Knowledge(str(p))


ADDITIONS = {"SimpleSequence": [{"core:md5Checksum?": [{"seq_md5": "abc"}]},
                                {"core:fragment?": [{"seq_fragment": "single"}]},
                                {"core:mass": [{"other_mass": 1}]}]}
CONSTRAINTS = {"SimpleSequence": ["?{var} a core:Simple_Sequence .",
                                  'FILTER(STRSTARTS(STR(?{var}), CONCAT(REPLACE(STR(?{root}), "/uniprot/", "/isoforms/"), "-")))']}


def test_model_additions_add_predicates_and_keep_the_upstream_ones(tmp_path):
    cfg = load_config(make_cfg(tmp_path))
    msgs = add_predicates(cfg, dict(ADDITIONS, Nowhere=[{"core:x": [{"x": 1}]}]))
    preds = {p.curie: p for p in cfg.subject("SimpleSequence").predicates}
    assert set(preds) == {"rdf:value", "core:mass", "core:md5Checksum", "core:fragment"}
    assert preds["core:fragment"].cardinality == "?" and preds["core:fragment"].objects[0].name == "seq_fragment"
    assert preds["core:mass"].objects[0].name == "seq_mass"          # the upstream predicate stands
    assert any("Nowhere is not in model.yaml" in m for m in msgs)
    assert any("already has core:mass" in m for m in msgs)


def test_uniprot_canonical_sequence_query(tmp_path):
    """The added predicates get rows like any other, and the node's constraints sit in its own
    OPTIONAL block, naming its variable and the root's, so they narrow which sequence binds and
    never drop the protein."""
    m = make_model(tmp_path)
    r = translate(m, make_cfg(tmp_path), str(tmp_path / "out"), make_knowledge(tmp_path),
                  {"model_additions": ADDITIONS})
    rows = {(x["subject"], x["predicate"]): x for x in r["rows"]}
    assert rows[("SimpleSequence", "rdf:value")]["im_class"] == "Sequence"
    assert rows[("SimpleSequence", "core:md5Checksum")]["im_field"] == "md5checksum"
    assert rows[("SimpleSequence", "core:fragment")]["table"] == "main"
    q, select, _ = QueryBuilder(r["cfg"], r["node_by_key"], node_constraints=CONSTRAINTS).build(
        "main", query_rows(r["rows"], "main", True))
    assert {"seq", "seq_md5", "seq_fragment"} <= set(select)
    block = q[q.index("OPTIONAL {\n"):]
    assert "?UniProt core:sequence ?simple_sequence ." in block
    assert "?simple_sequence a core:Simple_Sequence ." in block
    assert 'FILTER(STRSTARTS(STR(?simple_sequence), CONCAT(REPLACE(STR(?UniProt), "/uniprot/", "/isoforms/"), "-")))' in block
    assert block.index("a core:Simple_Sequence") < block.index("OPTIONAL { ?simple_sequence rdf:value")
    # without constraints the query is as before
    q0, _, _ = QueryBuilder(r["cfg"], r["node_by_key"]).build("main", query_rows(r["rows"], "main", True))
    assert "Simple_Sequence" not in q0 and "FILTER" not in q0


def test_default_transform_fills_only_an_empty_value():
    t = "replace:single:true,replace:multiple:true,default:false"
    assert apply_transform("single", t) == ["true"]
    assert apply_transform("multiple", t) == ["true"]
    assert apply_transform("", t) == ["false"]


def test_sequences_get_their_length_and_proteins_theirs(tmp_path):
    m = make_model(tmp_path)
    st = ItemStore(m)
    md5 = hashlib.md5(b"MKVL").hexdigest()
    s = st.get("Sequence", {"residues": "MKVL", "md5checksum": md5})
    bad = st.get("Sequence", {"residues": "MK", "md5checksum": md5})
    p1 = st.get("Protein", {"primaryAccession": "P1"})
    p2 = st.get("Protein", {"primaryAccession": "A0A1"})                   # same sequence, other entry
    p3 = st.get("Protein", {"primaryAccession": "P3", "length": "9"})      # a stated length stands
    assert st.get("Sequence", {"residues": "MKVL", "md5checksum": md5}) == s   # one item per sequence
    for p in (p1, p2, p3):
        st.link(p, "sequence", s)
    n, notes = st.complete_sequences()
    assert st.items[s].attrs["length"] == "4" and st.items[bad].attrs["length"] == "2"
    assert st.items[p1].attrs["length"] == "4" and st.items[p2].attrs["length"] == "4"
    assert st.items[p3].attrs["length"] == "9"
    assert n == 4
    assert len(notes) == 1 and "is not the md5 of its residues" in notes[0]
    assert "md5checksum" not in st.items[p1].attrs


def test_own_keys_cut_a_class_and_name_a_key_no_file_declares():
    type_lines = ["# humanmine-items_keys.properties", "#", "",
                  "Protein.key_primaryidentifier=primaryIdentifier", "Protein.key_primaryacc=primaryAccession",
                  "Protein.key_md5=md5checksum, organism", "",
                  "# WARNING no key and no identifier attribute for Sequence - its items never merge", "",
                  "Gene.key_primaryidentifier=primaryIdentifier", "Gene.key_symbol_org=symbol, organism", ""]
    out = source_keys(type_lines, {"Protein": ["primaryAccession"], "Sequence": ["md5checksum"]},
                      "humanmine-uniprot", "humanmine-items")
    keys = [ln for ln in out if "=" in ln and not ln.startswith("#")]
    assert "Protein.key_primaryacc=primaryAccession" in keys
    assert not any(k.startswith("Protein.key_md5") or k.startswith("Protein.key_primaryidentifier") for k in keys)
    assert "Sequence.key_md5checksum=md5checksum" in keys
    assert "Gene.key_symbol_org=symbol, organism" in keys                   # other classes untouched
    # a class that keeps a key of its own gets nothing added (ncbigene, hgnc)
    out2 = source_keys(type_lines, {"Gene": ["primaryIdentifier"]}, "humanmine-ncbigene", "humanmine-items")
    assert [ln for ln in out2 if ln.startswith("Gene.")] == ["Gene.key_primaryidentifier=primaryIdentifier"]


def _tsv(tmp_path, raw_header):
    """`rdfc2im tsv --source up` on a raw main.tsv with `raw_header`, for a query selecting ?UniProt ?seq."""
    import contextlib, io
    from rdfc2im import cli
    src = tmp_path / "out" / "up"
    (src / "raw").mkdir(parents=True)
    (tmp_path / "cfg" / "up").mkdir(parents=True)
    (tmp_path / "rdfc2im.yaml").write_text("config_root: cfg\nout: out\nsources: [up]\n")
    (src / "columns.tsv").write_text(
        "table\tposition\tcolumn\tvariable\tim_class\tim_field\ttransform\tfilter\tvalue\tkind\tvia\tstatus\trequired\troot\n"
        "main\t0\tUniProt\tUniProt\tProtein\tprimaryAccession\tiri_localname\t\t\tiri\t\tsure\tyes\tProtein\n"
        "main\t1\tseq\tseq\tSequence\tresidues\t\t\t\tliteral\t\tsure\tno\tProtein\n")
    vals = {"?UniProt": "<http://purl.uniprot.org/uniprot/P1>", "?seq": '"MKV"', "?seq_mass": '"1"'}
    (src / "raw" / "main.tsv").write_text("\t".join(raw_header) + "\n" + "\t".join(vals[h] for h in raw_header) + "\n")
    old = os.getcwd(); os.chdir(tmp_path); err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["tsv", "--source", "up"])
    finally:
        os.chdir(old)
    return rc, err.getvalue()


def test_tsv_stops_on_a_raw_table_fetched_for_another_query(tmp_path):
    """The raw-data cache records scope, taxon and panel, not the query: restored after a mapping
    change (the uniprot group before im-9n4.32 has no ?seq), the new column would load empty.
    `rdfc2im tsv` exits non-zero instead, which stops full-build.sh (set -e)."""
    rc, err = _tsv(tmp_path, ["?UniProt", "?seq_mass"])
    assert rc != 0 and "up/main lacks seq" in err


def test_tsv_passes_a_raw_table_that_has_every_column(tmp_path):
    assert _tsv(tmp_path, ["?UniProt", "?seq"]) == (0, "")


def test_rdf_uniprot_never_merges_a_protein_on_its_sequence():
    """Stock uniprot keys Protein on md5checksum+organism; 20 of the panel's TrEMBL entries have a
    Swiss-Prot entry's sequence (18 Nov 2026), and would merge into it if this source wrote
    Protein.md5checksum or merged Protein on it."""
    src = yaml.safe_load(open(os.path.join(HERE, "rdfc2im", "data", "sources.yaml")))["uniprot"]
    assert src["own_keys"]["Protein"] == ["primaryAccession"]
    assert src["own_keys"]["Sequence"] == ["md5checksum"]
    kn = yaml.safe_load(open(os.path.join(HERE, "rdfc2im", "data", "knowledge.yaml")))
    writes = [e for e in kn["predicates"] if e.get("source") == "uniprot" and e.get("status") != "drop"]
    assert not [e for e in writes if e.get("im") == "Protein.md5checksum"]
    assert [e for e in writes if e.get("im") == "Sequence.residues" and e.get("subject") == "SimpleSequence"]
    assert any("Simple_Sequence" in c for c in src["node_constraints"]["SimpleSequence"])
