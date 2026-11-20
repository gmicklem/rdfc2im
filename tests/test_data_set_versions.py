"""DataSet.version from what the build loaded [im-9n4.52].

Gos, 20 Nov 2026: "drop the 34 non-matching static data-set entries and do rebuild the file (if it is needed) from what
the build actually loads with real versions and dates". humanmine-static (HumanMine's datasets.xml of February 2022) is
gone; tools/source_pages.py data-set-links writes, for every data set the selected sources write, DataSet.version from
the build's own evidence (the release the file states, its Last-Modified, the date the build fetched it: the cache
groups' META.json), and the DataSource url/description HumanMine's file gave that stay accurate (the stock mapping
files' data_source_url / data_source_description). All offline, on small cache trees made here."""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402

import source_manifest as sm  # noqa: E402
import source_pages as sp  # noqa: E402
from rdfc2im import stock  # noqa: E402


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _group(root, name, saved_at, meta, files=None):
    for rel, text in (files or {}).items():
        _w(os.path.join(root, name, "data", rel), text)
    _w(os.path.join(root, name, "META.json"), json.dumps({"saved_at": saved_at, "meta": meta}))
    _w(os.path.join(root, name, "MD5SUMS"), "".join(f"0  data/{rel}\n" for rel in (files or {})))


# Four stock sources and two RDF ones:
#   relsrc   its file states a release ("#release: 7 (Jan 2026)") and the server sent a Last-Modified
#   datesrc  no release in the file, Last-Modified known: a date, never a release
#   bare     neither: only the date the build fetched the file
#   twofiles one data set fed by one file of the source, another fed by none (data_set_files)
#   streamed a streamed file: no raw group, the filtered group's META holds the Last-Modified and the stream time
#   nocache  selected, nothing cached (a local copy): no version, rather than one without evidence
TABLE = """sources:
  relsrc:
    type: relsrc
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: relsrc
    files:
      - {id: rows, url: "https://example.org/rel.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: x.tsv, filter: none}
  datesrc:
    type: datesrc
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: datesrc
    files:
      - {id: rows, url: "https://example.org/date.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: x.tsv, filter: none}
  bare:
    type: bare
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: bare
    files:
      - {id: rows, url: "https://example.org/bare.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: x.tsv, filter: none}
  twofiles:
    type: twofiles
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: twofiles
    files:
      - {id: median, url: "https://example.org/x_v8_median.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: x.tsv, filter: none}
  streamed:
    type: streamed
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: streamed
    files:
      - {id: matches, url: "https://example.org/big.dat.gz", verified: true, size: 1, last_modified: "2026-01-02",
         stage_as: big.dat, stream: true, filter: {format: tab, ids: uniprot, column: "1"}}
  nocache:
    type: nocache
    jar: intermine
    licence: CC0-1.0
    redistributable: true
    data_dir: nocache
    files:
      - {id: rows, url: "https://example.org/n.tsv", verified: true, size: 1, last_modified: "2026-01-02", stage_as: x.tsv, filter: none}
"""

MAPPINGS = {
    "relsrc": {"data_source": "Rel DB", "data_sets": ["Rel data set"],
               "data_source_url": "https://rel.example.org/", "data_source_description": "The Rel database",
               "files": [{"id": "rows", "format": "tab",
                          "release": [{"from": "line", "pattern": "^#release: (.*)$", "label": "release"}]}]},
    "datesrc": {"data_source": "Date DB", "data_sets": ["Date data set", "Shared data set"],
                "files": [{"id": "rows", "format": "tab"}]},
    "bare": {"data_source": "Date DB", "data_sets": ["Bare data set", "Shared data set"],
             "data_source_url": "https://date.example.org/",
             "files": [{"id": "rows", "format": "tab"}]},
    "twofiles": {"data_source": "Two DB", "data_sets": ["Median data", "Empty eQTL data"],
                 "data_set_files": {"Empty eQTL data": []},
                 "files": [{"id": "median", "format": "tab",
                            "release": [{"from": "url", "pattern": "_(v\\d+)_", "label": "Two"}]}]},
    "streamed": {"data_source": "Big DB", "data_sets": ["Big data set"], "files": [{"id": "matches", "format": "tab"}]},
    "nocache": {"data_source": "No DB", "data_sets": ["Nothing cached"], "files": [{"id": "rows", "format": "tab"}]},
}

