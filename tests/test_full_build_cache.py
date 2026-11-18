"""tools/full-build.sh --use-cached-data / --cache-dir, checked through --dry-run.

--dry-run is a real dry run of the exact command sequence (run/run_in/write_file are the only
things that touch the outside world, and all are no-op printers under it), so these tests read
the plan the script would execute. They skip on a machine without the tools check_prereqs needs
(docker compose, a JDK 8): that phase always runs first, even under --only.
"""
import hashlib
import os
import re
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, "curation", "demo_gene_panel.txt")


def _plan(tmp_path, *args):
    """Returns the dry-run log, or None if this machine can't pass check_prereqs."""
    if not shutil.which("bash"):
        return None
    env = dict(os.environ, TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test",
               LOG_DIR=str(tmp_path / "logs"))
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    if r.returncode != 0 and "[check_prereqs] FATAL" in out:
        return None
    assert r.returncode == 0, out
    return out


def _cmds(plan):
    """The `+ ...` command lines the script would run, without timestamp/phase decoration."""
    return [m.group(1) for line in plan.splitlines() if (m := re.search(r"\] \+ (.*)$", line))]


def _meta(cmd):
    return sorted(re.findall(r"--meta (\S+)", cmd))


def test_default_build_fetches_then_saves_to_the_cache(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go hgnc")
    if plan is None:
        return
    cmds = _cmds(plan)
    for src in ("go", "hgnc"):
        fetch = next(i for i, c in enumerate(cmds) if f"rdfc2im fetch --source {src} " in c)
        save = next(i for i, c in enumerate(cmds) if f"rdfc2im cache save {src} out/{src}/raw" in c)
        tsv = next(i for i, c in enumerate(cmds) if f"rdfc2im tsv --source {src}" in c)
        assert fetch < save < tsv, "cache only what was fetched, and before it is transformed"
    assert not any("cache restore" in c for c in cmds)


def test_use_cached_data_restores_and_never_fetches(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go hgnc", "--use-cached-data")
    if plan is None:
        return
    cmds = _cmds(plan)
    for src in ("go", "hgnc"):
        restore = next(i for i, c in enumerate(cmds) if f"rdfc2im cache restore {src} out/{src}/raw" in c)
        tsv = next(i for i, c in enumerate(cmds) if f"rdfc2im tsv --source {src}" in c)
        assert restore < tsv
    assert not any(" fetch " in c or "cache save" in c for c in cmds), cmds


def test_gene_symbol_lookups_are_cached_and_restored_before_translate(tmp_path):
    fetched = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go ncbigene")
    restored = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go ncbigene", "--use-cached-data")
    if fetched is None:
        return
    f, r = _cmds(fetched), _cmds(restored)
    last_tsv = max(i for i, c in enumerate(f) if "rdfc2im tsv" in c)
    save = next(i for i, c in enumerate(f) if "cache save gene-id-lookup" in c)
    assert save > last_tsv and not any("cache restore gene-id-lookup" in c for c in f)
    restore = next(i for i, c in enumerate(r) if "cache restore gene-id-lookup" in c)
    assert restore < next(i for i, c in enumerate(r) if "rdfc2im translate" in c)
    assert not any("cache save gene-id-lookup" in c for c in r)
    md5 = hashlib.md5(open(PANEL, "rb").read()).hexdigest()
    assert _meta(next(c for c in f if "cache save gene-id-lookup" in c)) == \
        _meta(next(c for c in r if "cache restore gene-id-lookup" in c)) == sorted(["taxon=9606", f"genes_md5={md5}"])


def test_no_lookup_cache_when_no_source_resolves_symbols(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go uniprot", "--use-cached-data")
    if plan is None:
        return
    assert not any("gene-id-lookup" in c for c in _cmds(plan))


def test_live_model_is_cached_and_restored(tmp_path):
    fetched = _plan(tmp_path, "--only", "fetch_inputs")
    restored = _plan(tmp_path, "--only", "fetch_inputs", "--use-cached-data")
    if fetched is None:
        return
    f, r = _cmds(fetched), _cmds(restored)
    assert any("sh tools/make-inputs.sh" in c and "OFFLINE" not in c for c in f)
    assert any("cache save humanmine-model" in c for c in f)
    assert not any("cache restore" in c for c in f)
    assert any("cache restore humanmine-model" in c for c in r)
    mi = [c for c in r if "sh tools/make-inputs.sh" in c]
    assert mi and all("CACHED=1" in c and "OFFLINE" not in c for c in mi), "cached is not offline"
    assert not any(c for c in mi if "OFFLINE=1" in c)
    assert not any("cache save" in c for c in r)


def test_saved_and_required_scope_are_identical_for_every_source(tmp_path):
    """A restore that demanded different --meta than save recorded would refuse every time (or,
    worse, check nothing). Both modes must derive them from the same function."""
    srcs = "go ncbigene reactome"
    saved = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", srcs)
    restored = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", srcs, "--use-cached-data")
    if saved is None:
        return
    for src in srcs.split():
        s = next(c for c in _cmds(saved) if f"cache save {src} " in c)
        r = next(c for c in _cmds(restored) if f"cache restore {src} " in c)
        assert _meta(s) == _meta(r) and _meta(s), (s, r)


def test_panel_scoped_sources_are_keyed_to_the_gene_panel_checksum(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "ncbigene go", "--use-cached-data")
    if plan is None:
        return
    md5 = hashlib.md5(open(PANEL, "rb").read()).hexdigest()
    cmds = _cmds(plan)
    assert f"--meta genes_md5={md5}" in next(c for c in cmds if "cache restore ncbigene" in c)
    assert "genes_md5" not in next(c for c in cmds if "cache restore go " in c), "unscoped source"


def test_a_different_panel_gives_a_different_cache_key(tmp_path):
    other = tmp_path / "panel.txt"
    other.write_text("CYP2D6 CYP3A4\n")
    a = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "ncbigene", "--use-cached-data")
    b = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "ncbigene", "--use-cached-data",
              "--genes", str(other))
    if a is None:
        return
    ka = _meta(next(c for c in _cmds(a) if "cache restore ncbigene" in c))
    kb = _meta(next(c for c in _cmds(b) if "cache restore ncbigene" in c))
    assert ka != kb


def test_cache_dir_option_is_passed_through(tmp_path):
    plan = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go", "--use-cached-data",
                 "--cache-dir", "/somewhere/else")
    if plan is None:
        return
    assert "--cache-dir /somewhere/else" in next(c for c in _cmds(plan) if "cache restore go" in c)


