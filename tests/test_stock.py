"""rdfc2im/stock.py and its table, rdfc2im/data/stock_sources.yaml (full-build.sh --stock-sources).

The table is checked against HumanMine's own project.xml (in/humanmine_project.xml, a tracked
input): every entry names a real HumanMine source, of the same type, with the version attribute its
jar origin needs, at HumanMine's own data path. The rest runs on small fixtures.
"""
import copy
import os

import yaml
from lxml import etree

from rdfc2im import stock
from rdfc2im.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HM_PROJECT = os.path.join(ROOT, "in", "humanmine_project.xml")
SOURCES_YAML = os.path.join(ROOT, "rdfc2im", "data", "sources.yaml")


def _have_hm():
    """in/ is made by tools/make-inputs.sh (gitignored): the tests reading HumanMine's own
    project.xml skip on a checkout that has not run it."""
    return os.path.exists(HM_PROJECT)


def _sources_cfg():
    with open(SOURCES_YAML) as fh:
        return yaml.safe_load(fh)


def _entry(**kw):
    e = {"type": "go-annotation", "jar": "intermine", "licence": "CC BY 4.0", "redistributable": True,
         "data_dir": "go-annotation/current/human",
         "files": [{"id": "gaf", "url": "https://example.org/goa_human.gaf.gz",
                    "stage_as": "gene_association.goa_human",
                    "filter": {"format": "gaf", "ids": "uniprot"}}]}
    e.update(kw)
    return e


# ------------------------------------------------------------------ the real table

def test_the_table_is_valid_and_covers_the_milestone_1_sources():
    t = stock.load_table()
    for n in ("uniprot", "uniprot-fasta", "uniprot-keywords", "go-annotation", "ncbi-gff", "ncbi-fasta",
              "panther", "psi-intact", "biogrid", "psi-mi-ontology", "protein-atlas", "protein-atlas-rna",
              "gtex", "atlas-express", "hpo-annotation", "orphanet", "omim", "interpro-go"):
        assert n in t, n
    assert t["omim"]["redistributable"] is False and t["omim"]["local_copy"] == "required"


def test_every_entry_matches_humanmines_own_project_xml():
    """Name, type, version attribute (4.3.0 for humanmine-bio-sources jars) and data path."""
    if not _have_hm():
        return
    t = stock.load_table()
    root = etree.parse(HM_PROJECT).getroot()
    by_name = {s.get("name"): s for s in root.iter("source")}
    for n, e in t.items():
        s = by_name[n]
        assert s.get("type") == e["type"], n
        assert (s.get("version") == "4.3.0") == (e["jar"] == "humanmine-bio-sources"), n
        prop = e.get("data_property", "src.data.dir")
        loc = next(p.get("location") for p in s.iter("property") if p.get("name") == prop)
        want = f"/micklem/data/{e['data_dir']}" + (f"/{e['data_file']}" if prop == "src.data.file" else "")
        assert loc.rstrip("/") == want, (n, loc, want)
    # and so applying the table to HumanMine's project.xml raises no problem at all
    sources_el = copy.deepcopy(root.find("sources"))
    assert stock.apply_to_project(sources_el, t, list(t)) == []


def test_the_table_orders_cleanly_in_humanmines_project_xml():
    if not _have_hm():
        return
    t = stock.load_table()
    names = stock.project_order(HM_PROJECT)
    assert stock.order_problems(names, t, list(t)) == []


def test_a_verified_file_has_a_url_and_the_uniprot_files_use_the_ebi_mirror():
    for n, e in stock.load_table().items():
        for f in e["files"]:
            if f.get("verified"):
                assert f.get("url"), (n, f["id"])
            if n.startswith("uniprot") and f.get("url"):
                assert f["url"].startswith("https://ftp.ebi.ac.uk/pub/databases/uniprot/"), (n, f["url"])


# ------------------------------------------------------------------ table validation

def test_validation_names_each_problem():
    bad = {
        "a": _entry(jar="jcenter"),
        "b": _entry(redistributable=False),
        "c": _entry(files=[{"id": "x", "url": "https://e/x.tsv", "stage_as": "x.tsv",
                            "filter": {"format": "tab", "ids": "ensembl"}}]),
        "d": _entry(files=[{"id": "x", "url": "https://e/x.zip", "unpack": "zip", "member": "*.xml",
                            "filter": {"format": "gaf", "ids": "uniprot"}}]),
        "e": _entry(files=[{"id": "x", "url": "https://e/x.gz", "stage_as": "x.gz", "filter": "none"}]),
        "f": _entry(data_dir="/micklem/data/abs"),
        "g": _entry(needs=["nowhere"]),
        "h": _entry(files=[{"id": "x", "url": None, "stage_as": "x"}]),
        "i": _entry(files=[{"id": "x", "url": "https://e/x", "stage_as": "x",
                            "filter": {"format": "gaf", "ids": "none"}}]),
    }
    probs = " | ".join(stock.validate_table(bad))
    for needle in ("a: `jar`", "b: redistributable: false needs local_copy: required",
                   "c/x: format tab needs `column`", "d/x: a member glob unpacks several files",
                   "e/x: `stage_as` is a plain file name", "f: `data_dir` must be a relative path",
                   "g: needs 'nowhere'", "h/x: no `url`", "i/x: format gaf filters by ids"):
        assert needle in probs, (needle, probs)
    assert stock.validate_table({"ok": _entry()}) == []


