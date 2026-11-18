"""tools/panelapp_lists.py: PanelApp panels to HumanMine gene lists [im-9n4.21].

tests/fixtures/panelapp/ holds real PanelApp v1 responses (fetched 2026-11-18) cut down to a few genes: panel 91
(a name with a comma, one Green gene short of its non-Green one), 165 (Green and Amber genes and an STR), 59 (a
non-Green gene with no GRCh38 Ensembl id), 263 (a name with a slash) and 9 (a panel renamed since 2021, with a
region); two index pages joined by `next`, and names_2021.tsv, the 171 `<Panel_name>`s of HumanMine's 2021 lists
with the current panel each one is. No network: the HTTP layer is injected.
"""
import io
import json
import os
import sys
import urllib.error

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import panelapp_lists as P  # noqa: E402

FX = os.path.join(HERE, "fixtures", "panelapp")
BASE = P.API_BASE + "/panels/"


def fx(name):
    with open(os.path.join(FX, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeApi:
    """The PanelApp, from the fixture files. Counts requests like Http does."""

    def __init__(self):
        self.requests = 0
        self.urls = []
        self.pages = {BASE: fx("panels_page1.json"), BASE + "?page=2": fx("panels_page2.json"),
                      P.API_BASE + "/panels/signedoff/": fx("signedoff_page1.json")}
        for pid in (9, 59, 91, 165, 263):
            self.pages[f"{BASE}{pid}/"] = fx(f"panel_{pid}.json")

    def get_json(self, url):
        self.requests += 1
        self.urls.append(url)
        if url not in self.pages:
            raise P.FetchError(f"unexpected URL {url}")
        return self.pages[url]


@pytest.fixture
def raw(tmp_path):
    out = str(tmp_path / "raw")
    P.fetch(out, FakeApi(), today="2026-11-18", log=lambda *_: None)
    return out


def tree(root):
    files = {}
    for d, _, names in os.walk(root):
        for n in names:
            with open(os.path.join(d, n), "rb") as fh:
                files[os.path.relpath(os.path.join(d, n), root)] = fh.read()
    return files


# ---------------------------------------------------------------------------------------------- fetch

def test_fetch_follows_next_and_saves_every_panel(tmp_path):
    api = FakeApi()
    meta = P.fetch(str(tmp_path), api, today="2026-11-18", log=lambda *_: None)
    assert api.urls[:3] == [BASE, BASE + "?page=2", P.API_BASE + "/panels/signedoff/"]
    assert api.requests == 3 + 5 and meta["requests"] == 8
    assert sorted(os.listdir(tmp_path / "panels")) == sorted(f"{i}.json" for i in (9, 59, 91, 165, 263))
    assert meta["panels"] == 5 and meta["fetch_date"] == "2026-11-18"
    assert [p["id"] for p in meta["panel_list"]] == [9, 59, 91, 165, 263]
    by = {p["id"]: p for p in meta["panel_list"]}
    assert by[165]["name"] == "Hereditary spastic paraplegia" and by[165]["version"] == "1.316"
    assert by[165]["version_created"].startswith("2025-11-23")
    assert (by[165]["genes_all"], by[165]["genes_green"], by[165]["strs"], by[165]["regions"]) == (5, 3, 1, 0)
    assert by[9]["regions"] == 1 and meta["strs_total"] == 1 and meta["regions_total"] == 1
    assert meta["genes_green_total"] == sum(p["genes_green"] for p in meta["panel_list"])
    assert os.path.exists(tmp_path / "META.json") and os.path.exists(tmp_path / "panels-index.json")


def test_fetch_resumes_without_refetching_unchanged_panels(raw):
    api = FakeApi()
    meta = P.fetch(raw, api, today="2026-11-18", log=lambda *_: None)
    assert api.requests == 3 and meta["panels_resumed_from_disk"] == 5
    api2 = FakeApi()
    P.fetch(raw, api2, today="2026-11-18", log=lambda *_: None, resume=False)
    assert api2.requests == 8


def test_fetch_refuses_a_loop_and_a_wrong_panel(tmp_path):
    api = FakeApi()
    api.pages[BASE + "?page=2"] = dict(api.pages[BASE + "?page=2"], next=BASE)
    with pytest.raises(P.FetchError, match="loop"):
        P.fetch(str(tmp_path / "a"), api, log=lambda *_: None)
    api = FakeApi()
    api.pages[f"{BASE}91/"] = api.pages[f"{BASE}59/"]
    with pytest.raises(P.FetchError, match="panel 91"):
        P.fetch(str(tmp_path / "b"), api, log=lambda *_: None)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_retries_429_and_5xx_with_backoff_and_identifies_itself():
    calls, sleeps, headers = [], [], []

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        headers.append(req.get_header("User-agent"))
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", {"Retry-After": "7"}, io.BytesIO(b""))
        if len(calls) == 2:
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, io.BytesIO(b""))
        return FakeResp(b'{"ok": true}')

    h = P.Http(sleep=sleeps.append, urlopen=urlopen, clock=lambda: 0.0)
    assert h.get_json("https://x/y") == {"ok": True}
    assert h.requests == 3 and headers == ["rdfc2im-panelapp-lists/1.0"] * 3
    assert 7.0 in sleeps and 4.0 in sleeps          # Retry-After honoured; then the back-off, 2 s doubling per attempt


def test_http_spaces_requests_and_does_not_retry_a_404():
    now = [0.0]
    sleeps = []

    def urlopen(req, timeout=None):
        if req.full_url.endswith("missing"):
            raise urllib.error.HTTPError(req.full_url, 404, "no", {}, io.BytesIO(b""))
        return FakeResp(b"{}")

    h = P.Http(sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)), urlopen=urlopen, clock=lambda: now[0])
    h.get_json("https://x/a")
    h.get_json("https://x/b")
    assert sleeps == [P.MIN_INTERVAL]               # at most 2 requests a second
    with pytest.raises(P.FetchError, match="HTTP 404"):
        h.get_json("https://x/missing")
    assert h.requests == 3


