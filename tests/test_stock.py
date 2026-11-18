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
    _, probs = stock.select(t, ["mgi-identifiers"], HM_PROJECT)
    assert any("mgi-identifiers needs panther" in p for p in probs), probs
    # OMIM's mimTitles.txt is optional for the current HPO files: hpo-annotation loads without omim [im-9n4.15]
    _, probs = stock.select(t, ["hpo-annotation"], HM_PROJECT)
    assert probs == [], probs
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


def test_a_load_first_stock_source_moves_ahead_of_the_rdfc2im_sources():
    """[im-9n4.6] Stock uniprot keys Protein on md5checksum only; after humanmine-hgnc (Protein by
    primaryAccession) it duplicated each protein, and the later merge left isoforms pointing at a
    deleted canonical protein. Loaded first, its objects are the ones the accession keys find."""
    from rdfc2im.project import _move_load_first
    sources_el = etree.fromstring(
        '<project><sources><source name="humanmine-hgnc" type="humanmine-items"/>'
        '<source name="so" type="so"/><source name="uniprot" type="uniprot"/>'
        '<source name="humanmine-uniprot" type="humanmine-items"/>'
        '<source name="uniprot-fasta" type="fasta"/></sources></project>').find("sources")
    _move_load_first(sources_el, ["uniprot"], log=lambda *a: None)
    assert [s.get("name") for s in sources_el] == ["uniprot", "humanmine-hgnc", "so", "humanmine-uniprot",
                                                   "uniprot-fasta"]
    t = stock.load_table()
    assert t["uniprot"]["load_first"] is True
    assert not any(t[n].get("load_first") for n in t if n != "uniprot")
    bad = dict(t, uniprot=dict(t["uniprot"], load_first="yes"))
    assert any("`load_first` must be true or false" in p for p in stock.validate_table(bad))


# ------------------------------------------------------------------ rows for full-build.sh

def test_file_rows_say_how_each_file_is_made_and_staged(tmp_path):
    t = stock.load_table()
    rows = [r.split("\t") for r in stock.file_rows(t, ["uniprot", "panther", "psi-mi-ontology", "biogrid"],
                                                    "/S", "/S/cache")]
    assert all(len(r) == 18 for r in rows)
    assert all(r[16] == "-" for r in rows)                    # keep_types: gff3 only
    by = {(r[0], r[1]): r for r in rows}
    u = by[("uniprot", "sprot")]
    assert u[2:5] == ["download", u[3], "/S/cache/stock-raw-uniprot/data/uniprot_sprot_human.xml.gz"]
    assert u[7:9] == ["uniprot-xml", "uniprot"] and u[12:16] == [
        "/S/subset/uniprot/sprot", "filtered", "uniprot/current", "9606_uniprot_sprot.xml"]
    p = by[("panther", "orthologs")]
    assert p[5:7] == ["tar.gz", "RefGenomeOrthologs"] and p[12:14] == ["/S/subset/panther/orthologs", "filtered"]
    assert by[("psi-mi-ontology", "obo")][12:16] == ["-", "asis", "psi/ontology/current", "psi-mi.obo"]
    assert by[("biogrid", "organisms")][15] == "-"          # a member glob: staged under member names
    (tmp_path / "omim").mkdir()
    (tmp_path / "omim" / "mimTitles.txt").write_text("x\n")
    o = [r.split("\t") for r in stock.file_rows(t, ["omim"], "/S", "/S/cache", str(tmp_path))]
    assert o[0][2:5] == ["local", "-", str(tmp_path / "omim" / "mimTitles.txt")]
    assert o[1][2] == "download"                                # no local morbidmap.txt


def test_psi_intact_is_filtered_from_the_zip_by_member_glob_with_its_xref_db():
    """[im-9n4.13] psi-xml reads the members of human.zip itself (a glob, which other formats refuse) and
    the xref db list travels in field 18; the spec, and so the cache key, includes it."""
    t = stock.load_table()
    r = stock.file_rows(t, ["psi-intact"], "/S", "/S/cache")[0].split("\t")
    assert r[5:9] == ["zip", "*.xml", "psi-xml", "uniprot"] and r[12:16] == [
        "/S/subset/psi-intact/human", "filtered", "psi/intact/current", "-"]
    assert r[17] == "uniprotkb"
    t2 = copy.deepcopy(t)
    t2["psi-intact"]["files"][0]["filter"]["xref_db"] = ["uniprotkb", "ensembl"]
    assert stock.file_rows(t2, ["psi-intact"], "/S", "/S/cache")[0].split("\t")[17] == "uniprotkb,ensembl"
    assert stock.cache_meta(t2, "psi-intact")[0] != stock.cache_meta(t, "psi-intact")[0]
    assert stock.validate_table(t) == []