def test_reactome_download_is_cached_and_restorable(tmp_path):
    fetched = _plan(tmp_path, "--only", "build_reactome_source")
    restored = _plan(tmp_path, "--only", "build_reactome_source", "--use-cached-data")
    if fetched is None:
        return
    f, r = _cmds(fetched), _cmds(restored)
    assert any("curl" in c and "UniProt2Reactome.txt" in c for c in f)
    assert any("cache save reactome-uniprot-map /micklem/data/reactome/current" in c for c in f)
    assert not any("curl" in c and "UniProt2Reactome" in c for c in r)
    assert any("cache restore reactome-uniprot-map /micklem/data/reactome/current" in c for c in r)


def test_logs_default_to_the_repository_so_a_host_can_watch_them(tmp_path):
    """A build in a sandbox logged under the sandbox's private $HOME, which a host terminal could not
    see ("no logfile at /home/agent/... for run fresh3"). The repository is the shared directory."""
    if not shutil.which("bash"):
        return
    env = {k: v for k, v in os.environ.items() if k != "LOG_DIR"}
    env.update(TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test-default-logdir")
    logs = os.path.join(ROOT, ".build-logs")
    mine = os.path.join(logs, "build-test-default-logdir")
    try:
        r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--only", "stage_src_data"], cwd=ROOT,
                           env=env, capture_output=True, text=True)
        if r.returncode != 0 and "[check_prereqs] FATAL" in r.stdout + r.stderr:
            return
        assert r.returncode == 0, r.stdout + r.stderr
        assert os.path.exists(mine + ".log") and os.path.exists(mine + ".status")
        assert not os.path.exists(tmp_path / "trial_home" / "logs")
        w = subprocess.run(["bash", "tools/watch-build.sh", "--run-id", "test-default-logdir", "--once"], cwd=ROOT,
                           env=env, capture_output=True, text=True)
        assert w.returncode == 0 and ".build-logs" in w.stdout, w.stdout + w.stderr
    finally:
        for ext in (".log", ".status", ".timing.tsv"):
            if os.path.exists(mine + ext):
                os.unlink(mine + ext)


def test_project_is_scoped_to_the_sources_being_built(tmp_path):
    """--sources scoped the fetch but not the mine: `project` was run with no source list, so any
    stale out/<dir>/columns.tsv from an earlier session leaked into project.xml (phase 11 then died
    loading humanmine-expressionatlas, which was never in the panel)."""
    plan = _plan(tmp_path, "--only", "rdfc2im_project", "--sources", "go hgnc")
    if plan is None:
        return
    cmd = next(c for c in _cmds(plan) if "rdfc2im project" in c)
    assert cmd.endswith("rdfc2im project --source go --source hgnc"), cmd