def test_http_gives_up_after_the_retries():
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b""))

    h = P.Http(retries=2, sleep=lambda s: None, urlopen=urlopen, clock=lambda: 0.0)
    with pytest.raises(P.FetchError, match="giving up after 3 attempts"):
        h.get_json("https://x/y")
    assert h.requests == 3


# ---------------------------------------------------------------------------------------------- Green filtering

def test_only_green_genes_and_strs_regions_counted_not_listed():
    p = fx("panel_165.json")
    assert [g["entity_name"] for g in P.green_genes(p)] == ["ABCD1", "ABHD16A", "ADAR"]
    lst = P.build_list(p, "2026-11-18")
    assert [g["symbol"] for g in lst["genes"]] == ["ABCD1", "ABHD16A", "ADAR"]
    assert lst["counts"] == {"genes_green": 3, "genes_other_confidence": 2, "strs_ignored": 1, "regions_ignored": 0}
    assert P.build_list(fx("panel_9.json"), "2026-11-18")["counts"]["regions_ignored"] == 1
    lst91 = P.build_list(fx("panel_91.json"), "2026-11-18")
    assert [g["symbol"] for g in lst91["genes"]] == ["ALAS2", "FECH"]       # CLPX is red (0)


def test_a_panel_listing_a_gene_twice_gets_it_once():
    p = fx("panel_91.json")
    p["genes"] = p["genes"] + [p["genes"][0]]
    assert [g["symbol"] for g in P.build_list(p, "2026-11-18")["genes"]] == ["ALAS2", "FECH"]


def test_gene_record_fields_and_the_non_green_gene_without_grch38():
    rec = P.gene_record(fx("panel_91.json")["genes"][0])
    assert rec["hgnc_id"] == "HGNC:397" and rec["symbol"] == "ALAS2" and rec["ensembl_grch38"] == "ENSG00000158578"
    hplh1 = [g for g in fx("panel_59.json")["genes"] if g["entity_name"] == "HPLH1"][0]
    assert P.gene_record(hplh1)["ensembl_grch38"] is None and P.gene_record(hplh1)["ensembl_release"] is None