# ------------------------------------------------------------------ selection

def test_check_orders_by_project_xml_and_refuses_unknown_and_repeated_names():
    if not _have_hm():
        return
    t = stock.load_table()
    order, probs = stock.select(t, ["go-annotation", "uniprot"], HM_PROJECT)
    assert order == ["uniprot", "go-annotation"] and probs == []
    _, probs = stock.select(t, ["uniprot", "uniprot", "nosuch"], HM_PROJECT)
    assert any("more than once: uniprot" in p for p in probs)
    assert any("unknown stock source(s) nosuch" in p for p in probs)


def test_check_refuses_a_stock_source_this_build_replaces():
    t = {"hgnc": _entry(type="hgnc", data_dir="human/hgnc/current")}
    _, probs = stock.select(t, ["hgnc"], None, ["hgnc", "go"], _sources_cfg())
    assert any("hgnc is replaced by humanmine-hgnc" in p for p in probs), probs
    _, probs = stock.select(t, ["hgnc"], None, ["go"], _sources_cfg())
    assert probs == []


def test_check_refuses_restricted_data_without_a_local_copy(tmp_path):
    if not _have_hm():
        return
    t = stock.load_table()
    _, probs = stock.select(t, ["omim"], HM_PROJECT)
    assert any("omim is not redistributable" in p and "lacks mimTitles.txt" in p for p in probs), probs
    (tmp_path / "omim").mkdir()
    for f in ("mimTitles.txt", "morbidmap.txt", "pubmed_cited"):
        (tmp_path / "omim" / f).write_text("x\n")
    assert stock.select(t, ["omim"], HM_PROJECT, local_dir=str(tmp_path)) == (["omim"], [])


def test_check_wants_needs_and_human():
    if not _have_hm():
        return
    t = stock.load_table()
    _, probs = stock.select(t, ["hpo-annotation"], HM_PROJECT)
    assert any("hpo-annotation needs omim" in p for p in probs), probs
    _, probs = stock.select(t, ["uniprot"], HM_PROJECT, taxa=["9606", "10090"])
    assert any("human (9606) only" in p for p in probs), probs


def test_order_constraints_map_replaced_names_to_their_replacement():
    t = {"ncbi-gff": _entry(type="ncbi-gff", after=["ncbi-gene"])}
    assert stock.order_problems(["humanmine-ncbigene", "ncbi-gff"], t, ["ncbi-gff"],
                                {"ncbi-gene": ["humanmine-ncbigene"]}) == []
    probs = stock.order_problems(["ncbi-gff", "humanmine-ncbigene"], t, ["ncbi-gff"],
                                 {"ncbi-gene": ["humanmine-ncbigene"]})
    assert probs == ["ncbi-gff must integrate after humanmine-ncbigene, but project.xml lists it before"]
    assert stock.order_problems(["ncbi-gff"], t, ["ncbi-gff"]) == []     # other end not loaded


# ------------------------------------------------------------------ project.xml rewrite

PROJECT = """<project type="bio"><sources>
  <source name="uniprot" type="uniprot">
    <property name="uniprot.organisms" value="9606 10090"/>
    <property name="src.data.dir" location="/micklem/data/uniprot/current/"/>
  </source>
  <source name="gtex" type="gtex"><property name="src.data.dir" location="/somewhere/else"/></source>
</sources></project>"""


def test_apply_rewrites_data_and_organism_properties_and_reports_mismatches():
    t = {"uniprot": _entry(type="uniprot", data_dir="uniprot/current",
                           properties={"uniprot.organisms": "9606", "uniprot.loadtrembl": "false"}),
         "gtex": _entry(type="gtex", jar="humanmine-bio-sources", data_dir="human/GTEx/current"),
         "omim": _entry(type="omim", data_dir="metabolic/omim/current")}
    sources_el = etree.fromstring(PROJECT).find("sources")
    probs = stock.apply_to_project(sources_el, t, ["uniprot", "gtex", "omim"])
    u = next(s for s in sources_el if s.get("name") == "uniprot")
    props = {p.get("name"): p.get("value") or p.get("location") for p in u.iter("property")}
    assert props == {"uniprot.organisms": "9606", "src.data.dir": "/micklem/data/uniprot/current",
                     "uniprot.loadtrembl": "false"}
    g = next(s for s in sources_el if s.get("name") == "gtex")
    assert [p.get("location") for p in g.iter("property")] == ["/micklem/data/human/GTEx/current"]
    assert any("gtex: jar origin humanmine-bio-sources needs version='4.3.0'" in p for p in probs), probs
    assert any('omim has no <source name="omim">' in p for p in probs), probs