def test_build_dbmodel_discards_the_previous_generated_model_before_regenerating(tmp_path):
    """The fourth fresh-build failure repeated the third one: loading humanmine-uniprot died with
    "Collection not found in class: Protein.keywords" AFTER Protein.keywords had been added to the
    additions, the loader jar rebuilt, and the phase re-run. dbmodel/build/.../genomic_model.xml was
    stale: Gradle treats model generation as up to date when only the CONTENT of an already
    installed jar changed (same coordinates), so `builddb` succeeded in 9 seconds and regenerated
    nothing. Any resume (--from) or re-run in an existing checkout after the additions changed hits
    it - and it looks exactly like success. The generated output must be removed first."""
    plan = _plan(tmp_path, "--only", "build_dbmodel")
    if plan is None:
        return
    cmds = _cmds(plan)
    rm = next(i for i, c in enumerate(cmds) if c.startswith("rm -rf ") and c.endswith("/humanmine/dbmodel/build"))
    builddb = next(i for i, c in enumerate(cmds) if ":dbmodel:builddb" in c)
    assert rm < builddb


def test_build_webapp_gives_copywebappcontent_a_history_before_building_the_war(tmp_path):
    """Phase 13 failed on a from-scratch checkout and passed when simply run again:
        File '.../webapp/build/explodedWebApp/WEB-INF/web.xml' specified for property 'webXml' does
        not exist.
    unwarBioWebApp expands the bio-webapp war into explodedWebApp, and copyWebappContent - whose
    declared output is that same directory - runs after it. A task with no history has its existing
    outputs treated as stale and removed, so on the very first run Gradle deleted what the unwar had
    just produced (web.xml, struts-config, ... - 2739 files down to 5). On any later run the copy has
    a history and nothing is removed. Running copyWebappContent once first gives it one."""
    plan = _plan(tmp_path, "--only", "build_webapp")
    if plan is None:
        return
    gradle = [c for c in _cmds(plan) if "./gradlew" in c]
    prime = next(i for i, c in enumerate(gradle) if ":webapp:copyWebappContent" in c)
    war = next(i for i, c in enumerate(gradle) if ":webapp:war" in c)
    assert prime < war, gradle


# ------------------------------------------------------------------ --reactome-levels

def test_default_reactome_levels_fetches_the_lowest_level_file(tmp_path):
    plan = _plan(tmp_path, "--only", "build_reactome_source")
    if plan is None:
        return
    cmds = _cmds(plan)
    assert any("curl" in c and c.endswith("UniProt2Reactome.txt") for c in cmds), cmds
    assert not any("curl" in c and "All_Levels" in c for c in cmds), cmds
    assert any(c.startswith("rm -f ") and c.endswith("UniProt2Reactome_All_Levels.txt") for c in cmds), cmds
    assert any("cache save reactome-uniprot-map " in c and "levels=default" in c for c in cmds), cmds


def test_all_levels_option_fetches_the_all_levels_file_instead(tmp_path):
    plan = _plan(tmp_path, "--only", "build_reactome_source", "--reactome-levels", "all")
    if plan is None:
        return
    cmds = _cmds(plan)
    assert any("curl" in c and c.endswith("UniProt2Reactome_All_Levels.txt") for c in cmds), cmds
    assert not any("curl" in c and c.endswith(" UniProt2Reactome.txt") for c in cmds), cmds
    assert any(c.startswith("rm -f ") and c.endswith("/UniProt2Reactome.txt") for c in cmds), cmds
    assert any("cache save reactome-uniprot-map " in c and "levels=all" in c for c in cmds), cmds


def test_switching_levels_clears_the_other_levels_file_first(tmp_path):
    """The converter reads every file the fileset finds under src.data.dir - if a build
    previously fetched one level and is now asked for the other, both files must not coexist
    there, or Reactome's pathway/protein data would be double-counted."""
    plan = _plan(tmp_path, "--only", "build_reactome_source", "--reactome-levels", "all")
    if plan is None:
        return
    cmds = _cmds(plan)
    rm = next(i for i, c in enumerate(cmds) if c.startswith("rm -f ") and "UniProt2Reactome" in c)
    curl = next(i for i, c in enumerate(cmds) if "curl" in c)
    assert rm < curl, cmds