SOURCES_YAML = """toyrdf:
  data_source_name: Toy
  data_set_title: Toy (RDF Portal)
otherrdf:
  data_source_name: Other
  data_set_title: Other (RDF Portal)
"""


def _tree(tmp_path):
    stock_dir = str(tmp_path / "stock")
    raw = os.path.join(stock_dir, "cache")
    filtered = str(tmp_path / "filtered")
    rdf = str(tmp_path / "rdfcache")
    _group(raw, "stock-raw-relsrc", "2026-11-18T03:00:00Z",
           {"last_modified.rows": "2026-01-02T10:00:00Z", "url.rows": "https://example.org/rel.tsv"},
           {"rel.tsv": "#release: 7 (Jan 2026)\na\tb\n"})
    _group(raw, "stock-raw-datesrc", "2026-11-18T04:00:00Z",
           {"last_modified.rows": "2026-11-04T14:16:56Z", "url.rows": "https://example.org/date.tsv"},
           {"date.tsv": "a\tb\n"})
    _group(raw, "stock-raw-bare", "2026-11-19T05:00:00Z",
           {"last_modified.rows": "unknown", "url.rows": "https://example.org/bare.tsv"}, {"bare.tsv": "a\n"})
    _group(raw, "stock-raw-twofiles", "2026-11-18T05:08:10Z",
           {"last_modified.median": "2023-03-20T18:05:03Z", "url.median": "https://example.org/x_v8_median.tsv"},
           {"x_v8_median.tsv": "a\n"})
    _group(filtered, "stock-streamed", "2026-11-20T04:30:13Z",
           {"release.matches": "2026-11-04T19:25:31Z", "genes_md5": "g"}, {"matches/big.dat": "P1\tx\n"})
    _group(rdf, "toyrdf", "2026-11-18T07:18:25Z", {"scope": "full"}, {"main.tsv": "?id\n"})
    _group(rdf, "otherrdf", "2026-09-21T17:25:00Z", {"scope": "none"}, {"main.tsv": "?id\n"})
    tpath = _w(str(tmp_path / "table.yaml"), TABLE)
    mdir = str(tmp_path / "mappings")
    for n, mp in MAPPINGS.items():
        doc = dict(mp, source=n, loader={"repository": "intermine", "path": n, "commit": "abc1234"})
        _w(os.path.join(mdir, n + ".yaml"), yaml.safe_dump(doc, sort_keys=False))
    syaml = _w(str(tmp_path / "sources.yaml"), SOURCES_YAML)
    return dict(stock_dir=stock_dir, filtered_cache=filtered, cache_dir=rdf, table=stock.load_table(tpath),
                mappings_dir=mdir, sources_yaml=syaml)


ALL_STOCK = ["relsrc", "datesrc", "bare", "twofiles", "streamed", "nocache"]


def _versions(tmp_path, stock_names=ALL_STOCK, rdf_names=("toyrdf",)):
    return sp.data_set_versions(list(stock_names), list(rdf_names), **_tree(tmp_path))


# ---------------------------------------------------------------- the facts, from the caches

def test_the_facts_of_a_stock_file_come_from_its_raw_cache_group(tmp_path):
    t = _tree(tmp_path)
    (f,) = sm.stock_file_facts("relsrc", t["table"]["relsrc"], sp.load_mapping("relsrc", t["mappings_dir"]),
                               t["stock_dir"], t["filtered_cache"])
    assert (f["release"], f["last_modified"], f["fetched_at"]) == (
        "release 7 (Jan 2026)", "2026-01-02T10:00:00Z", "2026-11-18T03:00:00Z")


def test_a_streamed_file_without_a_raw_group_takes_its_dates_from_the_filtered_group(tmp_path):
    t = _tree(tmp_path)
    (f,) = sm.stock_file_facts("streamed", t["table"]["streamed"], {}, t["stock_dir"], t["filtered_cache"])
    assert (f["release"], f["last_modified"], f["fetched_at"]) == (None, "2026-11-04T19:25:31Z", "2026-11-20T04:30:13Z")