# ------------------------------------------------------------------ rows for full-build.sh

def test_file_rows_say_how_each_file_is_made_and_staged(tmp_path):
    t = stock.load_table()
    rows = [r.split("\t") for r in stock.file_rows(t, ["uniprot", "panther", "psi-mi-ontology", "biogrid"],
                                                    "/S", "/S/cache")]
    assert all(len(r) == 16 for r in rows)
    by = {(r[0], r[1]): r for r in rows}
    u = by[("uniprot", "sprot")]
    assert u[2:5] == ["download", u[3], "/S/cache/stock-raw-uniprot/data/uniprot_sprot_human.xml.gz"]
    assert u[7:9] == ["uniprot-xml", "uniprot"] and u[12:16] == [
        "/S/subset/uniprot/sprot", "filtered", "uniprot/current", "9606_uniprot_sprot.xml"]
    p = by[("panther", "orthologs")]
    assert p[5:7] == ["tar.gz", "RefGenomeOrthologs"] and p[12:14] == ["/S/whole/panther/orthologs", "whole"]
    assert by[("psi-mi-ontology", "obo")][12:16] == ["-", "asis", "psi/ontology/current", "psi-mi.obo"]
    assert by[("biogrid", "organisms")][15] == "-"          # a member glob: staged under member names
    (tmp_path / "omim").mkdir()
    (tmp_path / "omim" / "mimTitles.txt").write_text("x\n")
    o = [r.split("\t") for r in stock.file_rows(t, ["omim"], "/S", "/S/cache", str(tmp_path))]
    assert o[0][2:5] == ["local", "-", str(tmp_path / "omim" / "mimTitles.txt")]
    assert o[1][2] == "download"                                # no local morbidmap.txt


def test_jar_rows_name_each_jar_once_at_its_origins_version():
    t = stock.load_table()
    rows = stock.jar_rows(t, ["uniprot-fasta", "ncbi-fasta", "gtex"], "6.0.0")
    assert rows == ["uniprot-fasta\tfasta\tintermine\tbio-source-fasta\t6.0.0",
                    "gtex\tgtex\thumanmine-bio-sources\tbio-source-gtex\t4.3.0"]


def test_cache_meta_keys_the_filter_spec_and_records_redistribution():
    t = stock.load_table()
    m = stock.cache_meta(t, "uniprot")
    assert m[1:] == ["redistributable=true", "licence=CC_BY_4.0_UniProt"]
    t2 = copy.deepcopy(t)
    t2["uniprot"]["files"][0]["filter"]["ids"] = "symbol"
    assert stock.cache_meta(t2, "uniprot")[0] != m[0]          # another filter, another cache key
    assert "redistributable=false" in stock.cache_meta(t, "omim")
    assert all(" " not in w for w in stock.cache_meta(t, "hpo-annotation"))


def test_postprocess_rows_follow_humanmines_post_processing_order(tmp_path):
    """[im-9n4.6] phase_postprocess runs the rows in the order printed: HumanMine's, not the table's."""
    t = stock.load_table()
    px = tmp_path / "project.xml"
    px.write_text('<project type="bio"><sources/><post-processing>'
                  '<post-process name="create-references"/><post-process name="transfer-sequences"/>'
                  '<post-process name="do-sources"/><post-process name="create-overlap-view"/>'
                  '<post-process name="create-chromosome-locations-and-lengths"/>'
                  '</post-processing></project>')
    rows = stock.postprocess_rows(t, ["ncbi-gff", "go-annotation", "ncbi-fasta"], str(px))
    names = [r.split("\t")[0] for r in rows]
    # the four HumanMine lists in its order; the ones it does not list follow in first-wanted order
    assert names[:4] == ["transfer-sequences", "do-sources", "create-overlap-view",
                         "create-chromosome-locations-and-lengths"], names
    assert set(names[4:]) == {"create-gene-flanking-features", "create-location-overlap-index"}, names
    assert "do-sources\tgo-annotation" in rows
    assert stock.postprocess_rows(t, ["uniprot", "uniprot-fasta", "uniprot-keywords"], str(px)) == []


def test_postprocess_rows_and_download_size():
    t = stock.load_table()
    assert stock.postprocess_rows(t, ["go-annotation", "ncbi-gff"])[0] == "do-sources\tgo-annotation"
    assert stock.download_bytes(t, ["uniprot", "go-annotation"]) == 174683391 + 15041996


# ------------------------------------------------------------------ CLI

def test_stock_check_cli(capsys):
    if not _have_hm():
        return
    assert main(["stock", "check", "go-annotation uniprot"]) == 0
    assert capsys.readouterr().out.strip() == "uniprot go-annotation"
    assert main(["stock", "check", "omim"]) == 1
    assert "not redistributable" in capsys.readouterr().err
    assert main(["stock", "meta", "uniprot", "--restore"]) == 0
    assert capsys.readouterr().out.startswith("--meta spec_md5=")
