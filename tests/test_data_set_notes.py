"""im-9n4.59: a note with the data set, where users read the data-source listing.

Gos, 20 Nov 2026: the data-source listing should say that Ensembl genes are loaded only where an NCBI
gene corresponds ("maybe a new column Notes").  Without a model change: a per-source `data_set_note`
(sources.yaml for the RDF sources, the stock mapping files for the stock ones), with numbers the build
fills in (`data_set_note_counts`, from the source's cross-reference join report), plus the gene-panel
cut the build applies; written by data-set-links into DataSet.description after the status-page
sentence, and shown as a Notes row on the source's status page.  All offline."""
import os
import re
import sys
import xml.etree.ElementTree as ET

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)

import source_pages as sp  # noqa: E402
from rdfc2im import data_set_notes as dsn  # noqa: E402
from rdfc2im import stock  # noqa: E402

from test_data_set_versions import _group, _w  # noqa: E402

NOTE = "Toy genes are loaded only where a cross-reference names an NCBI gene."
COUNTS = "{not_joined:,} of {total:,} Toy genes in this build's scope were not loaded for that reason."
REPORT = ("ensembl_id\tsymbol\tstatus\tentrez\tvia\treason\tdisagree\n"
          "E1\tA\tjoined\t1\thgnc\t\t\nE2\tB\tunmatched\t\t\tno cross-reference to an NCBI gene\t\n"
          "E3\tC\tambiguous\t2,3\tensembl\t\t\nE4\tD\tjoined\t4\tncbigene\t\t\n")
STATUS = ("Status page of this data set's source (rdf-toyrdf): the file, release and fetch date this build loaded, "
          "and which fields of the source are loaded and which are not.")

SOURCES_YAML = f"""toyrdf:
  data_source_name: Toy
  data_set_title: Toy (RDF Portal)
  data_set_note: "{NOTE}"
  data_set_note_counts: "{COUNTS}"
  gene_scope_field: secondaryIdentifier
plainrdf:
  data_source_name: Plain
  data_set_title: Plain (RDF Portal)
"""

TABLE = """sources:
  cutsrc:
    type: cutsrc
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: cutsrc
    files:
      - {id: rows, url: "https://example.org/c.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: c.tsv,
         filter: {format: tab, ids: uniprot, column: "1"}}
  partners:
    type: partners
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: partners
    files:
      - {id: rows, url: "https://example.org/p.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: p.tsv,
         filter: {format: tab, ids: mgi, column: "1"}}
  whole:
    type: whole
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: whole
    files:
      - {id: rows, url: "https://example.org/w.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: w.tsv, filter: none}
"""


def _tree(tmp_path, rdf_scope="panel", report=True):
    rdf = str(tmp_path / "rdfcache")
    _group(rdf, "toyrdf", "2026-11-20T07:00:00Z", {"scope": rdf_scope}, {"main.tsv": "?id\n"})
    _group(rdf, "plainrdf", "2026-11-20T07:00:00Z", {"scope": "full"}, {"main.tsv": "?id\n"})
    out_root = str(tmp_path / "out")
    if report:
        _w(os.path.join(out_root, "toyrdf", "items", "toyrdf_xref_join.tsv"), REPORT)
    mdir = str(tmp_path / "mappings")
    for n, extra in (("cutsrc", {}), ("partners", {}), ("whole", {"data_set_note": "Whole note."})):
        doc = dict({"source": n, "data_source": n.title(), "data_sets": [f"{n} data set"], "files": [{"id": "rows"}],
                    "loader": {"repository": "intermine", "path": n, "commit": "abc"}}, **extra)
        _w(os.path.join(mdir, n + ".yaml"), yaml.safe_dump(doc, sort_keys=False))
    return dict(mappings_dir=mdir, sources_yaml=_w(str(tmp_path / "sources.yaml"), SOURCES_YAML),
                table=stock.load_table(_w(str(tmp_path / "table.yaml"), TABLE)), cache_dir=rdf, out_root=out_root)


def _notes(tmp_path, panel_genes=114, stock_names=("cutsrc", "partners", "whole"), rdf_names=("toyrdf", "plainrdf"), **kw):
    return sp.data_set_notes(list(stock_names), list(rdf_names), panel_genes=panel_genes, **_tree(tmp_path, **kw))


# ---------------------------------------------------------------- the facts

def test_the_counts_come_from_the_join_report(tmp_path):
    p = _w(str(tmp_path / "r.tsv"), REPORT + "E5\tE\tkept\tE5\t\t\t\n")
    assert dsn.xref_join_counts(p) == {"total": 5, "not_joined": 2}, "kept genes are loaded: not counted"
    assert dsn.xref_join_counts(str(tmp_path / "missing.tsv")) is None