def test_only_psi_xml_may_filter_a_member_glob_and_xref_db_is_its_own():
    t = stock.load_table()
    bad = copy.deepcopy(t)
    bad["psi-intact"]["files"][0]["filter"] = {"format": "tab", "ids": "uniprot", "column": "1"}
    assert any("only a single file can be filtered" in p for p in stock.validate_table(bad))
    bad = copy.deepcopy(t)
    bad["panther"]["files"][0]["filter"]["xref_db"] = ["uniprotkb"]
    assert any("`xref_db` is for format psi-xml only" in p for p in stock.validate_table(bad))
    bad = copy.deepcopy(t)
    bad["psi-intact"]["files"][0]["filter"]["xref_db"] = "uniprotkb"
    assert any("`xref_db` must be a list" in p for p in stock.validate_table(bad))


def test_ncbi_gff_rows_keep_gene_rows_and_derive_the_chromosome_lengths():
    """[im-9n4.9] A last `derived` row makes the lengths file from the filtered GFF into the same
    filtered group, staged in its own directory for the ncbi-gff-lengths source; keep_types (the
    neighbour gene rows) travels in field 17 when the table sets it (off: its cost, BUILD.md)."""
    t = stock.load_table()
    rows = [r.split("\t") for r in stock.file_rows(t, ["ncbi-gff"], "/S", "/S/cache")]
    assert [r[1] for r in rows] == ["gff", "chromosome-lengths"]
    g, d = rows
    assert g[7:9] == ["gff3", "entrez"] and g[13] == "filtered" and g[16] == "-"
    t2 = copy.deepcopy(t)
    t2["ncbi-gff"]["files"][0]["filter"]["keep_types"] = ["gene"]
    assert stock.file_rows(t2, ["ncbi-gff"], "/S", "/S/cache")[0].split("\t")[16] == "gene"
    assert stock.cache_meta(t2, "ncbi-gff")[0] != stock.cache_meta(t, "ncbi-gff")[0]
    assert d[2] == "derived" and d[4] == "/S/subset/ncbi-gff/gff/GRCh38_latest_genomic.gff"
    assert d[7] == "chromosome-lengths" and d[12:16] == [
        "/S/subset/ncbi-gff/chromosome-lengths", "derived", "human/gff/lengths", "chromosome_lengths.xml"]
    assert stock.lengths_sources(t, ["uniprot", "ncbi-gff"]) == [
        ("ncbi-gff", "ncbi-gff-lengths", "/micklem/data/human/gff/lengths/chromosome_lengths.xml")]
    assert t["ncbi-gff"]["priority_first"] == ["Gene.chromosome"]
    # the genome FASTA is cut to the mapped chromosomes and needs the GFF
    f = [r.split("\t") for r in stock.file_rows(t, ["ncbi-fasta"], "/S", "/S/cache")][0]
    assert f[7:9] == ["fasta", "chromosomes"] and t["ncbi-fasta"]["needs"] == ["ncbi-gff"]
    m = stock.cache_meta(t, "ncbi-gff")[0]
    t2 = copy.deepcopy(t)
    del t2["ncbi-gff"]["chromosome_lengths"]
    assert stock.cache_meta(t2, "ncbi-gff")[0] != m           # the lengths file is part of the group


def test_validation_of_keep_types_lengths_and_priority_first():
    gff = {"id": "gff", "url": "https://e/x.gff.gz", "stage_as": "x.gff",
           "filter": {"format": "gff3", "ids": "entrez", "keep_types": ["gene"]}}
    ok = _entry(type="ncbi-gff", data_dir="human/gff/current", files=[gff],
                chromosome_lengths={"from": "gff", "source": "gff-lengths", "data_dir": "human/gff/lengths"},
                priority_first=["Gene.chromosome"])
    assert stock.validate_table({"ncbi-gff": ok}) == []
    bad = {
        "a": _entry(files=[dict(_entry()["files"][0], filter={"format": "gaf", "ids": "uniprot",
                                                              "keep_types": ["gene"]})]),
        "b": dict(ok, chromosome_lengths={"from": "nope", "source": "x-lengths", "data_dir": "d/l"}),
        "c": dict(ok, chromosome_lengths={"from": "gff", "source": "x-lengths", "data_dir": "human/gff/current"}),
        "d": dict(ok, priority_first=["chromosome"]),
        "e": dict(ok, chromosome_lengths={"from": "gff", "source": "a", "data_dir": "d/l"}),
    }
    probs = " | ".join(stock.validate_table(bad))
    for needle in ("a/gaf: `keep_types` is for format gff3 only", "b: chromosome_lengths `from`",
                   "c: chromosome_lengths `data_dir`", "d: `priority_first`",
                   "e: chromosome_lengths `source` must be a new"):
        assert needle in probs, (needle, probs)