def test_use_cached_data_with_all_levels_restores_the_all_levels_group(tmp_path):
    plan = _plan(tmp_path, "--only", "build_reactome_source", "--use-cached-data", "--reactome-levels", "all")
    if plan is None:
        return
    cmds = _cmds(plan)
    assert any("cache restore reactome-uniprot-map " in c and "levels=all" in c for c in cmds), cmds
    assert not any("curl" in c for c in cmds), cmds


def test_reactome_levels_rejects_an_unknown_value(tmp_path):
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--reactome-levels", "bogus"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and "reactome-levels" in (r.stdout + r.stderr)


# --- --use-cached-data is not --offline [im-ore.17] ---------------------------------------------

def _make_inputs_cmds(plan):
    return [c for c in _cmds(plan) if "sh tools/make-inputs.sh" in c]


def test_use_cached_data_alone_lets_make_inputs_clone_and_does_not_set_offline(tmp_path):
    """The nightly runs --use-cached-data on a runner with no in/.upstream: the clones must be
    allowed (CACHED=1, not OFFLINE=1) and the pipeline must not export RDFC2IM_OFFLINE."""
    plan = _plan(tmp_path, "--only", "fetch_inputs", "--use-cached-data")
    if plan is None:
        return
    mi = _make_inputs_cmds(plan)
    assert mi and all("CACHED=1" in c and "OFFLINE" not in c for c in mi), mi
    assert "offline=0" in plan


def test_offline_implies_use_cached_data_and_forbids_clones(tmp_path):
    plan = _plan(tmp_path, "--only", "fetch_inputs", "--offline")
    if plan is None:
        return
    cmds = _cmds(plan)
    assert any("cache restore humanmine-model" in c for c in cmds)
    assert not any("cache save" in c for c in cmds)
    mi = _make_inputs_cmds(plan)
    assert mi and all("OFFLINE=1" in c and "CACHED=1" in c for c in mi), mi
    assert "offline=1" in plan


def test_offline_pipeline_restores_every_source_like_use_cached_data(tmp_path):
    a = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go ncbigene", "--use-cached-data")
    b = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", "go ncbigene", "--offline")
    if a is None:
        return
    assert _cmds(a) == _cmds(b), "--offline differs from --use-cached-data only in the guards"


def test_caller_exported_rdfc2im_offline_means_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("RDFC2IM_OFFLINE", "1")
    plan = _plan(tmp_path, "--only", "fetch_inputs")
    if plan is None:
        return
    assert "offline=1" in plan and "use_cached_data=1" in plan
    assert any("cache restore humanmine-model" in c for c in _cmds(plan))


def test_every_gradle_call_carries_the_gradle_user_home_and_user_home(tmp_path):
    """im-ore.4: JDK 8 ignores $HOME, so a private HOME was silently bypassed unless the caller had
    put -Duser.home into JAVA_TOOL_OPTIONS itself.  The script passes both, explicitly, to each call."""
    if not shutil.which("bash"):
        return
    home = str(tmp_path / "privhome")
    env = dict(os.environ, HOME=home, TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test",
               LOG_DIR=str(tmp_path / "logs"))
    for k in ("JAVA_TOOL_OPTIONS", "GRADLE_USER_HOME"):
        env.pop(k, None)
    plans = []
    for phase in ("build_humanmine_items", "build_dbmodel", "integrate_sources", "build_webapp"):
        r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--only", phase], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        if r.returncode != 0 and "[check_prereqs] FATAL" in out:
            return
        assert r.returncode == 0, out
        plans += _cmds(out)
    gradle = [c for c in plans if "./gradlew" in c or " gradle " in c]
    assert gradle, plans
    for c in gradle:
        assert f"GRADLE_USER_HOME={home}/.gradle" in c and f"JAVA_TOOL_OPTIONS=-Duser.home={home}" in c, c


def test_compose_data_dirs_come_from_the_environment(tmp_path):
    """im-ore.4: RDFC2IM_PGDATA / RDFC2IM_SOLRDATA turn the data volumes into bind mounts; unset they
    are ordinary named volumes, as before."""
    if not shutil.which("docker"):
        return
    base = ["docker", "compose", "-f", os.path.join(ROOT, "trial", "docker-compose.yml"), "config", "--format", "json"]
    def vols(**extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("RDFC2IM_")}
        r = subprocess.run(base, env=dict(env, **extra), capture_output=True, text=True)
        if r.returncode != 0:
            return None
        import json
        return json.loads(r.stdout)["volumes"]
    plain = vols()
    if plain is None:
        return
    assert plain["pgdata"]["name"] == "rdfc2im-pgdata"
    assert not any(plain["pgdata"]["driver_opts"].values()) and not any(plain["solrdata"]["driver_opts"].values())
    bound = vols(RDFC2IM_PGDATA="/d/pg", RDFC2IM_SOLRDATA="/d/solr", RDFC2IM_PREFIX="rdfc2im-x")
    assert bound["pgdata"]["name"] == "rdfc2im-x-pgdata"
    assert bound["pgdata"]["driver_opts"] == {"type": "none", "o": "bind", "device": "/d/pg"}
    assert bound["solrdata"]["driver_opts"] == {"type": "none", "o": "bind", "device": "/d/solr"}