def test_the_note_then_its_numbers_from_the_build(tmp_path):
    rec = {"data_set_note": NOTE, "data_set_note_counts": COUNTS}
    got = dsn.rdf_notes("toyrdf", rec, out_root=str(tmp_path / "none"))
    assert got == [NOTE], "no report: the numbers are left out, never guessed"
    _w(str(tmp_path / "out" / "toyrdf" / "items" / "toyrdf_xref_join.tsv"), REPORT)
    got = dsn.rdf_notes("toyrdf", rec, out_root=str(tmp_path / "out"))
    assert got == [NOTE, "2 of 4 Toy genes in this build's scope were not loaded for that reason."]
    assert dsn.rdf_notes("plain", {}, out_root=str(tmp_path / "out")) == []


def test_the_panel_cut_is_said_where_the_build_applied_it(tmp_path):
    n = _notes(tmp_path)
    assert n["Toy (RDF Portal)"][-1] == "This build loads this data set only for the 114 genes of its gene panel."
    assert "Plain (RDF Portal)" not in n, "a whole (scope full) extract has nothing to say"
    assert n["cutsrc data set"] == ["This build loads only the records of this data set that involve one of the 114 "
                                    "genes of its gene panel or their proteins; the rest of the file is cut before loading."]
    assert n["partners data set"] == ["This build loads only the records of the genes that share a PANTHER orthology "
                                      "row with one of the 114 genes of its gene panel."]
    assert n["whole data set"] == ["Whole note."], "a file used whole: only its own note"


def test_a_data_set_no_file_of_the_build_feeds_gets_no_panel_note(tmp_path):
    """gtex's eQTL data set: `data_set_files` names no file of this build, so nothing was cut for it."""
    t = _tree(tmp_path)
    p = os.path.join(t["mappings_dir"], "cutsrc.yaml")
    mp = yaml.safe_load(open(p, encoding="utf-8"))
    mp["data_sets"] = ["cutsrc data set", "cutsrc empty"]
    mp["data_set_files"] = {"cutsrc empty": []}
    _w(p, yaml.safe_dump(mp))
    n = sp.data_set_notes(["cutsrc"], [], panel_genes=114, **t)
    assert "cutsrc empty" not in n and "one of the 114 genes" in n["cutsrc data set"][0]


def test_no_panel_no_panel_note(tmp_path):
    n = _notes(tmp_path, panel_genes=None)
    assert n["Toy (RDF Portal)"] == [NOTE, "2 of 4 Toy genes in this build's scope were not loaded for that reason."]
    assert "cutsrc data set" not in n and n["whole data set"] == ["Whole note."]
    n = _notes(tmp_path / "full", rdf_scope="full")
    assert not any("gene panel" in s for s in n["Toy (RDF Portal)"])


def test_the_notes_are_deterministic(tmp_path):
    a = _notes(tmp_path / "a")
    b = _notes(tmp_path / "b", stock_names=("whole", "partners", "cutsrc"), rdf_names=("plainrdf", "toyrdf"))
    assert a == b and list(a) == sorted(a)


# ---------------------------------------------------------------- DataSet.description

def _desc(xml):
    return {a["name"]: a.get("description") for it in ET.fromstring(xml) if it.get("class") == "DataSet"
            for a in [{x.get("name"): x.get("value") for x in it.findall("attribute")}]}


def test_the_description_is_the_status_sentence_then_the_note(tmp_path):
    t = _tree(tmp_path)
    pages = sp.data_set_pages(["whole"], ["toyrdf", "plainrdf"], t["mappings_dir"], t["sources_yaml"])
    notes = sp.data_set_notes(["whole"], ["toyrdf", "plainrdf"], panel_genes=None, **t)
    d = _desc(sp.data_set_links_xml(pages, "https://example.org/pages", notes=notes))
    assert d["Toy (RDF Portal)"] == STATUS + " " + NOTE + " 2 of 4 Toy genes in this build's scope were not loaded for that reason."
    assert d["Plain (RDF Portal)"] == STATUS.replace("rdf-toyrdf", "rdf-plainrdf"), "no note: as before"
    d = _desc(sp.data_set_links_xml(pages, None, notes=notes))
    assert d["Toy (RDF Portal)"].startswith(NOTE), "without the pages the note alone"
    assert "Plain (RDF Portal)" not in d
    assert sp.data_set_links_xml(pages, "https://example.org/pages") == \
        sp.data_set_links_xml(pages, "https://example.org/pages", notes={}), "no notes: byte for byte as before"