def test_jar_rows_name_each_jar_once_at_its_origins_version():
    t = stock.load_table()
    rows = stock.jar_rows(t, ["uniprot-fasta", "ncbi-fasta", "gtex"], "6.0.0")
    assert rows == ["uniprot-fasta\tfasta\tintermine\tbio-source-fasta\t6.0.0",
                    "gtex\tgtex\thumanmine-bio-sources\tbio-source-gtex\t4.3.0"]


def test_cache_meta_keys_the_filter_spec_and_records_redistribution():
    t = stock.load_table()
    m = stock.cache_meta(t, "uniprot")
    assert m[1:] == ["redistributable=true", "licence=CC-BY-4.0"]
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


def test_resolver_rows_are_the_taxon_then_the_selected_sources_partner_organisms():
    table = stock.load_table()
    rows = [r.split("\t") for r in stock.resolver_rows(table, ["panther", "uniprot"], "9606")]
    assert [r[0] for r in rows] == ["9606", "10116", "7955"]
    assert rows[1][1] == "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Rattus_norvegicus.gene_info.gz"
    assert [r[0] for r in map(lambda x: x.split("\t"), stock.resolver_rows(table, ["uniprot"], "9606"))] == ["9606"]


def test_a_resolver_taxon_without_a_known_gene_info_file_is_refused():
    table = copy.deepcopy(stock.load_table())
    table["panther"]["resolver_taxa"] = [99999]
    assert any("resolver_taxa" in p for p in stock.validate_table(table))


def test_mgi_and_rgd_are_cut_to_the_partner_id_sets():
    table = stock.load_table()
    assert table["mgi-identifiers"]["files"][0]["filter"] == {"format": "tab", "ids": "mgi", "column": "1"}
    assert table["rgd-identifiers"]["files"][0]["filter"]["ids"] == "rgd"
    assert table["panther"]["files"][0]["filter"] == {"format": "tab", "ids": "uniprot", "column": "1,2"}


# ------------------------------------------------------------------ expression and disease sources [im-9n4.14, im-9n4.15]

def test_expression_sources_stage_only_the_files_their_converters_accept():
    """Each converter throws on, or double-loads, an unexpected file in its directory (humanmine-bio-sources,
    d67fc5d): the table stages exactly one file for three of them and none of the wrong kind for gtex."""
    t = stock.load_table()
    staged = {n: [f["stage_as"] for f in t[n]["files"]]
              for n in ("protein-atlas", "protein-atlas-rna", "gtex", "atlas-express", "hpo-annotation", "orphanet")}
    assert staged["protein-atlas"] == ["normal_ihc_data.tsv", "tissue_to_organ.tsv"]
    assert staged["protein-atlas-rna"] == ["rna_tissue_consensus.tsv"]
    assert staged["atlas-express"] == ["E-MTAB-513-fpkms.tsv"]
    assert staged["orphanet"] == ["en_product1.xml"]
    assert staged["gtex"] == ["GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct"]
    assert "gene_median" in staged["gtex"][0] and "signif" not in staged["gtex"][0]
    assert staged["hpo-annotation"] == ["genes_to_phenotype.txt", "phenotype.hpoa"]


def test_gtex_keeps_three_header_lines_and_the_hpo_file_is_cut_in_two_stages():
    t = stock.load_table()
    gt = t["gtex"]["files"][0]["filter"]
    assert gt["keep_header"] == 3 and gt["ids"] == "ensembl"
    rows = [r.split("\t") for r in stock.file_rows(t, ["gtex", "protein-atlas"], "/S", "/S/cache")]
    assert rows[0][11] == "3" and rows[1][11] == "1"
    g2p, hpoa = t["hpo-annotation"]["files"]
    assert g2p["filter"]["ids"] == "entrez" and hpoa["filter"]["ids"] == "hpo-diseases"
    assert stock.filter_spec(t["gtex"]["files"][0]).endswith("keep_header=3")
    assert stock.filter_spec(g2p).endswith("keep_header")      # as before: existing cache specs do not change


