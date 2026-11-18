"""tools/apply_public_lists.py [im-9n4.22, T2.3]: archive first, upload as the superuser, no duplicates, stale lists
removed, the production guard. No network: the web service and the export script are injected; the PanelApp panels
are the fixtures of test_panelapp_lists.py (panels 9, 59, 91, 165 and 263)."""
import json
import os
import sys
import urllib.parse

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import apply_public_lists as A  # noqa: E402
import panelapp_lists as P  # noqa: E402
from test_panelapp_lists import FakeApi  # noqa: E402

MINE = "http://localhost:18090/humanmine"
TODAY = "2026-11-18"
PREFIX = P.LIST_PREFIX
GE = P.LIST_TAGS            # ["Genomics England gene panel", "im:public"]
RENAMED = PREFIX + "Disorders_of_sex_development"        # panel 9, renamed since 2021
RENAMED_NOW = PREFIX + "Differences_in_sex_development"
EMPTY_PANEL = PREFIX + "Haematological_malignancies_cancer_susceptibility"   # panel 59: emptied by the tests


def quiet(*_a, **_k):
    pass


@pytest.fixture
def cache(tmp_path):
    out = str(tmp_path / "panelapp")
    P.fetch(out, FakeApi(), today="2026-11-18", log=quiet)
    return out


@pytest.fixture
def cache_with_empty_panel(cache):
    path = os.path.join(cache, "panels", "59.json")
    panel = P.load_json(path)
    panel["genes"] = []
    P.dump_json(path, panel)
    return cache