def test_a_filtered_cut_of_an_older_download_keeps_its_own_date_and_claims_no_fetch_time(tmp_path):
    """The filtered group records the Last-Modified of the raw file it was cut from (release.<id>): when the raw group
    holds a newer download, the loaded rows are the older file's, and the raw group's fetch time is not theirs."""
    t = _tree(tmp_path)
    e = {"files": [{"id": "rows", "url": "https://example.org/date.tsv", "filter": {"format": "tab", "ids": "entrez"}}]}
    _group(t["filtered_cache"], "stock-datesrc", "2026-11-18T05:00:00Z", {"release.rows": "2025-06-01T00:00:00Z"})
    (f,) = sm.stock_file_facts("datesrc", e, {}, t["stock_dir"], t["filtered_cache"])
    assert (f["last_modified"], f["fetched_at"]) == ("2025-06-01T00:00:00Z", None)


# ---------------------------------------------------------------- the version of each data set

def test_a_source_that_states_its_release_gives_the_release_and_the_fetch_date(tmp_path):
    v = _versions(tmp_path)
    assert v["Rel data set"] == "release 7 (Jan 2026); fetched 2026-11-18"


def test_a_source_with_only_dates_gives_dates_never_a_release(tmp_path):
    v = _versions(tmp_path)
    assert v["Date data set"] == "Last-Modified 2026-11-04; fetched 2026-11-18"
    assert v["Bare data set"] == "fetched 2026-11-19"       # Last-Modified unknown: the fetch date alone
    assert v["Big data set"] == "Last-Modified 2026-11-04; fetched 2026-11-20"


def test_a_data_set_two_sources_write_carries_both_sources_evidence(tmp_path):
    v = _versions(tmp_path)
    assert v["Shared data set"] == "Last-Modified 2026-11-04; fetched 2026-11-18, 2026-11-19"


def test_an_rdf_source_gives_the_date_of_its_sparql_extract(tmp_path):
    v = _versions(tmp_path)
    assert v["Toy (RDF Portal)"] == "SPARQL extract fetched 2026-11-18"


def test_a_data_set_no_file_of_the_build_feeds_gets_no_version(tmp_path):
    v = _versions(tmp_path)
    assert v["Median data"] == "Two v8; fetched 2026-11-18"     # a file's stated release stands for its Last-Modified
    assert v["Empty eQTL data"] is None
    assert v["Nothing cached"] is None                             # no evidence: nothing is written


def test_a_source_left_out_of_the_build_has_no_record(tmp_path):
    v = _versions(tmp_path, stock_names=["relsrc"], rdf_names=[])
    assert set(v) == {"Rel data set"}
    assert "Toy (RDF Portal)" not in v and "Other (RDF Portal)" not in v and "Date data set" not in v


# ---------------------------------------------------------------- the items file

def _items(tmp_path, base_url=None, **kw):
    t = _tree(tmp_path)
    stock_names, rdf_names = kw.get("stock_names", ALL_STOCK), kw.get("rdf_names", ["toyrdf"])
    pages = sp.data_set_pages(stock_names, rdf_names, t["mappings_dir"], t["sources_yaml"])
    versions = sp.data_set_versions(stock_names, rdf_names, **t)
    sources = sp.data_source_records(stock_names, t["mappings_dir"])
    return sp.data_set_links_xml(pages, base_url, versions, sources)


def _parse(xml):
    out = {}
    for it in ET.fromstring(xml):
        a = {x.get("name"): x.get("value") for x in it.findall("attribute")}
        out[(it.get("class"), a["name"])] = a
    return out


def test_the_items_carry_the_versions_and_no_link_without_a_base_url(tmp_path):
    got = _parse(_items(tmp_path))
    assert got[("DataSet", "Rel data set")] == {"name": "Rel data set", "version": "release 7 (Jan 2026); fetched 2026-11-18"}
    assert got[("DataSet", "Toy (RDF Portal)")]["version"] == "SPARQL extract fetched 2026-11-18"
    # nothing to say about these two: no item, so the loader cannot make an empty DataSet of its own
    assert ("DataSet", "Empty eQTL data") not in got and ("DataSet", "Nothing cached") not in got
    assert not any("url" in a for (c, _), a in got.items() if c == "DataSet")


def test_with_a_base_url_every_data_set_also_gets_its_page_and_the_version_where_known(tmp_path):
    got = _parse(_items(tmp_path, "https://example.org/pages"))
    assert got[("DataSet", "Empty eQTL data")]["url"] == "https://example.org/pages/stock-twofiles.md"
    assert "version" not in got[("DataSet", "Empty eQTL data")]
    assert got[("DataSet", "Rel data set")]["url"] == "https://example.org/pages/stock-relsrc.md"
    assert got[("DataSet", "Rel data set")]["version"].startswith("release 7")