def test_hpo_annotation_has_no_omim_file_property_and_no_omim_dependency():
    t = stock.load_table()
    e = t["hpo-annotation"]
    assert not e.get("needs")
    assert e["properties"] == {"hpo.disease.file": ""}
    assert stock.validate_table(t) == []


def test_expression_and_disease_files_are_redistributable_and_hpa_says_share_alike():
    t = stock.load_table()
    for n in ("protein-atlas", "protein-atlas-rna", "gtex", "atlas-express", "hpo-annotation", "orphanet"):
        assert t[n]["redistributable"] is True, n
    # the Human Protein Atlas page states CC BY 4.0, not share-alike (read 2026-11-18, im-9n4.45)
    assert t["protein-atlas"]["licence"] == t["protein-atlas-rna"]["licence"] == "CC-BY-4.0"
    assert t["omim"]["redistributable"] is False


def test_every_source_has_a_complete_licence_record():
    """im-9n4.45: the licence is what the source states, with the page, the date and a status; an unread licence
    says so (`not verified`) instead of carrying a guess."""
    t = stock.load_table()
    for n, e in t.items():
        assert e["licence_status"] in stock.LICENCE_STATUSES, n
        assert e["licence_checked"] == "2026-11-18" or e["licence_status"] == "not-checked", n
        assert e.get("licence_conditions"), n
        assert e.get("redistributable_reason"), n
        if e["licence_status"] in ("verified", "partial"):
            assert e["licence_url"].startswith("http") and e["licence_quote"], n
        if e["licence_status"] in ("not-verified", "not-stated"):
            assert e["licence"].startswith("not verified"), n
    rdf = _sources_cfg()
    for n in ("go", "ncbigene", "reactome", "hgnc", "ensembl", "uniprot", "clinvar", "gwascatalog", "pubmed", "hpo"):
        assert not stock.licence_problems(n, rdf[n]) and rdf[n]["licence_status"], n
        assert rdf[n]["licence_checked"] == "2026-11-18" and rdf[n]["redistributable_reason"], n
        assert "rdfportal_licence_note" in rdf[n], n
    other = stock.other_licences()
    assert set(other) == {"reactome", "ncbi-gene-info", "bluegenes-tools", "imjs"}
    assert other["reactome"]["licence"] == "CC0-1.0"


def test_docs_licences_names_every_source():
    """docs/LICENCES.md is the summary of the YAML records: no source may be missing from it."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "LICENCES.md"), encoding="utf-8") as fh:
        doc = fh.read()
    for n in stock.load_table():
        assert f"`{n}`" in doc, n
    for n in ("go", "ncbigene", "reactome", "hgnc", "ensembl", "uniprot", "clinvar", "gwascatalog", "pubmed", "hpo"):
        assert f"RDF `{n}`" in doc, n
    for s in ("gene_info", "BlueGenes tools", "imjs"):
        assert s in doc, s


def test_licence_problems_reports_a_malformed_record():
    bad = {"licence_status": "verified", "licence_checked": "18 Nov", "licence_conditions": "text"}
    msgs = stock.licence_problems("x", bad)
    assert any("YYYY-MM-DD" in m for m in msgs) and any("list of strings" in m for m in msgs)
    assert any("licence_url" in m for m in msgs) and any("licence_quote" in m for m in msgs)
    assert stock.licence_problems("x", {"licence_status": "maybe"})
    assert stock.licence_problems("x", {}) == []          # a table older than im-9n4.45 still loads
    info = stock.licence_info({"licence": "MIT", "licence_status": "verified", "redistributable": True})
    assert info["name"] == "MIT" and info["conditions"] == [] and info["quote"] is None


def test_disease_name_priority_ranks_orphanet_above_hpo_annotation():
    """hpo-annotation sets no Disease.name; ranked above orphanet it starved the names of the diseases both load."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "curation", "priorities_override.properties")
    line = next(l for l in open(path, encoding="utf-8") if l.startswith("Disease.name"))
    order = [w.strip() for w in line.split("=", 1)[1].split(",")]
    assert order.index("orphanet") < order.index("hpo-annotation"), order
