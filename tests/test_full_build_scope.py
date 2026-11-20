"""tools/full-build.sh --scope full (the plan's `--genes all`, im-9n4.26, T3.2), through --dry-run.

A full-scope build has no gene panel anywhere: every RDF source is fetched for the whole taxon with no
limit, the stock files are used whole (no id sets, no filter), the ID resolver holds the whole taxon,
and every cache group it writes records scope=full, so a panel cache can never be restored into it,
nor a full one into a panel build. Like the other dry-run tests these skip where check_prereqs cannot
pass (no docker compose or JDK 8).
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from rdfc2im import rawcache, stock  # noqa: E402

STOCK = "uniprot uniprot-fasta go-annotation panther mgi-identifiers psi-intact biogrid ncbi-gff hpo-annotation gtex"
RDF = "go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed hpo"
PANEL_STEPS = ("subset_raw.py filter", "subset_raw.py idsets", "subset_raw.py panel-items",
               "subset_raw.py partner-ids", "subset_raw.py disease-ids", "--genes")


def _fake_intermine_60(tmp_path):
    src = tmp_path / "intermine-src"
    for rel, text in {
        "config/lib/install_intermine.py": 'DEFAULT_GRADLE_VERSION = "8.14.6"\n'
                                           '    "gradle-8.14.6-bin.zip":\n        "%s",\n' % ("0" * 64),
        "gradle/libs.versions.toml": '[versions]\nintermine = "6.0.0"\n',
        "plugin/build.gradle": "version = '6.0.0'\n",
        "intermine/libs/antlr-2.7.6-caching.jar": "",
        "intermine/resources/src/main/resources/default.intermine.production.properties": "",
        "bio/sources/reactome/reactome.properties": "",
    }.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return str(src)


def _run(tmp_path, *args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RDFC2IM_STOCK_FILTERED_CACHE", "RDFC2IM_STOCK_LOCAL")}
    env.update(TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test", LOG_DIR=str(tmp_path / "logs"),
               RDFC2IM_STOCK_DIR=str(tmp_path / "stock"), PG_PORT="39201", SOLR_PORT="39202", MINE_PORT="39203",
               BG_PORT="39204", **(env_extra or {}))
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _plan(tmp_path, *args, env_extra=None):
    rc, out = _run(tmp_path, *args, env_extra=env_extra)
    if rc != 0 and "[check_prereqs] FATAL" in out and "stock" not in out.split("FATAL", 1)[1][:200]:
        return None
    assert rc == 0, out
    return out


def _cmds(plan, phase=None):
    pat = r"\[(%s)\] \+ (.*)$" % (re.escape(phase) if phase else r"[a-z0-9_]+")
    return [m.group(2) for line in plan.splitlines() if (m := re.search(pat, line))]


def _meta(cmd):
    return dict(m.split("=", 1) for m in re.findall(r"--meta (\S+)", cmd))


def _full(tmp_path, *more):
    return ("--sources", RDF, "--intermine-src", _fake_intermine_60(tmp_path), "--stock-sources", STOCK, *more)


DATA_PHASES = ("rdfc2im_pipeline", "fetch_stock_data", "subset_stock_data", "stage_src_data")


def _data_plan(tmp_path, *args):
    """The data phases' dry runs, one --only each (the stand-in checkout cannot pass publish_intermine), joined."""
    plans = [_plan(tmp_path, "--only", p, *args) for p in DATA_PHASES]
    return None if None in plans else "\n".join(plans)


def test_scope_full_dry_run_has_no_subset_or_filter_step_and_no_limit(tmp_path):
    plan = _data_plan(tmp_path, *_full(tmp_path, "--scope", "full"))
    if plan is None:
        return
    cmds = _cmds(plan)
    for step in PANEL_STEPS:
        assert not [c for c in cmds if step in c], (step, [c for c in cmds if step in c])
    fetches = [c for c in cmds if "rdfc2im fetch --source" in c]
    assert len(fetches) == len(RDF.split()), fetches
    for c in fetches:
        assert "--limit 0" in c, c
    for src in ("ncbigene", "hgnc", "ensembl", "uniprot", "clinvar", "gwascatalog"):
        t = next(c for c in cmds if f"rdfc2im translate --source {src}" in c)
        assert t.endswith("--taxon 9606"), t
    assert "scope: full" in plan
    # the stock files are used whole: unpacked or decompressed, or staged as they are
    sub = _cmds(plan, "subset_stock_data")
    assert any("unzip" in c and "human.zip" in c for c in sub), sub
    assert any("gzip -dc" in c and "goa_human.gaf.gz" in c for c in sub), sub
    assert not any("cache save stock-" in c for c in sub), [c for c in sub if "cache save" in c]