def test_the_cli_fills_the_note_from_the_out_tree_and_the_panel(tmp_path):
    t = _tree(tmp_path)
    genes = _w(str(tmp_path / "panel.txt"), "# a panel\nA B\nC\n")
    out = str(tmp_path / "links.xml")
    rc = sp.main(["data-set-links", "--out", out, "--sources", "toyrdf", "--stock-sources", "cutsrc",
                  "--cache-dir", t["cache_dir"], "--stock-dir", str(tmp_path / "stock"), "--stock-table", str(tmp_path / "table.yaml"),
                  "--mappings", t["mappings_dir"], "--sources-yaml", t["sources_yaml"], "--out-root", t["out_root"],
                  "--genes", genes])
    assert rc == 0
    d = _desc(open(out, encoding="utf-8").read())
    assert d["Toy (RDF Portal)"].endswith("only for the 3 genes of its gene panel.")
    assert "2 of 4 Toy genes" in d["Toy (RDF Portal)"]
    assert "one of the 3 genes" in d["cutsrc data set"]


# ---------------------------------------------------------------- the real configuration

def test_ensembl_says_it_loads_only_genes_with_an_ncbi_counterpart_numbers_from_the_build():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml"), encoding="utf-8"))
    e = cfg["ensembl"]
    assert "HGNC, NCBI or Ensembl" in e["data_set_note"] and "NCBI gene" in e["data_set_note"]
    assert "{not_joined" in e["data_set_note_counts"] and "{total" in e["data_set_note_counts"]
    for n, rec in cfg.items():
        for k in ("data_set_note", "data_set_note_counts"):
            assert not re.search(r"\d", re.sub(r"\{[^}]*\}", "", rec.get(k) or "")), \
                f"{n}.{k}: numbers come from the build, not the file"


def test_every_note_formats_with_the_join_counts():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "rdfc2im", "data", "sources.yaml"), encoding="utf-8"))
    for n, rec in cfg.items():
        if rec.get("data_set_note_counts"):
            assert rec.get("xref_join"), f"{n}: counts come from the cross-reference join report"
            rec["data_set_note_counts"].format(not_joined=1, total=2)


# ---------------------------------------------------------------- the status page

def test_the_status_page_shows_the_notes_row(tmp_path):
    man = {"build": {"name": "t", "panel_genes": 114}, "sources": []}
    src = {"id": "rdf:toyrdf", "kind": "rdf", "name": "toyrdf", "data_set": "Toy (RDF Portal)", "citation": {},
           "notes": [NOTE, "2 of 4 Toy genes in this build's scope were not loaded for that reason."]}
    page = sp.rdf_page(src, man)
    assert f"| Notes | {NOTE} 2 of 4 Toy genes in this build's scope were not loaded for that reason. |" in page
    assert "| Notes |" not in sp.rdf_page(dict(src, notes=[]), man)
    stock_src = {"id": "stock:whole", "kind": "stock", "name": "whole", "type": "whole", "files": [], "mapping": {}, "notes": ["Whole note."]}
    assert "| Notes | Whole note. |" in sp.stock_page(stock_src, man)


def test_the_manifest_carries_the_notes_the_items_carry(tmp_path):
    import argparse
    import source_manifest as sm
    t = _tree(tmp_path)
    args = argparse.Namespace(out_root=t["out_root"], cache_dir=t["cache_dir"], count_cache=None, endpoint_counts=[],
                              panel_genes=114)
    cfg = yaml.safe_load(open(t["sources_yaml"], encoding="utf-8"))
    ent = sm.rdf_entry("toyrdf", args, cfg["toyrdf"], None, None)
    assert ent["notes"] == _notes(tmp_path / "again")["Toy (RDF Portal)"]


def test_two_panel_cuts_of_one_data_set_make_one_sentence():
    """InterPro data set: protein2ipr's rows cut to the panel proteins and interpro's entries cut to the
    ones those rows name; one sentence, not two."""
    gene = dsn.STOCK_PANEL_CUTS["uniprot"].format(n=114)
    ipr = dsn.STOCK_PANEL_CUTS["ipr"].format(n=114)
    got = dsn.merge_panel_cuts([ipr, gene], 114)
    assert got == [dsn.IPR_AND_MATCHES_CUT.format(n=114)]
    assert dsn.merge_panel_cuts([gene, "Other."], 114) == [gene, "Other."]