def test_the_data_sources_hold_only_what_the_mapping_files_give(tmp_path):
    got = _parse(_items(tmp_path))
    assert got[("DataSource", "Rel DB")] == {"name": "Rel DB", "url": "https://rel.example.org/",
                                             "description": "The Rel database"}
    assert got[("DataSource", "Date DB")] == {"name": "Date DB", "url": "https://date.example.org/"}
    assert ("DataSource", "Two DB") not in got and ("DataSource", "HumanMine") not in got


def test_two_mappings_that_disagree_on_a_data_source_are_refused(tmp_path):
    t = _tree(tmp_path)
    p = os.path.join(t["mappings_dir"], "datesrc.yaml")
    mp = yaml.safe_load(open(p, encoding="utf-8"))
    mp["data_source_url"] = "https://elsewhere.example.org/"
    _w(p, yaml.safe_dump(mp))
    try:
        sp.data_source_records(["datesrc", "bare"], t["mappings_dir"])
    except ValueError as e:
        assert "Date DB" in str(e)
    else:
        raise AssertionError("conflicting data_source_url accepted")


def test_the_items_file_is_byte_identical_when_made_again(tmp_path):
    a = _items(tmp_path / "a", "https://example.org/pages")
    b = _items(tmp_path / "b", "https://example.org/pages")
    assert a == b
    assert _items(tmp_path / "c", stock_names=list(reversed(ALL_STOCK))) == _items(tmp_path / "d")


def test_the_cli_writes_the_file_from_the_caches(tmp_path):
    t = _tree(tmp_path)
    out = str(tmp_path / "links.xml")
    rc = sp.main(["data-set-links", "--out", out, "--stock-sources", "relsrc bare", "--sources", "",
                  "--stock-dir", t["stock_dir"], "--filtered-cache", t["filtered_cache"], "--cache-dir", t["cache_dir"],
                  "--stock-table", str(tmp_path / "table.yaml"), "--mappings", t["mappings_dir"]])
    assert rc == 0
    got = _parse(open(out, encoding="utf-8").read())
    assert got[("DataSet", "Rel data set")]["version"] == "release 7 (Jan 2026); fetched 2026-11-18"
    assert got[("DataSet", "Bare data set")]["version"] == "fetched 2026-11-19"


def test_add_links_source_ranks_the_source_first_for_the_version(tmp_path):
    proj = _w(str(tmp_path / "project.xml"), '<project type="bio">\n  <sources>\n'
              '    <source name="humanmine-go" type="humanmine-items" version="4.3.0">\n'
              '      <property name="src.data.file" location="/d/go.xml"/>\n    </source>\n  </sources>\n</project>\n')
    pri = _w(str(tmp_path / "p.properties"), "DataSet.version = x, *\n")
    for _ in range(2):
        sp.add_links_source(proj, pri, "/d/links.xml")
    ptext = open(pri, encoding="utf-8").read()
    assert ptext.count("DataSet.version = data-set-links, *") == 1 and "DataSet.version = x" not in ptext


def test_add_links_source_goes_before_the_sources_that_read_the_mine(tmp_path):
    """[im-9n4.56] update-data-sources, update-publications and entrez-organism read what every loader stored;
    data-set-links is a loader (DataSets, DataSources), so it goes in front of the first of them, not at the end."""
    proj = _w(str(tmp_path / "project.xml"), '<project type="bio">\n  <sources>\n'
              '    <source name="humanmine-go" type="humanmine-items" version="4.3.0">\n'
              '      <property name="src.data.file" location="/d/go.xml"/>\n    </source>\n'
              '    <source name="gtex" type="gtex"/>\n'
              '    <source name="update-data-sources" type="update-data-sources"/>\n'
              '    <source name="update-publications" type="update-publications"/>\n'
              '    <source name="entrez-organism" type="entrez-organism"/>\n  </sources>\n</project>\n')
    pri = _w(str(tmp_path / "p.properties"), "")
    sp.add_links_source(proj, pri, "/d/links.xml")
    text = open(proj, encoding="utf-8").read()
    names = re.findall(r'<source name="([^"]+)"', text)
    assert names == ["humanmine-go", "gtex", "data-set-links", "update-data-sources", "update-publications",
                     "entrez-organism"], names
    assert '<source name="data-set-links" type="humanmine-items" version="4.3.0">' in text
    # without a mine reader it is the last source, as before
    proj2 = _w(str(tmp_path / "project2.xml"), '<project type="bio">\n  <sources>\n'
               '    <source name="gtex" type="gtex"/>\n  </sources>\n</project>\n')
    sp.add_links_source(proj2, pri, "/d/links.xml")
    assert re.findall(r'<source name="([^"]+)"', open(proj2, encoding="utf-8").read()) == ["gtex", "data-set-links"]