def test_scope_full_records_scope_full_in_every_cache_group_it_writes(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", *_full(tmp_path, "--scope", "full"))
    if plan is None:
        return
    saves = [c for c in _cmds(plan, "rdfc2im_pipeline") if "rdfc2im cache save" in c]
    assert len(saves) == len(RDF.split()), saves      # no gene-id-lookup group: nothing is resolved by symbol
    for c in saves:
        m = _meta(c)
        assert m.get("scope") == "full" and "genes_md5" not in m and m.get("limit") == "0", c


def test_scope_full_restores_only_full_groups(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", *_full(tmp_path, "--scope", "full", "--use-cached-data"))
    if plan is None:
        return
    restores = [c for c in _cmds(plan, "rdfc2im_pipeline") if "rdfc2im cache restore" in c]
    assert len(restores) == len(RDF.split()), restores      # and no gene-id-lookup group
    assert all(_meta(c).get("scope") == "full" for c in restores), restores


def test_a_panel_group_is_refused_by_a_full_build_and_a_full_group_by_a_panel_build(tmp_path):
    data = tmp_path / "raw"
    data.mkdir()
    (data / "main.tsv").write_text("a\n1\n")
    cache = str(tmp_path / "cache")
    rawcache.save("go", str(data), cache, {"scope": "none", "taxon": "9606", "limit": "0"})
    rawcache.save("clinvar", str(data), cache, {"scope": "full", "taxon": "9606", "limit": "0"})
    for group, want in (("go", "full"), ("clinvar", "panel")):
        try:
            rawcache.restore(group, str(tmp_path / ("out-" + group)), cache, {"scope": want, "taxon": "9606"})
        except rawcache.CacheError as e:
            assert "refusing" in str(e)
        else:
            raise AssertionError(f"{group} restored for scope={want}")


def test_genes_all_is_the_plans_name_for_scope_full(tmp_path):
    a = _data_plan(tmp_path, *_full(tmp_path, "--scope", "full"))
    b = _data_plan(tmp_path, *_full(tmp_path, "--genes", "all"))
    if a is None or b is None:
        return
    assert _cmds(a) == _cmds(b)


def test_scope_full_refuses_the_panel_options(tmp_path):
    for extra, msg in ((("--gene-identifiers", "panel"), "--scope full"),
                       (("--resolver-scope", "panel"), "--scope full"),
                       (("--genes", os.path.join(ROOT, "curation", "demo_gene_panel.txt")), "--scope full")):
        rc, out = _run(tmp_path, "--scope", "full", *extra)
        assert rc == 2 and msg in out, (extra, out)
    rc, out = _run(tmp_path, "--scope", "some")
    assert rc == 2 and "--scope wants panel or full" in out, out


def test_scope_full_needs_no_gene_panel_file(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go hgnc pubmed", "--scope", "full",
                 env_extra={"GENE_PANEL": str(tmp_path / "no-such-panel.txt")})
    if plan is None:
        return
    cmds = _cmds(plan)
    assert not any("panel-items" in c for c in cmds)
    cite = next(c for c in cmds if "cited_pmids.txt" in c and "out/" in c)
    assert "hgnc" in cite and "hgnc-panel-items" not in cite, cite


def test_scope_full_takes_every_human_gene_in_the_resolver(tmp_path):
    plan = _plan(tmp_path, "--only", "subset_stock_data", *_full(tmp_path, "--scope", "full"))
    if plan is None:
        return
    sub = _cmds(plan, "subset_stock_data")
    entrez = [c for c in sub if "resolver/entrez" in c]
    assert entrez and all("gzip -dc" in c and "--ids" not in c for c in entrez), entrez


def test_stock_file_rows_in_full_scope_use_every_panel_cut_file_whole(tmp_path):
    table = stock.load_table()
    names = sorted(table)
    panel = [r.split("\t") for r in stock.file_rows(table, names, "/S", "/R")]
    full = [r.split("\t") for r in stock.file_rows(table, names, "/S", "/R", full=True)]
    assert len(panel) == len(full)
    for p, f in zip(panel, full):
        assert p[:2] == f[:2]
        if p[13] == "filtered" and p[8] in stock.PANEL_ID_SETS:
            assert f[13] in ("whole", "asis") and f[8] == "-", f
            assert f[13] == "asis" or f[12].startswith("/S/whole/"), f
        elif p[13] == "derived":     # ncbi-gff's chromosome lengths, read from the whole GFF
            assert f[13] == "derived" and f[4].startswith("/S/whole/") and f[12] == p[12], f
        else:
            assert f == p, (p, f)
    assert any(p[13] == "filtered" and p[8] == "chromosomes" for p in full)   # the assembly cut is not a panel cut


def test_reduce_mine_leaves_the_files_alone_when_every_source_is_present(tmp_path):
    px = tmp_path / "project.xml"
    px.write_text('<project type="bio">\n  <sources>\n    <source name="a" type="humanmine-items"/>\n'
                  '    <source name="uniprot" type="uniprot"/>\n  </sources>\n</project>\n')
    before = px.read_bytes()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "reduce_mine.py"), "sources", str(px),
                        "humanmine-items", "uniprot"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert px.read_bytes() == before and "nothing to trim" in r.stdout, r.stdout
    model = tmp_path / "genomic_model.xml"
    model.write_text('<model name="genomic" package="org.intermine.model.bio">'
                     '<class name="Gene" is-interface="true"><attribute name="symbol" type="java.lang.String"/></class>'
                     '</model>')
    pr = tmp_path / "genomic_priorities.properties"
    pr.write_text("# a comment\nGene.symbol = a, *\n")
    before = pr.read_bytes()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "reduce_mine.py"), "priorities", str(pr),
                        str(model)], capture_output=True, text=True)
    assert r.returncode == 0 and pr.read_bytes() == before and "nothing to trim" in r.stdout, r.stdout
