"""Data-source status pages [im-9n4.42]: tools/field_counts.py (the streaming counters), tools/source_manifest.py
(the build manifest from caches and logs), tools/source_pages.py (pages, golden; the DataSet link items and
project.xml wiring). All offline, on small fixtures made here."""
import gzip
import io
import json
import os
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import field_counts as fc  # noqa: E402
import source_manifest as sm  # noqa: E402
import source_pages as sp  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "fixtures", "source_pages")


def _w(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.endswith(".gz"):
        with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(text.encode("utf-8"))    # mtime 0: the same bytes (and sha256) on every run
    else:
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(text)
    return path


def _k(res, key):
    return res["keys"].get(key, {"with": 0, "values": 0})


# ---------------------------------------------------------------- counters

GAF = ("!gaf-version: 2.2\n!date-generated: 2026-05-21T08:10\n"
       "UniProtKB\tP1\tA\t\tGO:1\tPMID:1\tIDA\t\tP\t\t\tprotein\ttaxon:9606\t20200101\tUniProt\t\t\n"
       "UniProtKB\tP2\tB\tenables\tGO:2\tPMID:2\tIEA\tX:1\tF\t\t\tprotein\ttaxon:9606\t20200101\tUniProt\tx(y)\t\n"
       "\n")


def test_tab_counts_records_with_a_value_per_column_and_skips_comments(tmp_path):
    res = fc.count_file(_w(str(tmp_path / "a.gaf.gz"), GAF), "tab", comment="!")
    assert res["records"] == 2 and res["complete"]
    assert _k(res, "col:2")["with"] == 2 and _k(res, "col:4")["with"] == 1
    assert _k(res, "col:8")["with"] == 1 and _k(res, "col:16")["with"] == 1 and "col:17" not in res["keys"]


def test_tab_header_by_number_first_and_match(tmp_path):
    p = _w(str(tmp_path / "g.gct"), "#1.2\n2\t3\nName\tDescription\tLiver\nG1\tg\t1\nG2\t\t2\n")
    res = fc.count_file(p, "tab", comment=None, skip_lines=2, header_line=3)
    assert res["records"] == 2 and res["names"]["col:3"] == "Liver" and _k(res, "col:2")["with"] == 1
    p = _w(str(tmp_path / "h.tsv"), "Gene\tLevel\nE1\tHigh\nE2\t\n")
    res = fc.count_file(p, "tab", header_line="first")
    assert res["records"] == 2 and res["names"] == {"col:1": "Gene", "col:2": "Level"}
    # phenotype.hpoa: '#' lines, then a header upstream; the filtered copy has no header at all
    up = _w(str(tmp_path / "up.hpoa"), "#version: 1\ndatabase_id\tname\nOMIM:1\tx\nORPHA:2\ty\n")
    cut = _w(str(tmp_path / "cut.hpoa"), "#version: 1\nOMIM:1\tx\n")
    a = fc.count_file(up, "tab", comment="#", header_line="match:database_id")
    b = fc.count_file(cut, "tab", comment="#", header_line="match:database_id")
    assert (a["records"], b["records"]) == (2, 1) and a["names"]["col:1"] == "database_id"


def test_gff3_columns_types_attributes_and_dbxref_prefixes(tmp_path):
    gff = ("##gff-version 3\n##sequence-region NC_1 1 100\n"
           "NC_1\tRefSeq\tgene\t1\t50\t.\t+\t.\tID=gene-A;Dbxref=GeneID:1,HGNC:HGNC:5;Name=A;gene_biotype=protein_coding\n"
           "NC_1\tRefSeq\tmRNA\t1\t50\t.\t+\t.\tID=rna-A;Parent=gene-A;Dbxref=GeneID:1,Genbank:NM_1,GeneID:9\n"
           "##FASTA\n>x\nACGT\n")
    res = fc.count_file(_w(str(tmp_path / "a.gff"), gff), "gff3")
    assert res["records"] == 2
    assert _k(res, "col:6") == {"with": 0, "values": 0} and _k(res, "col:3=gene")["with"] == 1
    assert _k(res, "attr:Parent")["with"] == 1 and _k(res, "attr:Dbxref")["with"] == 2
    assert _k(res, "attr:Dbxref:GeneID") == {"with": 2, "values": 3} and _k(res, "attr:Dbxref:HGNC")["with"] == 1


XML = ('<?xml version="1.0"?><uniprot xmlns="https://uniprot.org/uniprot">'
       '<entry dataset="Swiss-Prot"><accession>P1</accession><accession>P1b</accession><gene><name type="primary">A</name></gene></entry>'
       '<entry dataset="Swiss-Prot"><accession>P2</accession><feature type="chain"/></entry>'
       '<copyright>c</copyright></uniprot>')


def test_xml_paths_records_and_values_namespace_stripped(tmp_path):
    res = fc.count_file(_w(str(tmp_path / "u.xml.gz"), XML), "xml", record_key="uniprot/entry")
    assert res["records"] == 2
    assert _k(res, "uniprot/entry/accession") == {"with": 2, "values": 3}
    assert _k(res, "uniprot/entry/@dataset")["with"] == 2 and _k(res, "uniprot/entry/gene/name/@type")["with"] == 1
    assert _k(res, "uniprot/copyright") == {"with": 0, "values": 1}


def test_xml_needs_a_record_key_and_a_stopped_count_says_so(tmp_path):
    p = _w(str(tmp_path / "u.xml"), XML)
    try:
        fc.count_file(p, "xml")
        raise AssertionError("no record key accepted")
    except fc.CountError:
        pass
    res = fc.count_file(p, "xml", record_key="uniprot/entry", max_seconds=1e-9)
    assert res["complete"] is False and res["bytes_read"] > 0


def test_obo_tags_per_stanza_and_fasta_headers(tmp_path):
    obo = ("format-version: 1.2\ndata-version: x\n\n[Term]\nid: MI:1\nname: a\nis_a: MI:0\nis_a: MI:2\n\n"
           "[Term]\nid: MI:2\nname: b\n\n[Typedef]\nid: part_of\n")
    res = fc.count_file(_w(str(tmp_path / "m.obo"), obo), "obo")
    assert res["records"] == 2 and _k(res, "Term/is_a") == {"with": 1, "values": 2}
    assert _k(res, "header/format-version")["with"] == 1 and _k(res, "Typedef")["values"] == 1
    fa = (">sp|P1-2|X_HUMAN Isoform 2 of Thing OS=Homo sapiens OX=9606 GN=ABC\nMKV\n"
          ">sp|P2-2|Y_HUMAN Isoform 2 of Other OS=Homo sapiens OX=9606\n\n")
    res = fc.count_file(_w(str(tmp_path / "v.fasta.gz"), fa), "fasta")
    assert res["records"] == 2 and _k(res, "header:GN")["with"] == 1 and _k(res, "sequence")["with"] == 1
    assert fc.fasta_header_fields("sp|P1-2|X_HUMAN Isoform 2 of Thing OS=Homo sapiens OX=9606")["header:description"] \
        == "Isoform 2 of Thing"


def test_archives_and_directories_are_read_member_by_member(tmp_path):
    zp = str(tmp_path / "a.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("d/one.tsv", "a\tb\n")
        z.writestr("d/two.tsv", "c\t\n")
        z.writestr("readme.txt", "x\n")
    res = fc.count_file(zp, "tab", member="*.tsv")
    assert res["records"] == 2 and res["inputs"] == ["d/one.tsv", "d/two.tsv"]
    tp = str(tmp_path / "a.tar.gz")
    with tarfile.open(tp, "w:gz") as tf:
        data = b"x\ty\nz\tw\n"
        ti = tarfile.TarInfo("Orth/Orth")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    assert fc.count_file(tp, "tab", unpack="tar.gz", member="Orth")["records"] == 2
    d = tmp_path / "dir"
    _w(str(d / "b.xml"), XML)
    _w(str(d / "a.xml"), XML)
    res = fc.count_file(str(d), "xml", member="*.xml", record_key="uniprot/entry")
    assert res["records"] == 4 and res["inputs"] == ["a.xml", "b.xml"]


def test_counts_are_cached_under_the_sha256(tmp_path):
    p = _w(str(tmp_path / "a.tsv"), "a\tb\n")
    cache = str(tmp_path / "cache")
    spec = fc.spec_of("tab")
    first = fc.count_cached(p, spec, cache)
    second = fc.count_cached(p, spec, cache)
    assert first["cached"] is False and second["cached"] is True and first["records"] == second["records"] == 1
    assert first["sha256"] == fc.sha256_file(p) == fc.sha256_file(p, cache)
    _w(p, "a\tb\nc\td\n")
    assert fc.count_cached(p, spec, cache)["records"] == 2


# ---------------------------------------------------------------- manifest pieces

def test_filter_rule_in_one_sentence():
    r = sm.filter_rule({"format": "gaf", "ids": "uniprot"}, {"uniprot": 1547})
    assert r.startswith("rows whose column 2 is one of the 1,547 UniProt accessions") and r.endswith(".")
    r = sm.filter_rule({"format": "tab", "ids": "ensembl", "column": "1", "keep_header": 3}, {"ensembl": 115})
    assert "column 1 holds one of the 115 Ensembl gene ids" in r and "first 3 lines (header) kept" in r
    assert sm.filter_rule("none", {}).startswith("none")


def test_release_from_header_member_name_and_url(tmp_path):
    p = _w(str(tmp_path / "a.gaf"), GAF)
    assert sm.release_of({"from": "line", "pattern": r"^!date-generated: (\S+)", "label": "generated"},
                         p, None, None, None, None) == "generated 2026-05-21T08:10"
    assert sm.release_of([{"from": "member_name", "pattern": r"-(\d+\.\d+\.\d+)\.psi25"}], p, None, None, None,
                         ["BIOGRID-ORGANISM-Homo_sapiens-5.0.263.psi25.xml"]) == "5.0.263"
    assert sm.release_of({"from": "url", "pattern": r"_(v\d+)_"}, p, None, None, "https://x/GTEx_v8_x.gct.gz", None) == "v8"
    assert sm.release_of(None, p, None, None, None, None) is None


def test_filter_logs_pair_each_command_with_its_json_line(tmp_path):
    _w(str(tmp_path / "build-ut-subset_stock_data.log"),
       "12:00 [subset_stock_data] + python3 tools/subset_raw.py filter --format gaf --in /r/x.gaf.gz "
       "--out /s/subset/go-annotation/gaf/gene_association.goa_human --ids /i/uniprot.txt\n"
       '{"format": "gaf", "records_in": 10, "records_out": 2, "ids_given": 3, "ids_matched": 1}\n')
    got = sm.filter_logs(str(tmp_path))
    assert got["/s/subset/go-annotation/gaf/gene_association.goa_human"]["records_out"] == 2


def test_rdf_table_counts_and_items_per_class(tmp_path):
    t = _w(str(tmp_path / "main.tsv"), '?id\t?label\n"A"\t"a"\n"A"\t\n"B"\t"b"\n')
    got = sm.table_column_counts(t)
    assert got["_rows"] == 3 and got["label"] == {"with": 2, "ids": 2} and got["id"] == {"with": 3, "ids": 2}
    i = _w(str(tmp_path / "x.xml"), '<items>\n  <item id="0_1" class="Gene" implements="">\n'
           '  <item id="0_2" class="Gene" implements="">\n  <item id="0_3" class="DataSet" implements="">\n</items>\n')
    assert sm.items_per_class(i) == {"DataSet": 1, "Gene": 2}


def test_leaf_total_counts_each_object_once():
    model = {"classes": {"BioEntity": {"count": 5}, "Gene": {"count": 3, "extends": ["BioEntity"]},
                         "Protein": {"count": 2, "extends": ["BioEntity"]}, "DataSet": {"count": 4}}}
    assert sm.leaf_total(model) == 9


# ---------------------------------------------------------------- a whole stock source, end to end

TOY_TABLE = """sources:
  toy:
    type: toy
    jar: intermine
    licence: CC-BY-4.0
    licence_status: verified
    licence_url: https://example.org/toy/licence
    licence_checked: "2026-11-18"
    licence_quote: "The Toy data are licensed under CC BY 4.0."
    licence_conditions:
      - "Cite Toy DB (2026)."
      - "Say if the rows were cut."
    redistributable: true
    redistributable_reason: "CC BY 4.0 allows redistribution of changed copies."
    data_dir: toy/current
    files:
      - id: rows
        url: https://example.org/toy.tsv.gz
        verified: true
        size: 10
        last_modified: "2026-01-02"
        stage_as: toy.tsv
        filter: {format: tab, ids: entrez, column: "1", keep_header: true}
"""

TOY_MAPPING = """source: toy
home: https://example.org/
loader:
  repository: intermine
  path: bio/sources/toy
  classes: [org.intermine.bio.dataconversion.ToyConverter]
  commit: abc1234
basis: read from code at intermine abc1234 (ToyConverter.java)
data_source: Toy DB
data_sets: [Toy data set]
writes: [Gene]
files:
  - id: rows
    format: tab
    header_line: first
    record: one row (one gene)
    release: [{from: line, pattern: "^#release: (.*)$", label: release}]
    unlisted: not loaded
    unlisted_reason: ToyConverter reads only the columns listed
    fields:
      - key: "col:1"
        name: gene_id
        description: NCBI gene id
        maps_to: [Gene.primaryIdentifier]
        status: loaded
        code: ToyConverter.java:10
      - key: "col:2"
        name: symbol
        description: gene symbol
        maps_to: []
        status: not loaded
        reason: superseded by ncbigene
"""

TOY_RAW = "#release: 7 (Jan 2026)\ngene_id\tsymbol\tnote\n1\tA\tx\n2\tB\t\n3\t\t\n"
TOY_CUT = "gene_id\tsymbol\tnote\n1\tA\tx\n"


def _toy_tree(tmp_path):
    stock = tmp_path / "stock"
    _w(str(stock / "cache" / "stock-raw-toy" / "data" / "toy.tsv.gz"), TOY_RAW)
    _w(str(stock / "cache" / "stock-raw-toy" / "META.json"), json.dumps(
        {"bytes": 10, "files": 1, "saved_at": "2026-11-18T03:00:00Z",
         "meta": {"last_modified.rows": "2026-01-02T10:00:00Z", "url.rows": "https://example.org/toy.tsv.gz"}}))
    _w(str(stock / "cache" / "stock-raw-toy" / "MD5SUMS"), "0123  data/toy.tsv.gz\n")
    _w(str(stock / "filtered" / "stock-toy" / "data" / "rows" / "toy.tsv"), TOY_CUT)
    _w(str(stock / "filtered" / "stock-toy" / "META.json"), json.dumps(
        {"saved_at": "2026-11-18T03:05:00Z", "meta": {"genes_md5": "g"}}))
    _w(str(stock / "idsets" / "idsets.json"), json.dumps({"counts": {"entrez": 2}, "genes_md5": "g"}))
    _w(str(tmp_path / "table.yaml"), TOY_TABLE)
    _w(str(tmp_path / "mappings" / "toy.yaml"), TOY_MAPPING)
    return stock


def _toy_manifest(tmp_path):
    stock = _toy_tree(tmp_path)
    out = str(tmp_path / "manifest.json")
    rc = sm.main(["--out", out, "--stock-sources", "toy", "--stock-dir", str(stock),
                  "--filtered-cache", str(stock / "filtered"), "--stock-table", str(tmp_path / "table.yaml"),
                  "--mappings", str(tmp_path / "mappings"), "--count-cache", str(tmp_path / "cc"),
                  "--build-name", "toy build", "--rdfc2im-commit", "0123456789abcdef",
                  "--out-root", str(tmp_path / "out"), "--cache-dir", str(tmp_path / "rdfcache")])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        man = json.load(fh)
    # what varies with the machine: absolute paths, timings, the mapping commit of this checkout
    man["gaps"] = {"stock:toy": [{"text": "A toy gap.", "from": "BUILD.md"}]}
    return man


def test_manifest_of_a_stock_source_from_its_caches(tmp_path):
    man = _toy_manifest(tmp_path)
    (src,) = man["sources"]
    (f,) = src["files"]
    assert src["id"] == "stock:toy" and src["licence"] == "CC-BY-4.0"
    assert src["licence_info"]["status"] == "verified" and src["licence_info"]["conditions"][0] == "Cite Toy DB (2026)."
    assert f["fetched_at"] == "2026-11-18T03:00:00Z" and f["last_modified"] == "2026-01-02T10:00:00Z"
    assert f["release"] == "release 7 (Jan 2026)" and len(f["sha256"]) == 64
    assert (f["records_raw"], f["records_kept"]) == (3, 1)
    assert f["counts_raw"]["keys"]["col:2"]["with"] == 2 and f["counts_input"]["keys"]["col:3"]["with"] == 1
    assert "column 1 holds one of the 2 NCBI Gene (Entrez) ids" in f["filter_rule"]


def _golden(tmp_path):
    man = _toy_manifest(tmp_path)
    for s in man["sources"]:
        for f in s["files"]:
            for k in ("raw_path", "input_path"):
                f[k] = "<path>"
            for c in ("counts_raw", "counts_input"):
                if f.get(c):
                    f[c]["seconds"] = f[c]["peak_rss_mb"] = 0
    man["build"]["finished_at"] = "2026-11-18T10:24:00Z"
    return man


def test_the_stock_page_matches_the_golden_page(tmp_path):
    man = _golden(tmp_path)
    out = tmp_path / "pages"
    sp.write_pages(man, str(out), str(tmp_path / "mappings"))
    for name in ("stock-toy.md", "README.md"):
        got = (out / name).read_text(encoding="utf-8")
        want_path = os.path.join(GOLDEN, name)
        if os.environ.get("RDFC2IM_UPDATE_GOLDEN") == "1":
            _w(want_path, got)
        with open(want_path, encoding="utf-8") as fh:
            assert got == fh.read(), name


def test_pages_are_byte_identical_when_made_again(tmp_path):
    man = _golden(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    sp.write_pages(man, str(a), str(tmp_path / "mappings"))
    sp.write_pages(json.loads(json.dumps(man)), str(b), str(tmp_path / "mappings"))
    for n in sorted(os.listdir(a)):
        assert (a / n).read_bytes() == (b / n).read_bytes(), n


def test_unlisted_xml_keys_show_only_the_top_of_an_unread_subtree():
    mf = {"format": "xml", "unlisted": "not loaded", "unlisted_reason": "not read",
          "fields": [{"key": "u/e/acc", "status": "loaded", "maps_to": ["Protein.primaryAccession"]},
                     {"key": "u/e/skip", "status": "not loaded"}]}
    counts = {"keys": {k: {"with": 1, "values": 1} for k in
                       ("u/e/acc", "u/e/skip", "u/e/skip/x", "u/e/other", "u/e/other/y", "u/e/other/@z")}}
    keys = [r["key"] for r in sp.stock_rows(mf, counts, None)]
    assert keys == ["u/e/acc", "u/e/skip", "u/e/other"]


def test_rdf_rows_use_the_extract_counts_and_the_sssom_status():
    src = {"tables": {"main": {"columns": {"label": {"with": 5, "ids": 4}, "_rows": 5}}},
           "mapping_rows": [
               {"ext_predicate": "rdfs:label", "subject_label": "label", "ext_table": "main", "ext_status": "sure",
                "object_label": "GOTerm.name"},
               {"ext_predicate": "oboinowl:inSubset", "subject_label": "subset", "ext_table": "main_subset",
                "ext_status": "todo"},
               {"ext_predicate": "-const-", "subject_label": "c", "ext_table": "*", "ext_status": "sure"}]}
    rows = sp.rdf_rows(src)
    assert [(r["pred"], r["loaded"], r["n"]) for r in rows] == [("rdfs:label", True, "5 (4 subjects)"),
                                                               ("oboinowl:inSubset", False, "not fetched")]
    assert rows[1]["why"] == "not yet done"


def test_licence_rows_of_a_stock_page_an_rdf_page_and_an_old_manifest():
    info = {"name": "CC-BY-4.0", "status": "partial", "url": "https://example.org/l", "checked": "2026-11-18",
            "quote": "Free | with credit.", "conditions": ["Credit X.", "No logos."], "redistributable": True,
            "reason": "allowed", "rdfportal": "CC BY 4.0", "rdfportal_url": "https://rdfportal.org/dataset/x/",
            "rdfportal_note": "Same as upstream."}
    rows = sp.licence_rows(info, "CC BY 4.0 (old)", True)
    assert rows[0] == "| Licence | CC-BY-4.0 |"
    assert any("partly verified" in r for r in rows) and "| Licence stated at | <https://example.org/l> |" in rows
    assert "| Licence read on | 2026-11-18 (UTC) |" in rows
    assert '| Licence wording | "Free \\| with credit." |' in rows
    assert "| Conditions | - Credit X. <br> - No logos. |" in rows
    assert rows[-1] == "| Redistributable | yes: allowed |"
    rdf = sp.licence_rows(info, None, None, rdf=True)
    assert rdf[0] == "| Licence (upstream) | CC-BY-4.0 |"
    assert any(r.startswith("| Licence (RDF Portal) | CC BY 4.0 (on <https://rdfportal.org/dataset/x/>). Same as upstream.") for r in rdf)
    # a manifest made before the structured keys: the old rows, and the old RDF wording
    assert sp.licence_rows(None, "CC0 (old)", False) == ["| Licence | CC0 (old) |", "| Redistributable | no |"]
    assert sp.licence_rows(None, None, None, rdf=True)[0].startswith("| Licence (upstream) | not recorded")
    assert sp.licence_cell({"licence_info": info, "licence": "x"}) == "CC-BY-4.0 [partial]"
    assert sp.licence_cell({"licence": "MIT"}) == "MIT"


def test_rdf_page_shows_the_licence_and_what_rdf_portal_states():
    man = {"build": {"name": "b", "rdfc2im_commit": "0123456789abcdef", "finished_at": "2026-11-18T10:00:00Z"}, "sources": []}
    src = {"id": "rdf:toy", "kind": "rdf", "name": "toy", "data_source": {"name": "Toy", "url": "https://example.org"},
           "data_set": "Toy (RDF Portal)", "tables": {}, "mapping_rows": [], "columns": [], "cache_group": {},
           "licence": "CC0-1.0", "licence_info": {"name": "CC0-1.0", "status": "verified", "url": "https://example.org/l",
                                                   "checked": "2026-11-18", "quote": "CC0.", "conditions": [],
                                                   "redistributable": True, "reason": "no conditions",
                                                   "rdfportal": "CC0", "rdfportal_url": "https://rdfportal.org/dataset/toy/"}}
    page = sp.rdf_page(src, man)
    assert "| Licence (upstream) | CC0-1.0 |" in page and "not recorded in rdfc2im" not in page
    assert "| Licence (RDF Portal) | CC0 (on <https://rdfportal.org/dataset/toy/>) |" in page
    assert "| Redistributable | yes: no conditions |" in page


# ---------------------------------------------------------------- DataSet links

def test_data_set_links_items_and_project_wiring(tmp_path):
    pages = {"Toy data set": ["stock-toy.md"], "Reactome pathways data set": ["rdf-reactome.md", "stock-reactome.md"]}
    xml = sp.data_set_links_xml(pages, "https://github.com/o/r/blob/b/docs/data-sources")
    assert xml.count('class="DataSet"') == 2
    assert 'value="https://github.com/o/r/blob/b/docs/data-sources/rdf-reactome.md"' in xml
    assert "(rdf-reactome, stock-reactome)" in xml
    proj = _w(str(tmp_path / "project.xml"), '<project type="bio">\n  <sources>\n'
              '    <source name="humanmine-go" type="humanmine-items" version="4.3.0">\n'
              '      <property name="src.data.file" location="/d/go.xml"/>\n    </source>\n  </sources>\n</project>\n')
    pri = _w(str(tmp_path / "p.properties"), "DataSource.url = humanmine-static, *\nDataSet.url = x, *\n")
    for _ in range(2):    # idempotent
        sp.add_links_source(proj, pri, "/d/links.xml")
    text = open(proj, encoding="utf-8").read()
    assert text.count('<source name="data-set-links" type="humanmine-items" version="4.3.0">') == 1
    assert text.index("data-set-links") > text.index("humanmine-go") and text.rstrip().endswith("</project>")
    ptext = open(pri, encoding="utf-8").read()
    assert "DataSet.url = data-set-links, *" in ptext and "DataSet.url = x, *" not in ptext
    assert ptext.count("DataSet.description = data-set-links, *") == 1 and "DataSource.url = humanmine-static" in ptext


def test_data_set_pages_from_the_mapping_files_and_sources_yaml():
    pages = sp.data_set_pages(["go-annotation"], ["go", "reactome"])
    assert pages["GO (RDF Portal)"] == ["rdf-go.md"]
    assert pages["Reactome pathways data set"] == ["rdf-reactome.md", "stock-reactome.md"]
    assert pages["GO Annotation data set"] == ["stock-go-annotation.md"]


def test_every_mapping_file_is_well_formed():
    import yaml
    for n in sorted(os.listdir(sp.MAPPINGS_DIR)):
        with open(os.path.join(sp.MAPPINGS_DIR, n), encoding="utf-8") as fh:
            mp = yaml.safe_load(fh)
        assert mp["source"] == n[:-5], n
        # data_sets may be empty: humanmine-static and update-data-sources write no DataSet of their own [im-9n4.27]
        assert isinstance(mp.get("data_sets"), list) and mp.get("loader", {}).get("commit"), n
        if not mp["data_sets"]:
            assert n in ("humanmine-static.yaml", "update-data-sources.yaml"), n
        for f in mp["files"]:
            assert f["format"] in fc.FORMATS, (n, f["id"])
            if f["format"] == "xml":
                assert f.get("record_key"), (n, f["id"])
            keys = [x["key"] for x in f.get("fields") or []]
            assert len(keys) == len(set(keys)), (n, f["id"], "duplicate keys")
            for x in f.get("fields") or []:
                assert x.get("status") in ("loaded", "not loaded", "unknown"), (n, x["key"])
                for m in x.get("maps_to") or []:
                    assert "." in m and " " not in m, (n, x["key"], m)