# ---------------------------------------------------------------- the repository's own files

def test_the_real_mapping_files_agree_on_every_data_source_they_describe():
    names = sorted(n[:-5] for n in os.listdir(sp.MAPPINGS_DIR))
    recs = sp.data_source_records(names)             # raises on a disagreement
    # what HumanMine's datasets.xml gave and stays accurate, for the DataSources no UniProt abbreviation covers
    assert recs["NCBI"]["url"] == "https://www.ncbi.nlm.nih.gov"
    for n in ("Panther", "UniProt", "ArrayExpress", "The Human Protein Atlas", "GTEx portal", "Human Phenotype Ontology",
              "The Mouse genome database (MGD) from Mouse Genome Informatics (MGI)"):
        assert recs[n]["url"].startswith("http"), n
    # update-data-sources (UniProt's dbxref.txt) describes these: no second value from us
    for n in ("BioGRID", "IntAct", "Reactome", "HGNC", "Orphanet", "InterPro", "MGI"):
        assert n not in recs, n


def test_gtex_says_no_file_of_this_build_feeds_its_eqtl_data_set():
    mp = sp.load_mapping("gtex")
    assert mp["data_set_files"] == {"Single-Tissue cis-eQTL Data": []}


def test_humanmine_static_is_retired_with_a_reason():
    t = stock.load_table()
    assert "humanmine-static" not in t
    _, probs = stock.select(t, ["humanmine-static", "uniprot"])
    assert any("humanmine-static" in p and "im-9n4.52" in p and "data-set-links" in p for p in probs), probs
    assert not os.path.exists(os.path.join(sp.MAPPINGS_DIR, "humanmine-static.yaml"))


def test_the_data_source_fields_rank_the_generated_source_first_then_update_data_sources():
    path = os.path.join(ROOT, "curation", "priorities_override.properties")
    lines = {ln.split("=", 1)[0].strip(): [w.strip() for w in ln.split("=", 1)[1].split(",")]
             for ln in open(path, encoding="utf-8") if ln.startswith("DataSource.")}
    for f in ("DataSource.url", "DataSource.description"):
        assert lines[f] == ["data-set-links", "update-data-sources", "*"], lines


def test_an_older_cut_takes_its_release_from_the_cut_itself_not_from_the_newer_download(tmp_path):
    """BioGRID's case on the ut stack: the cut was made from the download of 04:20 (release.<id> in its group), the raw
    group holds a later one (11:42). The release is read from the cut's own file names, the raw file is not probed."""
    t = _tree(tmp_path)
    e = {"files": [{"id": "rows", "url": "https://example.org/date.tsv", "filter": {"format": "psi-xml", "ids": "entrez"}}]}
    mp = {"files": [{"id": "rows", "format": "xml",
                     "release": [{"from": "member_name", "pattern": r"-(\d+\.\d+\.\d+)\.psi25\.xml$", "label": "release"}]}]}
    _group(t["filtered_cache"], "stock-datesrc", "2026-11-18T04:40:38Z", {"release.rows": "2026-11-18T04:20:41Z"},
           {"rows/BIOGRID-ORGANISM-Homo_sapiens-5.0.263.psi25.xml": "<x/>"})
    (f,) = sm.stock_file_facts("datesrc", e, mp, t["stock_dir"], t["filtered_cache"])
    assert (f["release"], f["last_modified"], f["fetched_at"]) == ("release 5.0.263", "2026-11-18T04:20:41Z", None)
    assert sp.version_label([f]) == "release 5.0.263"


def test_stated_releases_come_before_the_dates_of_the_files_that_state_none():
    facts = [{"release": None, "last_modified": "2026-11-04T19:25:31Z", "fetched_at": "2026-11-20T04:30:13Z"},
             {"release": "InterPro 111.0", "last_modified": "2026-11-04T19:19:12Z", "fetched_at": "2026-11-20T03:28:47Z"}]
    assert sp.version_label(facts) == "InterPro 111.0; Last-Modified 2026-11-04; fetched 2026-11-20"
    assert sp.version_label([]) is None