def write_legacy(root, lists):
    """lists: [(name, type, description, tags, members)] in the layout of an archive directory."""
    os.makedirs(os.path.join(root, "members"))
    out, index = [], ["file\tlist_name\trows_exported"]
    for i, (name, type_, desc, tags, members) in enumerate(lists):
        out.append({"name": name, "type": type_, "description": desc, "tags": tags, "size": len(members)})
        fn = f"legacy{i}.tsv"
        with open(os.path.join(root, "members", fn), "w", encoding="utf-8") as fh:
            fh.write(f"{type_}.primaryIdentifier\tx\n" + "".join(f"{m}\tsym\n" for m in members))
        index.append(f"{fn}\t{name}\t{len(members)}")
    with open(os.path.join(root, "lists.json"), "w", encoding="utf-8") as fh:
        json.dump({"lists": out}, fh)
    with open(os.path.join(root, "members", "INDEX.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(index) + "\n")
    return root


@pytest.fixture
def legacy(tmp_path):
    return write_legacy(str(tmp_path / "legacy"), [
        ("PL_Legacy_genes", "Gene", "Some genes.", ["im:favourite", "im:public"], ["101", "102", "103", "999"]),
        ("PL_Legacy_proteins", "Protein", "", ["im:public"], ["P1", "P2"]),
        ("PL_Legacy_snps", "SNP", "SNPs.", ["im:public"], ["rs1"]),
        ("PL_Legacy_whole", "Gene", "All of them.", ["im:public"], ["101", "102"]),
    ])


class FakeService:
    """The mine's web service in memory: lists by name, a resolver, and a record of every call in order."""

    def __init__(self, cache_dir=None, classes=("Gene", "Protein"), legacy_ids=None, unplaced=()):
        self.calls, self.store = [], {}
        self.classes = list(classes)
        self.token = None
        self.legacy_ids = legacy_ids if legacy_ids is not None else {"Gene": {"101", "102", "103"}, "Protein": set()}
        self.table = {}
        if cache_dir:
            _, panels = P.read_panels(cache_dir)
            n = 0
            for p in panels:
                for rec in P.green_records(p):
                    key = A.gene_key(rec)
                    if key in unplaced or any(v in unplaced for _, v in P.candidate_identifiers(rec)):
                        continue
                    n += 1
                    for kind, v in P.candidate_identifiers(rec):
                        self.table[v.lower()] = (kind, f"{5000 + n}", f"obj{n}")

    def seed(self, name, type_="Gene", tags=GE, size=3, description="old"):
        self.store[name] = {"name": name, "type": type_, "tags": list(tags), "size": size, "description": description}

    # the interface apply_public_lists uses
    def wait(self, seconds):
        self.calls.append(("wait", seconds))

    def login(self):
        self.calls.append(("login",))
        self.token = "tok"
        return "tok"

    def lists(self, token=None):
        self.calls.append(("lists", bool(token)))
        return [dict(l) for l in self.store.values() if token or A.PUBLIC_TAG in l["tags"]]

    def model_classes(self):
        return {c: {} for c in self.classes}

    def resolve(self, type_, values):
        self.calls.append(("resolve", type_, len(set(values))))
        out = {}
        for v in set(values):
            k = v.lower()
            if type_ == "Gene" and k in self.table:
                kind, pid, obj = self.table[k]
                out[k] = {"status": "unique", "genes": [obj], "summaries": {obj: {"primaryIdentifier": pid}},
                          "categories": ["OTHER"] if kind == "hgnc_id" else ["MATCH"]}
            elif v in self.legacy_ids.get(type_, ()):
                out[k] = {"status": "unique", "genes": ["o" + v], "summaries": {}, "categories": ["MATCH"]}
            else:
                out[k] = {"status": "unresolved", "genes": [], "summaries": {}, "categories": []}
        return out

    def upload(self, name, type_, description, tags, identifiers, extra=A.ORGANISM):
        self.calls.append(("upload", name))
        assert self.token, "upload before login"
        self.store[name] = {"name": name, "type": type_, "tags": list(tags), "size": len(set(identifiers)),
                            "description": description}
        return {"size": len(set(identifiers)), "unmatched": []}

    def delete(self, name):
        self.calls.append(("delete", name))
        assert self.token, "delete before login"
        del self.store[name]

    def names(self, what):
        return [c[1] for c in self.calls if c[0] == what]


def make_exporter(service, fail=None):
    """An exporter that archives what the fake mine holds, in the layout of the T2.1 script."""
    def export(service_url, out_dir):
        service.calls.append(("export", out_dir))
        if fail:
            raise fail
        lists = service.lists()
        service.calls.pop()                                 # not a call of the tool's own
        os.makedirs(os.path.join(out_dir, "members"), exist_ok=True)
        with open(os.path.join(out_dir, "lists.json"), "w", encoding="utf-8") as fh:
            json.dump({"lists": lists}, fh)
        with open(os.path.join(out_dir, "members", "INDEX.tsv"), "w", encoding="utf-8") as fh:
            fh.write("file\tlist_name\trows_exported\n" + "".join(f"f{i}.tsv\t{l['name']}\t{l['size']}\n"
                                                                    for i, l in enumerate(lists)))
    return export


def args_for(tmp_path, cache_dir, *more, legacy_dir=None):
    argv = ["--mine", MINE, "--panelapp-cache", cache_dir, "--archive-repo", str(tmp_path / "archive"), *more]
    if legacy_dir:
        argv += ["--legacy", legacy_dir]
    return A.parse_args(argv)


def go(tmp_path, cache_dir, svc, *more, legacy_dir=None, exporter=None, today=TODAY):
    a = args_for(tmp_path, cache_dir, *more, legacy_dir=legacy_dir)
    return A.run(a, svc, exporter or make_exporter(svc), today=today, log=quiet)


def archive_dirs(tmp_path):
    base = tmp_path / "archive" / "humanmine-public-lists"
    return sorted(os.listdir(base)) if base.exists() else []


# ---------------------------------------------------------------------------------------------- archive first

def test_the_archive_is_made_before_anything_is_written_to_the_mine(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    kinds = [c[0] for c in svc.calls]
    assert "export" in kinds
    first_write = min(i for i, k in enumerate(kinds) if k in ("login", "upload", "delete"))
    assert kinds.index("export") < first_write
    assert kinds.index("export") < kinds.index("resolve")


def test_a_failing_archive_stops_before_any_upload_or_removal(tmp_path, cache):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Retired")
    with pytest.raises(A.ArchiveError):
        go(tmp_path, cache, svc, exporter=make_exporter(svc, fail=RuntimeError("request failed twice")))
    assert not [c for c in svc.calls if c[0] in ("login", "upload", "delete", "resolve")], svc.calls
    assert PREFIX + "Retired" in svc.store
    d = tmp_path / "archive" / "humanmine-public-lists" / TODAY
    assert (d / "FAILED.txt").read_text().startswith("RuntimeError: request failed twice")


def test_an_export_script_that_exits_is_a_failed_archive_too(tmp_path, cache):
    svc = FakeService(cache)
    with pytest.raises(A.ArchiveError, match="stopped"):
        go(tmp_path, cache, svc, exporter=make_exporter(svc, fail=SystemExit(2)))
    assert not [c for c in svc.calls if c[0] in ("login", "upload", "delete")]


def test_a_size_mismatch_in_the_export_log_fails_the_archive(tmp_path, cache):
    svc = FakeService(cache)

    def export(url, out):
        make_exporter(svc)(url, out)
        with open(os.path.join(out, "export.log"), "w") as fh:
            fh.write("MISMATCH PL_x: size=3 exported=2\n")
    with pytest.raises(A.ArchiveError, match="MISMATCH"):
        go(tmp_path, cache, svc, exporter=export)
    assert not svc.names("upload")


def test_an_existing_archive_directory_is_never_overwritten(tmp_path, cache):
    base = tmp_path / "archive" / "humanmine-public-lists"
    (base / TODAY).mkdir(parents=True)
    (base / TODAY / "keep.txt").write_text("earlier archive")
    svc = FakeService(cache)
    r = go(tmp_path, cache, svc)
    assert r["archive"]["path"].endswith(TODAY + "-2")
    assert (base / TODAY / "keep.txt").read_text() == "earlier archive"
    assert os.listdir(base / TODAY) == ["keep.txt"]
    r = go(tmp_path, cache, svc)
    assert r["archive"]["path"].endswith(TODAY + "-3")
    assert archive_dirs(tmp_path) == [TODAY, TODAY + "-2", TODAY + "-3"]


def test_a_mine_without_public_lists_gets_an_empty_dated_record_and_the_run_goes_on(tmp_path, cache):
    svc = FakeService(cache)
    r = go(tmp_path, cache, svc)
    d = tmp_path / "archive" / "humanmine-public-lists" / TODAY
    assert json.loads((d / "lists.json").read_text()) == {"lists": []}
    assert json.loads((d / "archive.json").read_text())["lists"] == 0
    assert r["archive"]["lists"] == 0 and len(svc.names("upload")) == 5


def test_the_second_run_archives_the_lists_the_first_run_made(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    go(tmp_path, cache, svc)
    second = tmp_path / "archive" / "humanmine-public-lists" / (TODAY + "-2")
    names = {l["name"] for l in json.loads((second / "lists.json").read_text())["lists"]}
    assert RENAMED in names and PREFIX + "Hereditary_spastic_paraplegia" in names and len(names) == 5


def test_the_archive_label_is_the_last_part_of_the_mine_url_or_the_option(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc, "--mine-label", "ut-demo")
    assert os.listdir(tmp_path / "archive") == ["ut-demo-public-lists"]


def test_the_export_script_is_imported_and_told_not_to_pause_for_a_local_mine(tmp_path, monkeypatch):
    trace = tmp_path / "trace.json"
    monkeypatch.setenv("EXPORT_TRACE", str(trace))
    script = tmp_path / "scripts" / A.EXPORT_SCRIPT_NAME
    script.parent.mkdir()
    script.write_text("import json, os\nPAUSE = 0.3\nlog_lines = ['old']\nrefusals = 4\n"
                      "def main(base, out):\n    open(os.environ['EXPORT_TRACE'], 'w').write("
                      "json.dumps([base, out, PAUSE, log_lines, refusals]))\n")
    A.load_exporter(str(script))(MINE + "/service", "/some/dir")
    assert json.loads(trace.read_text()) == [MINE + "/service", "/some/dir", 0, [], 0]
    A.load_exporter(str(script))("https://mine.example.org/m/service", "/d")
    assert json.loads(trace.read_text())[2] == 0.3                 # a public server keeps the script's courtesy pause
    with pytest.raises(A.ArchiveError, match="does not exist"):
        A.load_exporter(str(tmp_path / "nothing.py"))


def test_the_real_t2_1_script_is_what_gets_imported_when_it_is_there():
    script = "/Users/gos/claude_projects/update_intermine_planning/repos/historic_artefacts/scripts/" + A.EXPORT_SCRIPT_NAME
    if not os.path.exists(script):
        pytest.skip("the historic_artefacts checkout is not here")
    assert callable(A.load_exporter(script))


# ---------------------------------------------------------------------------------------------- what is uploaded

def test_panels_are_uploaded_with_both_tags_and_resolved_entrez_ids(tmp_path, cache):
    svc = FakeService(cache)
    r = go(tmp_path, cache, svc)
    assert sorted(svc.names("upload")) == sorted(svc.store)
    assert len(svc.store) == 5
    l = svc.store[PREFIX + "Hereditary_spastic_paraplegia"]
    assert l["tags"] == ["Genomics England gene panel", "im:public"] and l["type"] == "Gene" and l["size"] == 3
    assert "Panel 165, version" in l["description"]
    assert {u["name"]: u["size"] for u in r["uploaded"]}[PREFIX + "Hereditary_spastic_paraplegia"] == 3
    assert r["verification"]["ok"] == 5 and not r["failures"]


def test_the_ids_uploaded_are_the_mines_own_identifiers_not_symbols(tmp_path, cache):
    svc = FakeService(cache)
    seen = {}
    real = svc.upload
    svc.upload = lambda name, type_, d, tags, ids, extra=A.ORGANISM: (seen.setdefault(name, ids), real(name, type_, d, tags, ids))[1]
    go(tmp_path, cache, svc)
    ids = seen[PREFIX + "Hereditary_spastic_paraplegia"]
    assert ids and all(i.isdigit() and 5001 <= int(i) < 6000 for i in ids), ids


def test_the_chain_falls_back_from_hgnc_to_ensembl_to_symbol(tmp_path, cache):
    svc = FakeService(cache)
    for k, v in list(svc.table.items()):               # HGNC ids unknown to the mine: Ensembl or symbol must do
        if v[0] == "hgnc_id":
            del svc.table[k]
    r = go(tmp_path, cache, svc)
    assert not r["failures"] and len(svc.store) == 5
    assert svc.store[PREFIX + "Hereditary_spastic_paraplegia"]["size"] == 3


def test_a_gene_the_mine_does_not_know_is_reported_and_left_out(tmp_path, cache):
    svc = FakeService(cache, unplaced={"HGNC:61"})      # ABCD1, in panel 165
    r = go(tmp_path, cache, svc)
    u = {x["name"]: x for x in r["uploaded"]}[PREFIX + "Hereditary_spastic_paraplegia"]
    assert u["size"] == 2 and u["members_in"] == 3 and u["unresolved"] == ["ABCD1"] and u["unresolved_count"] == 1


def test_a_panel_without_a_green_gene_is_skipped_and_reported(tmp_path, cache_with_empty_panel):
    svc = FakeService(cache_with_empty_panel)
    r = go(tmp_path, cache_with_empty_panel, svc)
    assert EMPTY_PANEL not in svc.store and EMPTY_PANEL not in svc.names("upload")
    assert [s for s in r["skipped"] if s["name"] == EMPTY_PANEL][0]["reason"].startswith("the panel has no Green gene")
    assert len(svc.store) == 4


def test_a_panel_none_of_whose_genes_resolve_is_skipped(tmp_path, cache):
    svc = FakeService(cache, unplaced={"HGNC:464", "HGNC:465"})   # all of panel 9
    r = go(tmp_path, cache, svc)
    assert RENAMED not in svc.store
    assert "none of the panel's genes resolves" in [s for s in r["skipped"] if s["name"] == RENAMED][0]["reason"]


def test_the_renamed_panels_keep_their_2021_names_by_default_and_say_so_in_the_description(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    assert RENAMED in svc.store and RENAMED_NOW not in svc.store
    assert 'PanelApp now names this panel "Differences in sex development"' in svc.store[RENAMED]["description"]
    assert "now names" not in svc.store[PREFIX + "Hereditary_spastic_paraplegia"]["description"]


def test_the_switch_names_every_list_after_the_current_panel_and_retires_the_2021_name(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    r = go(tmp_path, cache, svc, "--current-names")
    assert RENAMED_NOW in svc.store and RENAMED not in svc.store
    assert r["removed"] == [RENAMED] and r["keep_2021_names"] is False
    assert "now names" not in svc.store[RENAMED_NOW]["description"]
    r = go(tmp_path, cache, svc, "--keep-2021-names")
    assert RENAMED in svc.store and RENAMED_NOW not in svc.store and r["removed"] == [RENAMED_NOW]


def test_the_default_of_the_switch_is_one_variable(monkeypatch, tmp_path, cache):
    assert A.KEEP_2021_NAMES_DEFAULT is True and args_for(tmp_path, cache).keep_2021_names is True
    assert args_for(tmp_path, cache, "--current-names").keep_2021_names is False


def test_select_100k_uploads_only_the_2021_scope_and_removes_the_rest(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    r = go(tmp_path, cache, svc, "--select", "100k")
    # panels 9, 91, 165 and 263 are rare-disease-100k; 59 is a cancer panel
    assert sorted(svc.store) == sorted([RENAMED, PREFIX + "Erythropoietic_protoporphyria,_mild_variant",
                                        PREFIX + "Hereditary_spastic_paraplegia",
                                        PREFIX + "Amyotrophic_lateral_sclerosis_motor_neuron_disease"])
    assert r["removed"] == [EMPTY_PANEL]


def test_the_slash_in_a_panel_name_does_not_reach_the_list_name(tmp_path, cache):
    svc = FakeService(cache)
    go(tmp_path, cache, svc)
    assert not [n for n in svc.store if "/" in n]


# ---------------------------------------------------------------------------------------------- re-runs and stale lists

def test_a_second_run_replaces_the_lists_and_adds_no_duplicate(tmp_path, cache, legacy):
    svc = FakeService(cache)
    go(tmp_path, cache, svc, legacy_dir=legacy)
    before = {n: dict(l) for n, l in svc.store.items()}
    r = go(tmp_path, cache, svc, legacy_dir=legacy)
    assert svc.store == before and len(svc.store) == 5 + 2
    names = svc.names("upload")
    assert len(names) == 2 * len(set(names)) and not r["failures"] and r["removed"] == []
    assert archive_dirs(tmp_path) == [TODAY, TODAY + "-2"]


def test_a_retired_panel_list_is_removed_and_reported(tmp_path, cache):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Retired_panel")
    r = go(tmp_path, cache, svc)
    assert PREFIX + "Retired_panel" not in svc.store
    assert r["removed"] == [PREFIX + "Retired_panel"]


def test_lists_that_are_not_public_panel_lists_are_never_touched(tmp_path, cache):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Private_one", tags=[GE[0]])                    # not public
    svc.seed("PL_Not_a_panel", tags=["im:public"])                    # no Genomics England tag
    svc.seed("Mine_Genomics_list", tags=GE)                           # no PL_ prefix
    svc.seed(PREFIX + "Old", tags=GE)                                 # public, tagged, PL_: the one that goes
    r = go(tmp_path, cache, svc)
    assert {"PL_Not_a_panel", "Mine_Genomics_list", PREFIX + "Private_one"} <= set(svc.store)
    assert r["removed"] == [PREFIX + "Old"]
    assert "PL_Not_a_panel" not in svc.names("delete")


def test_a_failed_removal_is_a_failure_not_a_crash(tmp_path, cache):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Old")

    def refuse(name):
        raise A.ApplyError(f"delete of {name}: HTTP 403")
    svc.delete = refuse
    r = go(tmp_path, cache, svc)
    assert r["removal_failed"] and r["failures"]


# ---------------------------------------------------------------------------------------------- the legacy lists

def test_a_legacy_list_keeps_its_name_description_and_tags(tmp_path, cache, legacy):
    svc = FakeService(cache)
    go(tmp_path, cache, svc, legacy_dir=legacy)
    l = svc.store["PL_Legacy_whole"]
    assert (l["type"], l["description"], l["tags"], l["size"]) == ("Gene", "All of them.", ["im:public"], 2)
    assert svc.store["PL_Legacy_genes"]["tags"] == ["im:favourite", "im:public"]


def test_a_partly_resolving_legacy_list_gets_a_note_in_its_description(tmp_path, cache, legacy):
    svc = FakeService(cache)
    r = go(tmp_path, cache, svc, legacy_dir=legacy)
    l = svc.store["PL_Legacy_genes"]
    assert l["size"] == 3
    assert l["description"] == ("Some genes. [Note: this mine holds 3 of the 4 members of the original HumanMine list.]")
    u = {x["name"]: x for x in r["uploaded"]}["PL_Legacy_genes"]
    assert u["unresolved"] == ["999"] and u["members_in"] == 4


def test_a_legacy_list_with_no_member_in_the_mine_or_no_class_is_skipped_and_reported(tmp_path, cache, legacy):
    svc = FakeService(cache)
    r = go(tmp_path, cache, svc, legacy_dir=legacy)
    skipped = {s["name"]: s["reason"] for s in r["skipped"]}
    assert "none of its 2 members is in this mine" in skipped["PL_Legacy_proteins"]
    assert "type SNP is not in this mine's model" in skipped["PL_Legacy_snps"]
    assert "PL_Legacy_proteins" not in svc.store and "PL_Legacy_snps" not in svc.store


def test_a_synonym_match_does_not_count_as_a_legacy_member(tmp_path, cache, legacy):
    svc = FakeService(cache)
    real = svc.resolve

    def resolve(type_, values):
        out = real(type_, values)
        if type_ == "Gene" and "101" in values:
            out["101"]["categories"] = ["OTHER"]          # the upload would not add it, so it is not counted
        return out
    svc.resolve = resolve
    go(tmp_path, cache, svc, legacy_dir=legacy)
    assert svc.store["PL_Legacy_whole"]["size"] == 1


def test_the_13_curated_legacy_lists_load_as_archived():
    defs = A.legacy_definitions(os.path.join(ROOT, "curation", "public_lists"))
    assert len(defs) == 13
    by = {d["name"]: d for d in defs}
    assert by["PL_Pax6_Targets"]["type"] == "Gene" and len(by["PL_Pax6_Targets"]["members"]) == 319
    assert by["PL_Protein coding cancer genes containing probable driver mutations"]["tags"] == ["im:favourite", "im:public"]
    assert sorted(d["type"] for d in defs).count("Protein") == 2 and by["PL_T2DcandSNPs_Voight2010"]["type"] == "SNP"
    assert all(A.PUBLIC_TAG in d["tags"] and len(d["members"]) == d["original_size"] for d in defs)
    assert by["PL_BHF_UCL_cardiovascGenes"]["members"][0].isdigit()


# ---------------------------------------------------------------------------------------------- dry run, report, exit code

def test_dry_run_archives_and_writes_nothing(tmp_path, cache, legacy):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Old")
    r = go(tmp_path, cache, svc, "--dry-run", legacy_dir=legacy)
    assert not [c for c in svc.calls if c[0] in ("login", "upload", "delete", "export")], svc.calls
    assert archive_dirs(tmp_path) == [] and list(svc.store) == [PREFIX + "Old"]
    assert len(r["uploaded"]) == 7 and r["would_remove"] == [PREFIX + "Old"] and r["archive"]["lists"] == 1


def test_the_run_report_is_written_and_says_what_happened(tmp_path, cache, legacy):
    svc = FakeService(cache)
    svc.seed(PREFIX + "Old")
    rep = tmp_path / "report.json"
    code = A.main(["--mine", MINE, "--panelapp-cache", cache, "--archive-repo", str(tmp_path / "archive"),
                   "--legacy", legacy, "--report", str(rep)], service=svc, exporter=make_exporter(svc))
    assert code == 0
    r = json.loads(rep.read_text())
    assert r["mine"] == MINE and r["select"] == "all" and r["keep_2021_names"] is True and r["dry_run"] is False
    assert r["archive"]["path"].startswith(str(tmp_path / "archive" / "humanmine-public-lists")) and r["archive"]["lists"] == 1
    assert len(r["uploaded"]) == 7 and r["removed"] == [PREFIX + "Old"]
    assert {s["name"] for s in r["skipped"]} == {"PL_Legacy_proteins", "PL_Legacy_snps"}
    assert r["verification"]["ok"] == 7 and r["verification"]["problems"] == [] and r["failures"] == []
    assert {"name", "kind", "type", "size", "members_in", "unresolved_count", "unresolved", "tags"} <= set(r["uploaded"][0])


def test_a_list_that_reads_back_wrong_makes_the_exit_code_one(tmp_path, cache):
    svc = FakeService(cache)
    real = svc.lists

    def lists(token=None):
        out = real(token)
        for l in out:
            if l["name"] == RENAMED:
                l["size"] = 1
        return out
    svc.lists = lists
    code = A.main(["--mine", MINE, "--panelapp-cache", cache, "--archive-repo", str(tmp_path / "archive")],
                  service=svc, exporter=make_exporter(svc))
    assert code == 1


def test_an_archive_failure_is_exit_code_one_and_nothing_was_written(tmp_path, cache):
    svc = FakeService(cache)
    code = A.main(["--mine", MINE, "--panelapp-cache", cache, "--archive-repo", str(tmp_path / "archive")],
                  service=svc, exporter=make_exporter(svc, fail=RuntimeError("boom")))
    assert code == 1 and not svc.store and not svc.names("upload")


# ---------------------------------------------------------------------------------------------- the production guard

@pytest.mark.parametrize("url", [
    "https://www.humanmine.org/humanmine", "http://humanmine.org/humanmine", "http://www.flymine.org/flymine",
    "https://bluegenes.example.com/humanmine", "http://93.184.216.34/humanmine", "https://beta.intermine.org/m"])
def test_a_public_host_is_refused(url, tmp_path, cache):
    svc = FakeService(cache)
    code = A.main(["--mine", url, "--panelapp-cache", cache, "--archive-repo", str(tmp_path / "archive")], service=svc,
                  exporter=make_exporter(svc))
    assert code == 1 and svc.calls == [] and archive_dirs(tmp_path) == []
    with pytest.raises(A.GuardError, match="i-know-this-is-production"):
        A.guard_mine(url)


@pytest.mark.parametrize("url", [
    "http://localhost:18090/humanmine", "http://127.0.0.1:8080/humanmine", "http://10.1.2.3/humanmine",
    "http://192.168.0.5:8080/humanmine", "http://host.docker.internal:18090/humanmine", "http://mine:8080/humanmine",
    "http://[::1]:8080/humanmine", "http://ut.localhost/humanmine"])
def test_a_local_or_private_host_is_allowed(url):
    assert A.guard_mine(url) == url


def test_the_production_switch_lets_a_public_host_through():
    assert A.guard_mine("https://www.humanmine.org/humanmine/", True) == "https://www.humanmine.org/humanmine"


def test_a_url_that_is_not_http_is_refused():
    for url in ("ftp://localhost/x", "localhost:8080/humanmine", ""):
        with pytest.raises(A.GuardError):
            A.guard_mine(url)


# ---------------------------------------------------------------------------------------------- the web service calls

class Recorder:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, method, url, data=None, headers=None, timeout=60):
        self.calls.append((method, url, data, headers or {}))
        return self.replies.pop(0)


def test_upload_is_a_text_plain_post_with_the_documented_parameters():
    rec = Recorder([(200, json.dumps({"wasSuccessful": True, "listSize": 3, "unmatchedIdentifiers": []}))])
    ws = A.WebService(MINE + "/", "u", "p", http=rec)
    ws._token = "T0K"
    res = ws.upload("PL_x:Name (a), b/c", "Gene", "desc; with\nnewline", ["Genomics England gene panel", "im:public"],
                    ["10", "20", "30"])
    method, url, body, headers = rec.calls[0]
    assert method == "POST" and url.startswith(MINE + "/service/lists?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q == {"name": ["PL_x:Name (a), b/c"], "type": ["Gene"], "description": ["desc; with\nnewline"],
                 "tags": ["Genomics England gene panel;im:public"], "extraValue": ["H. sapiens"],
                 "replaceExisting": ["true"]}
    assert body == "10\n20\n30\n" and headers["Authorization"] == "Token T0K"
    assert headers["Content-Type"].startswith("text/plain") and res == {"size": 3, "unmatched": []}


def test_upload_errors_are_raised_with_the_mines_message():
    rec = Recorder([(400, json.dumps({"wasSuccessful": False, "error": "Attempt to overwrite an existing bag"}))])
    ws = A.WebService(MINE, "u", "p", http=rec)
    with pytest.raises(A.ApplyError, match="HTTP 400"):
        ws.upload("n", "Gene", "", ["im:public"], ["1"])


def test_delete_and_lists_use_the_token_only_when_there_is_one():
    rec = Recorder([(200, "{}"), (200, json.dumps({"lists": [{"name": "a"}]})), (200, json.dumps({"lists": []}))])
    ws = A.WebService(MINE, "u", "p", http=rec)
    ws._token = "T"
    ws.delete("PL_x:y z")
    assert rec.calls[0][0] == "DELETE" and rec.calls[0][1] == MINE + "/service/lists?name=PL_x%3Ay+z"
    assert rec.calls[0][3]["Authorization"] == "Token T"
    assert ws.lists() == [{"name": "a"}] and "Authorization" not in rec.calls[1][3]
    ws.lists("T")
    assert rec.calls[2][3]["Authorization"] == "Token T" and rec.calls[2][1].endswith("/service/lists?format=json")


def test_the_cache_group_directory_is_found_with_or_without_data(tmp_path, cache):
    assert A.locate_panelapp(cache) == cache
    group = tmp_path / "group"
    group.mkdir()
    os.symlink(cache, group / "data")
    assert A.locate_panelapp(str(group)) == str(group / "data")
    with pytest.raises(A.ApplyError, match="no META.json"):
        A.locate_panelapp(str(tmp_path / "nothing"))