def test_ensembl_grch38_takes_the_newest_release_and_survives_odd_values():
    gd = {"ensembl_genes": {"GRch37": {"82": {"ensembl_id": "ENSG1"}},
                            "GRch38": {"90": {"ensembl_id": "ENSG2"}, "105": {"ensembl_id": "ENSG3"}, "99": {}}}}
    assert P.ensembl_grch38(gd) == ("ENSG3", "105")
    assert P.ensembl_grch38({"ensembl_genes": "{}"}) == (None, None)        # PanelApp sends "{}" as a string
    assert P.ensembl_grch38({"ensembl_genes": json.dumps({"GRch38": {"90": {"ensembl_id": "ENSG9"}}})}) == ("ENSG9", "90")
    assert P.ensembl_grch38({"ensembl_genes": None}) == (None, None)
    assert P.ensembl_grch38({}) == (None, None)
    assert P.ensembl_grch38({"ensembl_genes": {"GRch37": {"82": {"ensembl_id": "ENSG1"}}}}) == (None, None)


# ---------------------------------------------------------------------------------------------- names

def names_2021():
    with open(os.path.join(FX, "names_2021.tsv"), encoding="utf-8") as fh:
        rows = [l.rstrip("\n").split("\t") for l in fh][1:]
    return [(a, b, int(c)) for a, b, c in rows]


def test_the_naming_rule_reproduces_the_2021_names_of_panels_that_still_exist():
    rows = names_2021()
    assert len(rows) == 171
    same = [r for r in rows if P.list_suffix(r[1]) == r[0]]
    assert len(same) == 154                      # 154 of 171 reproduced by the rule alone
    for suffix, panel_name, pid in rows:
        if P.list_suffix(panel_name) != suffix:  # the other 17 are exactly the renamed panels
            assert P.RENAMED_SINCE_2021[pid] == suffix
    assert len(P.RENAMED_SINCE_2021) == 17
    # unusual characters the 2021 names carried unchanged
    for panel_name, suffix in (("Erythropoietic protoporphyria, mild variant", "Erythropoietic_protoporphyria,_mild_variant"),
                               ("Familial Tumours Syndromes of the central & peripheral Nervous system",
                                "Familial_Tumours_Syndromes_of_the_central_&_peripheral_Nervous_system"),
                               ("Glaucoma (developmental)", "Glaucoma_(developmental)"),
                               ("Radial dysplasia", "Radial_dysplasia")):
        assert P.list_suffix(panel_name) == suffix
        assert P.list_name(panel_name) == "PL_GenomicsEngland_GenePanel:" + suffix


def test_name_exceptions_and_whitespace():
    assert P.list_suffix("Amyotrophic lateral sclerosis/motor neuron disease ") == \
        "Amyotrophic_lateral_sclerosis_motor_neuron_disease"
    assert P.list_suffix("  A   B ") == "A_B"
    assert P.file_stem("PL_GenomicsEngland_GenePanel:Glaucoma_(developmental)") == \
        "PL_GenomicsEngland_GenePanel__Glaucoma_(developmental)"
    assert P.file_stem("PL_x:a/b c") == "PL_x__a_b_c"


def test_renamed_panels_follow_the_current_name_and_say_what_they_replace():
    p = fx("panel_9.json")
    new = P.build_list(p, "2026-11-18")
    assert new["name"] == "PL_GenomicsEngland_GenePanel:Differences_in_sex_development"
    assert new["replaces"] == "PL_GenomicsEngland_GenePanel:Disorders_of_sex_development"
    old = P.build_list(p, "2026-11-18", keep_2021_names=True)
    assert old["name"] == "PL_GenomicsEngland_GenePanel:Disorders_of_sex_development" and old["replaces"] is None
    assert P.build_list(fx("panel_91.json"), "2026-11-18")["replaces"] is None


# ---------------------------------------------------------------------------------------------- list definition