def test_stage_artifacts_is_per_stack(tmp_path):
    """im-ore.21: a named stack stages into its own $TRIAL_HOME/artifacts; the default stack keeps trial/artifacts
    (RDFC2IM_ARTIFACTS not passed on); an explicit RDFC2IM_ARTIFACTS wins."""
    if not shutil.which("bash"):
        return
    base = dict(os.environ, TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test", LOG_DIR=str(tmp_path / "logs"),
                PG_PORT="39001", SOLR_PORT="39002", MINE_PORT="39003", BG_PORT="39004")  # nothing else may hold them
    base.pop("RDFC2IM_ARTIFACTS", None)

    def stage_cmd(extra_env, *args):
        r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--only", "stage_artifacts", *args],
                           cwd=ROOT, env=dict(base, **extra_env), capture_output=True, text=True)
        out = r.stdout + r.stderr
        if r.returncode != 0 and "[check_prereqs] FATAL" in out:
            return None
        assert r.returncode == 0, out
        return next(c for c in _cmds(out) if "tools/trial-stage.sh" in c)

    named = stage_cmd({}, "--stack-name", "zz")
    if named is None:
        return
    assert f"RDFC2IM_ARTIFACTS={tmp_path}/trial_home/artifacts " in named, named
    assert "RDFC2IM_ARTIFACTS" not in stage_cmd({}), "the default stack keeps the compose file's ./artifacts"
    assert "RDFC2IM_ARTIFACTS=/x/art " in stage_cmd({"RDFC2IM_ARTIFACTS": "/x/art"}, "--stack-name", "zz")


def test_gene_identifiers_all_fetches_ncbigene_and_hgnc_unscoped_and_keeps_pubmed_on_the_panel(tmp_path):
    """--gene-identifiers all [im-9n4.40]: ncbigene and hgnc get --taxon only (scope=full, no
    genes_md5 in their cache meta), every other gene-shaped source keeps --genes, and the pubmed
    PMID list is gathered from the panel genes' cut of the hgnc items, not from all 44,000 genes.
    The default (panel) build is unchanged."""
    srcs = "ncbigene hgnc ensembl pubmed"
    full = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", srcs, "--gene-identifiers", "all")
    panel = _plan(tmp_path, "--only", "rdfc2im_pipeline", "--sources", srcs)
    if full is None or panel is None:
        return
    fc, pc = _cmds(full), _cmds(panel)
    for src in ("ncbigene", "hgnc"):
        t = next(c for c in fc if f"rdfc2im translate --source {src}" in c)
        assert "--taxon 9606" in t and "--genes" not in t, t
        save = next(c for c in fc if f"rdfc2im cache save {src} " in c)
        assert "scope=full" in _meta(save) and not any(m.startswith("genes_md5=") for m in _meta(save)), save
        assert "--genes @" in next(c for c in pc if f"rdfc2im translate --source {src}" in c)
    assert "--genes @" in next(c for c in fc if "rdfc2im translate --source ensembl" in c)
    cut = next(i for i, c in enumerate(fc) if "subset_raw.py panel-items" in c and "out/hgnc/items/hgnc.xml" in c)
    grep = next(i for i, c in enumerate(fc) if "cited_pmids.txt" in c and "grep" in c)
    assert cut < grep and "hgnc-panel-items.xml" in fc[grep] and "out/{hgnc," not in fc[grep], fc[grep]
    assert not any("panel-items" in c for c in pc)
    assert "out/{hgnc,uniprot,gwascatalog,reactome}" in next(c for c in pc if "cited_pmids.txt" in c and "grep" in c)


def test_gene_identifiers_takes_panel_or_all_only(tmp_path):
    env = dict(os.environ, TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test", LOG_DIR=str(tmp_path / "logs"))
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--gene-identifiers", "some"], cwd=ROOT,
                       env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "--gene-identifiers wants panel or all" in r.stdout + r.stderr