def test_description_carries_version_date_and_the_corrected_2021_text():
    lst = P.build_list(fx("panel_165.json"), "2026-11-18")
    d = lst["description"]
    assert d.startswith("Gene panel from the Genomics England PanelApp. Only genes with a high level of confidence "
                        "(Green level) are included.")
    assert "Panel 165, version 1.316 (created 2025-11-23), fetched 2026-11-18." in d
    assert "See https://panelapp.genomicsengland.co.uk/panels/165/ for more details. " + P.ATTRIBUTION_TEXT == d[d.index("See "):]
    assert d.endswith("Non-commercial use only; not for diagnostic use or medical decision-making.")
    assert "authored by Genomics England and its contributors" in d and "Terms of Use (December 2019)" in d
    assert "Decemeber" not in d
    assert lst["type"] == "Gene" and lst["tags"] == ["Genomics England gene panel", "im:public"]


def test_identifier_order_is_hgnc_then_ensembl_then_symbol():
    assert P.ID_ORDER == ("hgnc_id", "ensembl_id", "symbol")
    rec = {"hgnc_id": "HGNC:397", "ensembl_grch38": "ENSG00000158578", "symbol": "ALAS2"}
    assert P.candidate_identifiers(rec) == [("hgnc_id", "HGNC:397"), ("ensembl_id", "ENSG00000158578"), ("symbol", "ALAS2")]
    assert P.candidate_identifiers(dict(rec, ensembl_grch38=None)) == [("hgnc_id", "HGNC:397"), ("symbol", "ALAS2")]
    assert P.candidate_identifiers(dict(rec, hgnc_id=None)) == [("ensembl_id", "ENSG00000158578"), ("symbol", "ALAS2")]
    assert P.candidate_identifiers({"symbol": "X"}) == [("symbol", "X")]


def test_lists_output_files_index_and_determinism(raw, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    idx = P.make_lists(raw, a)
    P.make_lists(raw, b)
    assert tree(a) == tree(b)                    # same input, same bytes
    assert [r["name"] for r in idx] == [
        "PL_GenomicsEngland_GenePanel:Differences_in_sex_development",
        "PL_GenomicsEngland_GenePanel:Haematological_malignancies_cancer_susceptibility",
        "PL_GenomicsEngland_GenePanel:Erythropoietic_protoporphyria,_mild_variant",
        "PL_GenomicsEngland_GenePanel:Hereditary_spastic_paraplegia",
        "PL_GenomicsEngland_GenePanel:Amyotrophic_lateral_sclerosis_motor_neuron_disease"]
    assert sorted(tree(a)) == sorted([
        "index.json", "index.tsv",
        "lists/PL_GenomicsEngland_GenePanel__Differences_in_sex_development.json",
        "lists/PL_GenomicsEngland_GenePanel__Haematological_malignancies_cancer_susceptibility.json",
        "lists/PL_GenomicsEngland_GenePanel__Erythropoietic_protoporphyria,_mild_variant.json",
        "lists/PL_GenomicsEngland_GenePanel__Hereditary_spastic_paraplegia.json",
        "lists/PL_GenomicsEngland_GenePanel__Amyotrophic_lateral_sclerosis_motor_neuron_disease.json"])
    one = json.load(open(os.path.join(a, "lists", "PL_GenomicsEngland_GenePanel__Hereditary_spastic_paraplegia.json")))
    assert one["panel"]["version"] == "1.316" and one["genes"][0]["hgnc_id"] == "HGNC:61"
    tsv = open(os.path.join(a, "index.tsv"), encoding="utf-8").read().splitlines()
    assert tsv[0] == "name\tpanel_id\tversion\tgenes\treplaces\texists_in_mine"
    assert len(tsv) == 6


def test_select_100k_keeps_the_2021_panel_type_only(raw, tmp_path):
    types = {p["id"]: p["types"] for p in P.load_json(os.path.join(raw, "META.json"))["panel_list"]}
    idx = P.make_lists(raw, str(tmp_path / "k"), select="100k")
    assert {r["panel_id"] for r in idx} == {pid for pid, t in types.items() if "rare-disease-100k" in t}
    assert 0 < len(idx) < 5


def test_lists_notes_which_lists_a_mine_already_has(raw, tmp_path):
    class Mine:
        def get_json(self, url):
            assert url == "http://m/humanmine/service/lists?format=json"
            return {"lists": [{"name": "PL_GenomicsEngland_GenePanel:Hereditary_spastic_paraplegia"}]}

    idx = P.make_lists(raw, str(tmp_path / "o"), mine="http://m/humanmine/", http=Mine())
    assert {r["name"].split(":")[1]: r["exists_in_mine"] for r in idx}["Hereditary_spastic_paraplegia"] is True
    assert sum(1 for r in idx if r["exists_in_mine"]) == 1


def test_two_panels_with_one_list_name_are_refused(raw, tmp_path):
    p = P.load_json(os.path.join(raw, "panels", "91.json"))
    p2 = P.load_json(os.path.join(raw, "panels", "165.json"))
    p2["name"] = p["name"].upper().replace("_", " ")
    assert P.list_suffix(p["name"]) != P.list_suffix(p2["name"])
    p2["name"] = p["name"] + " "                    # differs only in trailing whitespace
    P.dump_json(os.path.join(raw, "panels", "165.json"), p2)
    with pytest.raises(P.FetchError, match="same list name"):
        P.make_lists(raw, str(tmp_path / "o"))


# ---------------------------------------------------------------------------------------------- resolve

class FakeMine:
    """The id resolution service of a mine, in the shape of the web service's category-keyed results.
    `table`: lower-case identifier -> [(gene id, category, reason)]; anything else is unresolved."""

    def __init__(self, table):
        self.table, self.jobs, self.calls, self.fail_first = table, {}, [], False

    def get_json(self, url):
        return self.request("GET", url)

    def request(self, method, url, body=None, timeout=None):
        self.calls.append((method, url.split("/service/")[1]))
        if url.endswith("/service/version"):
            return {"version": 30, "statusCode": 200}
        if method == "POST":
            uid = f"job{len(self.jobs)}"
            self.jobs[uid] = body
            assert body["type"] == "Gene" and body["extra"] == "H. sapiens"
            return {"uid": uid, "statusCode": 200}
        uid = url.split("/service/ids/")[1].split("/")[0]
        if method == "DELETE":
            return {}
        if url.endswith("/status"):
            return {"status": "SUCCESS", "statusCode": 200}
        matches = {"MATCH": [], "DUPLICATE": [], "OTHER": [], "TYPE_CONVERTED": [], "WILDCARD": []}
        unresolved = []
        for ident in self.jobs[uid]["identifiers"]:
            hits = self.table.get(ident.lower(), [])
            if not hits:
                unresolved.append(ident)
            elif hits[0][1] == "MATCH":
                matches["MATCH"].append({"id": hits[0][0], "input": [ident], "summary": {}})
            else:
                matches[hits[0][1]].append({"input": ident, "reason": hits[0][2],
                                            "matches": [{"id": h[0], "summary": {}} for h in hits]})
        return {"results": {"matches": matches, "unresolved": unresolved, "stats": {}, "type": "Gene"}}


def mine_table(raw):
    """What the fake mine knows: ALAS2 by HGNC id; FECH only by Ensembl id; ABCD1's HGNC id as a synonym; ABHD16A's
    HGNC id on two genes; ADAR only by symbol; the rest nowhere (ANG, ALS2, ACD, ... unresolved)."""
    meta, panels = P.read_panels(raw)
    recs = {r["symbol"]: r for r in (P.gene_record(g) for p in panels for g in P.green_genes(p))}
    t = {}
    t[recs["ALAS2"]["hgnc_id"].lower()] = [(101, "MATCH", None)]
    t[recs["FECH"]["ensembl_grch38"].lower()] = [(102, "MATCH", None)]
    t[recs["ABCD1"]["hgnc_id"].lower()] = [(103, "OTHER", "Synonym")]
    t[recs["ABHD16A"]["hgnc_id"].lower()] = [(104, "DUPLICATE", "Gene identifier"), (105, "DUPLICATE", "Gene identifier")]
    t["adar"] = [(106, "MATCH", None)]
    t["alas2"] = [(101, "MATCH", None)]
    return t, recs


def test_resolve_counts_each_identifier_type_alone_and_as_a_chain(raw, tmp_path):
    table, recs = mine_table(raw)
    mine = FakeMine(table)
    out = str(tmp_path / "res.json")
    res = P.resolve(raw, "http://m/humanmine", out, http=mine, sleep=lambda s: None, log=lambda *_: None)
    t = res["total"]
    assert res["mine_version"] == 30 and res["id_order"] == ["hgnc_id", "ensembl_id", "symbol"]
    # 12 Green gene entries: 91 has 2, 165 has 3, 59 has 2, 263 has 2, 9 has 2 -> 11
    assert t["genes"] == 11
    assert {k: v for k, v in t["hgnc_id"].items() if k != "unique_by_category"} == \
        {"have": 11, "unique": 2, "ambiguous": 1, "unresolved": 8}                          # ALAS2, ABCD1 / ABHD16A
    assert t["hgnc_id"]["unique_by_category"] == {"MATCH": 1, "OTHER": 1}                   # ABCD1 is a synonym match
    assert res["distinct"]["by_identifier"]["hgnc_id"] == {"unique": 2, "ambiguous": 1, "unresolved": 8}
    assert t["ensembl_id"]["unique"] == 1 and t["symbol"]["unique"] == 2                   # FECH / ALAS2, ADAR
    c = t["chain"]
    assert c["resolved"] == 4 and c["by_hgnc_id"] == 2 and c["by_ensembl_id"] == 1 and c["by_symbol"] == 1
    assert c["fallback"] == 2 and c["ambiguous"] == 1 and c["unresolved"] == 6 and c["conflict"] == 0
    assert res["panels"]["91"]["chain"]["resolved"] == 2 and res["panels"]["165"]["chain"]["ambiguous"] == 1
    assert res["distinct"]["distinct_genes"] == 11
    # three jobs, one per identifier type, none of them one request per gene
    assert sum(1 for m, p in mine.calls if m == "POST") == 3
    assert [j["identifiers"] for j in mine.jobs.values()][0] == sorted({r["hgnc_id"] for r in recs.values()})
    assert all(m in ("GET", "POST", "DELETE") for m, _ in mine.calls)                    # nothing else


def test_unresolved_report_format(raw, tmp_path):
    table, recs = mine_table(raw)
    out = str(tmp_path / "res.json")
    res = P.resolve(raw, "http://m/humanmine", out, http=FakeMine(table), sleep=lambda s: None, log=lambda *_: None)
    lines = open(out + ".unresolved.tsv", encoding="utf-8").read().splitlines()
    assert lines[0].split("\t") == ["panel_id", "panel", "symbol", "hgnc_id", "ensembl_grch38", "status", "resolved_by",
                                    "conflict", "hgnc_outcome", "ensembl_outcome", "symbol_outcome", "why"]
    rows = {l.split("\t")[2]: l.split("\t") for l in lines[1:]}
    assert "ALAS2" not in rows                                  # resolved by HGNC id: not a problem
    assert rows["FECH"][5] == "resolved-by-fallback" and rows["FECH"][6] == "ensembl_id"
    assert rows["ADAR"][5] == "resolved-by-fallback" and rows["ADAR"][6] == "symbol"
    assert "ABCD1" not in rows       # its HGNC id matched through a synonym: still the first identifier, still unique
    assert rows["ABHD16A"][5] == "ambiguous" and rows["ABHD16A"][8] == "ambiguous:DUPLICATE"
    assert "hgnc_id matches 2 genes" in rows["ABHD16A"][11]
    assert rows["ANG"][5] == "unresolved" and rows["ANG"][8] == "unresolved"
    assert len(lines) - 1 == len(res["problems"]) == 9
    genes = open(out + ".genes.tsv", encoding="utf-8").read().splitlines()
    assert genes[0].split("\t")[:5] == ["hgnc_id", "symbol", "ensembl_grch38", "status", "resolved_by"]
    g = {l.split("\t")[1]: l.split("\t") for l in genes[1:]}
    assert g["ALAS2"][3:6] == ["resolved", "hgnc_id", "101"] and g["ANG"][3] == "unresolved" and len(genes) - 1 == 11
    again = str(tmp_path / "res2.json")
    P.resolve(raw, "http://m/humanmine", again, http=FakeMine(table), sleep=lambda s: None, log=lambda *_: None)
    assert open(out + ".unresolved.tsv").read() == open(again + ".unresolved.tsv").read()   # deterministic


def test_resolve_flags_a_gene_that_two_identifier_types_place_on_different_genes(raw, tmp_path):
    table, recs = mine_table(raw)
    table["alas2"] = [(999, "MATCH", None)]                     # the symbol finds another gene than the HGNC id
    res = P.resolve(raw, "http://m/humanmine", str(tmp_path / "r.json"), http=FakeMine(table), sleep=lambda s: None,
                    log=lambda *_: None)
    assert res["total"]["chain"]["conflict"] == 1
    assert [p["symbol"] for p in res["problems"] if p["conflict"]] == ["ALAS2"]


def test_resolve_waits_for_a_mine_that_is_down_and_never_reports_the_outage(raw):
    class Down(FakeMine):
        def __init__(self, table, down_for):
            super().__init__(table)
            self.down_for = down_for

        def request(self, method, url, body=None, timeout=None):
            if self.down_for > 0 and url.endswith("/service/version"):
                self.down_for -= 1
                raise P.FetchError("connection refused")
            return super().request(method, url, body, timeout)

    table, _ = mine_table(raw)
    slept = []
    mine = Down(table, 3)
    out = P.resolve_values("http://m/humanmine", {"hgnc:99999999"}, mine, "H. sapiens", sleep=slept.append, log=lambda *_: None)
    assert slept == [30, 30, 30] and out["hgnc:99999999"]["status"] == "unresolved"
    never = Down(table, 10 ** 6)
    with pytest.raises(P.FetchError, match="connection refused"):
        P.wait_for_mine("http://m/humanmine", never, max_wait=60, sleep=lambda s: None, log=lambda *_: None)


def test_parse_ids_results_categories():
    results = {"matches": {"MATCH": [{"id": 1, "input": ["A", "a2"], "summary": {"symbol": "A1", "primaryIdentifier": "11"}}],
                           "DUPLICATE": [{"input": "B", "reason": "x", "matches": [{"id": 2}, {"id": 3}]}],
                           "OTHER": [{"input": "C", "reason": "Synonym", "matches": [{"id": 4}]}],
                           "TYPE_CONVERTED": [], "WILDCARD": []},
               "unresolved": ["D"]}
    found, unresolved = P.parse_ids_results(results)
    assert found["a"] == {"genes": [1], "categories": ["MATCH"], "reasons": [],
                          "summaries": {1: {"symbol": "A1", "primaryIdentifier": "11"}}}
    assert found["b"]["genes"] == [2, 3] and found["c"]["reasons"] == ["Synonym"] and unresolved == {"d"}


# ---------------------------------------------------------------------------------------------- command line

def test_cli_lists_and_fetch_cache(raw, tmp_path, monkeypatch, capsys):
    out = str(tmp_path / "lists")
    assert P.main(["lists", "--in", raw, "--out", out]) == 0
    assert "5 lists" in capsys.readouterr().out
    assert os.path.exists(os.path.join(out, "index.json"))
    # fetch with --cache-dir saves the rdfc2im cache group, marked not redistributable
    monkeypatch.setattr(P, "Http", lambda **kw: FakeApi())
    cache = str(tmp_path / "cache")
    assert P.main(["fetch", "--out", str(tmp_path / "f"), "--cache-dir", cache]) == 0
    info = P.load_json(os.path.join(cache, "panelapp", "META.json"))
    assert info["meta"]["redistributable"] == "false" and info["meta"]["panels"] == "5"
    assert os.path.exists(os.path.join(cache, "panelapp", "data", "panels", "91.json"))
