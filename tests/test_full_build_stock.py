"""tools/full-build.sh --stock-sources, checked through --dry-run (see test_full_build_cache.py).

--stock-sources needs --intermine-src on the 6.0 line (D-5), so these tests make a stand-in
checkout with just the files the script reads before and during the phases under test. They skip,
like the other dry-run tests, where check_prereqs cannot pass (no docker compose or JDK 8).
"""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, "curation", "demo_gene_panel.txt")


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


def _run(tmp_path, *args, stock_dir=True, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "RDFC2IM_STOCK_FILTERED_CACHE"}
    env.update(TRIAL_HOME=str(tmp_path / "trial_home"), RUN_ID="test", LOG_DIR=str(tmp_path / "logs"),
               **(env_extra or {}))
    if stock_dir:
        env["RDFC2IM_STOCK_DIR"] = str(tmp_path / "stock")
    env.pop("RDFC2IM_STOCK_LOCAL", None)
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _plan(tmp_path, *args, env_extra=None):
    """The dry-run log, or None where check_prereqs fails for reasons that are not ours."""
    rc, out = _run(tmp_path, *args, env_extra=env_extra)
    if rc != 0 and "[check_prereqs] FATAL" in out and "stock" not in out.split("FATAL", 1)[1][:200]:
        return None
    assert rc == 0, out
    return out


def _cmds(plan, phase=None):
    pat = r"\[(%s)\] \+ (.*)$" % (re.escape(phase) if phase else r"[a-z0-9_]+")
    return [m.group(2) for line in plan.splitlines() if (m := re.search(pat, line))]


def _stock(tmp_path, *more):
    return ("--intermine-src", _fake_intermine_60(tmp_path), "--stock-sources", "go-annotation uniprot", *more)


def test_the_phase_list_has_the_stock_phases_in_place():
    r = subprocess.run(["bash", "tools/full-build.sh", "--list-phases"], cwd=ROOT, capture_output=True, text=True)
    phases = r.stdout.split()
    i = phases.index("build_humanmine_items")
    assert phases[i + 1:i + 5] == ["build_stock_sources", "fetch_stock_data", "subset_stock_data",
                                   "prepare_mine_checkout"], phases
    assert phases[phases.index("prepare_mine_checkout") + 1] == "stage_src_data"
    assert "build_reactome_source" not in phases


def test_an_empty_stock_list_makes_the_new_phases_no_ops(tmp_path):
    for phase in ("fetch_stock_data", "subset_stock_data"):
        plan = _plan(tmp_path, "--only", phase)
        if plan is None:
            return
        assert _cmds(plan, phase) == [], plan
        assert "no --stock-sources: nothing to" in plan
    plan = _plan(tmp_path, "--only", "prepare_mine_checkout")
    reduce = next(c for c in _cmds(plan) if "reduce_mine.py sources" in c)
    assert reduce.endswith(" humanmine-items reactome"), reduce


def test_stock_sources_need_the_60_line(tmp_path):
    rc, out = _run(tmp_path, "--only", "fetch_stock_data", "--stock-sources", "uniprot")
    if "[check_prereqs] FATAL" in out and "stock" not in out:
        return
    assert rc != 0 and "needs --intermine-src on the 6.0 line" in out, out


def test_an_unknown_or_restricted_stock_source_stops_check_prereqs(tmp_path):
    src = _fake_intermine_60(tmp_path)
    rc, out = _run(tmp_path, "--only", "fetch_stock_data", "--intermine-src", src, "--stock-sources", "uniprot nosuch")
    if "[check_prereqs] FATAL" in out and "stock" not in out:
        return
    assert rc != 0 and "unknown stock source(s) nosuch" in out, out
    rc, out = _run(tmp_path, "--only", "fetch_stock_data", "--intermine-src", src, "--stock-sources", "omim")
    assert rc != 0 and "omim is not redistributable" in out, out
    # ... and a local copy is what lets it through
    local = tmp_path / "local" / "omim"
    local.mkdir(parents=True)
    for f in ("mimTitles.txt", "morbidmap.txt", "pubmed_cited"):
        (local / f).write_text("x\n")
    plan = _plan(tmp_path, "--only", "stage_src_data", "--intermine-src", src, "--stock-sources", "omim",
                 "--stock-local", str(tmp_path / "local"))
    assert any(f"ln -sfn '{local}/mimTitles.txt'" in c for c in _cmds(plan, "stage_src_data")), plan


def test_stock_sources_are_put_in_humanmines_order_and_kept_by_project_and_reduce(tmp_path):
    if not os.path.exists(os.path.join(ROOT, "in", "humanmine_project.xml")):
        return                                  # in/ (make-inputs.sh) gives HumanMine's order
    plan = _plan(tmp_path, "--only", "rdfc2im_project", *_stock(tmp_path))
    if plan is None:
        return
    assert "stock sources, in HumanMine's project.xml order: uniprot go-annotation" in plan
    proj = next(c for c in _cmds(plan) if "rdfc2im project" in c)
    assert proj.endswith("--stock-source uniprot --stock-source go-annotation"), proj
    plan = _plan(tmp_path, "--only", "prepare_mine_checkout", *_stock(tmp_path))
    reduce = next(c for c in _cmds(plan) if "reduce_mine.py sources" in c)
    assert reduce.endswith(" humanmine-items reactome uniprot go-annotation"), reduce


def test_fetch_downloads_into_the_stock_cache_once_per_source(tmp_path):
    plan = _plan(tmp_path, "--only", "fetch_stock_data", *_stock(tmp_path))
    if plan is None:
        return
    stock, cmds = tmp_path / "stock", _cmds(plan, "fetch_stock_data")
    dl = next(i for i, c in enumerate(cmds) if c.startswith("curl -fsSL") and c.endswith("uniprot_sprot_human.xml.gz"))
    save = next(i for i, c in enumerate(cmds) if "cache save stock-raw-uniprot " in c)
    assert dl < save and f"--cache-dir {stock}/cache" in cmds[save], cmds
    assert "--meta url.sprot=https://ftp.ebi.ac.uk/" in cmds[save] and "last_modified.sprot=" in cmds[save]
    assert not any(str(os.path.join(ROOT, "cached_raw_data")) in c for c in cmds), "raw data never in cached_raw_data/"
    cached = _plan(tmp_path, "--only", "fetch_stock_data", "--use-cached-data", *_stock(tmp_path))
    ccmds = _cmds(cached, "fetch_stock_data")
    assert not any("curl" in c for c in ccmds), ccmds
    assert any("cache verify stock-raw-go-annotation " in c and "--meta url.gaf=" in c for c in ccmds), ccmds


def test_subset_filters_with_subset_raw_and_caches_by_gene_panel(tmp_path):
    plan = _plan(tmp_path, "--only", "subset_stock_data", *_stock(tmp_path))
    if plan is None:
        return
    stock, cmds = tmp_path / "stock", _cmds(plan, "subset_stock_data")
    assert cmds[0].startswith(f"python3 tools/subset_raw.py idsets --genes {PANEL} --out {stock}/idsets")
    flt = next(c for c in cmds if "subset_raw.py filter --format uniprot-xml" in c)
    assert f"--ids {stock}/idsets/uniprot.txt" in flt and "/subset/uniprot/sprot/9606_uniprot_sprot.xml " in flt
    assert f"--in {stock}/cache/stock-raw-uniprot/data/uniprot_sprot_human.xml.gz" in flt
    save = next(c for c in cmds if "cache save stock-uniprot " in c)
    assert f"--cache-dir {ROOT}/cached_raw_data" in save
    for k in ("genes_md5=", "taxon=9606", "spec_md5=", "redistributable=true", "licence="):
        assert f"--meta {k}" in save, (k, save)
    cached = _cmds(_plan(tmp_path, "--only", "subset_stock_data", "--use-cached-data", *_stock(tmp_path)),
                   "subset_stock_data")
    # the stock files come from the filtered cache; only the resolver's entrez is always (re)made
    assert not any("subset_raw.py filter" in c and "--format gene_info" not in c for c in cached), cached
    restore = next(c for c in cached if "cache restore stock-go-annotation " in c)
    assert "--meta genes_md5=" in restore and "--meta spec_md5=" in restore and "--meta licence=" not in restore


def test_use_cached_data_cuts_a_missing_filtered_group_from_the_cached_raw_one(tmp_path):
    """[im-9n4.6] A panel change gives a new genes_md5, so --use-cached-data found no filtered group
    to restore and died, although the raw group was cached and filtering needs no network. Now the
    files are cut from the raw group and saved; a source with no raw group still restores."""
    raw = tmp_path / "stock" / "cache" / "stock-raw-uniprot"
    raw.mkdir(parents=True)
    (raw / "META.json").write_text("{}")
    fcache = tmp_path / "filtered-cache"
    plan = _plan(tmp_path, "--only", "subset_stock_data", "--use-cached-data", *_stock(tmp_path),
                 env_extra={"RDFC2IM_STOCK_FILTERED_CACHE": str(fcache)})
    if plan is None:
        return
    cmds = _cmds(plan, "subset_stock_data")
    assert "uniprot: no filtered group for this panel" in plan
    assert any("subset_raw.py filter --format uniprot-xml" in c for c in cmds), cmds
    save = next(c for c in cmds if "cache save stock-uniprot " in c)
    assert f"--cache-dir {fcache} " in save, save
    assert not any("cache restore stock-uniprot " in c for c in cmds), cmds
    # go-annotation has no raw group here: it is restored as before (and would fail if absent)
    assert any("cache restore stock-go-annotation " in c and f"--cache-dir {fcache} " in c for c in cmds), cmds
    assert not any("--format gaf" in c for c in cmds), cmds


def test_postprocess_runs_the_stock_postprocesses_in_humanmines_order(tmp_path):
    """[im-9n4.6] The hook ran nothing; now the table's postprocesses run between create-references
    and create-attribute-indexes in HumanMine's order, do-sources scoped to the sources wanting it."""
    plan = _plan(tmp_path, "--only", "postprocess", "--intermine-src", _fake_intermine_60(tmp_path),
                 "--stock-sources", "uniprot go-annotation ncbi-gff ncbi-fasta", "--sources",
                 "go ncbigene reactome hgnc ensembl uniprot clinvar gwascatalog pubmed")
    if plan is None:
        return
    pp = [c.split("-Pprocess=", 1)[1].rstrip(")") for c in _cmds(plan, "postprocess") if "-Pprocess=" in c]
    assert pp[:9] == ["create-references", "create-chromosome-locations-and-lengths", "transfer-sequences",
                      "do-sources -Psource=go-annotation", "create-gene-flanking-features",
                      "create-location-overlap-index", "create-overlap-view", "create-attribute-indexes",
                      "do-sources -Psource=reactome"], pp
    assert "HOOK" not in plan
    # without stock sources: as before
    plain = _plan(tmp_path, "--only", "postprocess")
    pp = [c.split("-Pprocess=", 1)[1].rstrip(")") for c in _cmds(plain, "postprocess") if "-Pprocess=" in c]
    assert pp[:3] == ["create-references", "create-attribute-indexes", "do-sources -Psource=reactome"], pp


def test_stage_links_into_humanmines_own_paths_and_never_over_a_real_file(tmp_path):
    plan = _plan(tmp_path, "--only", "stage_src_data", *_stock(tmp_path))
    if plan is None:
        return
    cmds = _cmds(plan, "stage_src_data")
    link = next(c for c in cmds if "gene_association.goa_human" in c)
    assert "/go-annotation/current/human/gene_association.goa_human'" in link
    assert "refusing to replace the real file" in link and "ln -sfn" in link
    assert any(c.startswith("find ") and "/uniprot/current" in c and "-delete" in c for c in cmds), cmds


def test_the_jar_of_an_intermine_stock_source_comes_from_publish_intermine(tmp_path):
    plan = _plan(tmp_path, "--only", "build_stock_sources", *_stock(tmp_path))
    if plan is None:
        return
    assert "uniprot: bio-source-uniprot 6.0.0 from publish_intermine" in plan, plan
    assert "UniProt2Reactome.txt" in plan                  # reactome is still built first
    old = _plan(tmp_path, "--only", "build_reactome_source", *_stock(tmp_path))
    assert "[build_stock_sources]" in old                   # the old phase name still works


# ---- the ID-resolver gate (plan 50 2.2, T0.3)

def _show(tmp_path, *args):
    return _plan(tmp_path, *args, env_extra={"RDFC2IM_DRY_RUN_SHOW_WRITES": "1"})


def test_an_empty_stock_list_leaves_resolver_steps_out_entirely(tmp_path):
    for phase in ("fetch_stock_data", "subset_stock_data", "prepare_mine_checkout"):
        plan = _show(tmp_path, "--only", phase)
        if plan is None:
            return
        mine = [l for l in plan.splitlines() if f"[{phase}]" in l]
        assert not any(w in l for l in mine for w in ("stock-raw-resolver", "gene_info", "idresolver", "/resolver")), (phase, mine)
        assert "resolver.file.rootpath" not in plan


def test_fetch_gets_gene_info_into_its_own_raw_group(tmp_path):
    plan = _plan(tmp_path, "--only", "fetch_stock_data", *_stock(tmp_path))
    if plan is None:
        return
    stock, cmds = tmp_path / "stock", _cmds(plan, "fetch_stock_data")
    url = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz"
    dl = next(i for i, c in enumerate(cmds) if c.startswith("curl -fsSL") and c.endswith(url))
    save = next(i for i, c in enumerate(cmds) if "cache save stock-raw-resolver " in c)
    assert dl < save and f"--cache-dir {stock}/cache" in cmds[save], cmds
    assert f"--meta url.gene_info={url}" in cmds[save] and "--meta redistributable=true" in cmds[save]
    # every other raw group now carries the flag too, so check-release has something to read
    assert any("cache save stock-raw-uniprot " in c for c in cmds)
    cached = _cmds(_plan(tmp_path, "--only", "fetch_stock_data", "--use-cached-data", *_stock(tmp_path)),
                   "fetch_stock_data")
    assert any("cache verify stock-raw-resolver " in c and f"--meta url.gene_info={url}" in c for c in cached), cached
    assert not any("curl" in c for c in cached)


def test_subset_writes_the_all_human_gene_info_as_entrez_in_the_resolver_root(tmp_path):
    plan = _plan(tmp_path, "--only", "subset_stock_data", *_stock(tmp_path))
    if plan is None:
        return
    stock, cmds = tmp_path / "stock", _cmds(plan, "subset_stock_data")
    flt = next(c for c in cmds if "subset_raw.py filter --format gene_info" in c)
    assert f"--in {stock}/cache/stock-raw-resolver/data/Homo_sapiens.gene_info.gz" in flt
    assert flt.endswith(f"--taxon 9606 --out {stock}/resolver/entrez"), flt      # plain text, no --ids (D-1)
    assert cmds.index(f"mkdir -p {stock}/resolver") < cmds.index(flt)
    plan = _plan(tmp_path, "--only", "subset_stock_data", "--resolver-scope", "panel", *_stock(tmp_path))
    flt = next(c for c in _cmds(plan, "subset_stock_data") if "subset_raw.py filter --format gene_info" in c)
    assert flt.endswith(f"--out {stock}/resolver/entrez --ids {stock}/idsets/entrez.txt"), flt
    rc, out = _run(tmp_path, "--only", "subset_stock_data", "--resolver-scope", "mouse", *_stock(tmp_path))
    assert rc == 2 and "--resolver-scope wants panel or taxon" in out


def test_the_mine_properties_name_the_resolver_root_and_stale_caches_go(tmp_path):
    plan = _show(tmp_path, "--only", "prepare_mine_checkout", *_stock(tmp_path))
    if plan is None:
        return
    stock = tmp_path / "stock"
    assert f"\nresolver.file.rootpath={stock}/resolver\n" in plan
    cmds = _cmds(plan, "prepare_mine_checkout")
    assert any(c.startswith("find ") and "-name idresolver.cache" in c and c.endswith("-delete") for c in cmds), cmds
    i_del = next(i for i, c in enumerate(cmds) if "idresolver.cache" in c)
    i_write = next(i for i, c in enumerate(cmds) if c.startswith("write ") and "humanmine.properties" in c)
    assert i_del < i_write < len(cmds)
    base = _show(tmp_path, "--only", "prepare_mine_checkout")
    n_base = int(re.search(r"humanmine.properties \((\d+) lines\)", base).group(1))
    assert f"humanmine.properties ({n_base + 1} lines)" in plan



def test_ncbi_gff_is_cut_with_its_neighbour_genes_and_its_chromosome_lengths(tmp_path):
    """[im-9n4.9] subset_stock_data filters the GFF (panel closure only: the table leaves keep_types
    off), then writes the lengths Items XML from the filtered file; stage_src_data links that into
    its own directory."""
    src = _fake_intermine_60(tmp_path)
    plan = _plan(tmp_path, "--only", "subset_stock_data", "--intermine-src", src, "--stock-sources", "ncbi-gff")
    if plan is None:
        return
    cmds = _cmds(plan, "subset_stock_data")
    stock = str(tmp_path / "stock")
    filt = next(c for c in cmds if "subset_raw.py filter --format gff3" in c)
    assert filt.endswith(f"--ids {stock}/idsets/entrez.txt"), filt
    lengths = [i for i, c in enumerate(cmds) if "subset_raw.py chromosome-lengths" in c]
    assert lengths and lengths[0] > cmds.index(filt)
    assert cmds[lengths[0]].endswith(
        f"--in {stock}/subset/ncbi-gff/gff/GRCh38_latest_genomic.gff "
        f"--out {stock}/subset/ncbi-gff/chromosome-lengths/chromosome_lengths.xml --taxon 9606"), cmds[lengths[0]]
    plan = _plan(tmp_path, "--only", "stage_src_data", "--intermine-src", src, "--stock-sources", "ncbi-gff")
    staged = " ".join(_cmds(plan, "stage_src_data"))
    assert (f"ln -sfn '{stock}/subset/ncbi-gff/chromosome-lengths/chromosome_lengths.xml' "
            f"'/micklem/data/human/gff/lengths/chromosome_lengths.xml'") in staged, staged
    plan = _plan(tmp_path, "--only", "fetch_stock_data", "--intermine-src", src, "--stock-sources", "ncbi-gff")
    assert "chromosome-lengths: local copy" not in plan and "ncbi-gff/chromosome-lengths" not in plan


def test_with_genome_sequence_adds_ncbi_fasta_and_transfer_sequences(tmp_path):
    src = _fake_intermine_60(tmp_path)
    rc, out = _run(tmp_path, "--only", "fetch_stock_data", "--intermine-src", src, "--stock-sources", "uniprot",
                   "--with-genome-sequence")
    assert rc == 2 and "--with-genome-sequence needs ncbi-gff in --stock-sources" in out, out
    plan = _plan(tmp_path, "--only", "subset_stock_data", "--intermine-src", src, "--stock-sources", "ncbi-gff",
                 "--with-genome-sequence")
    if plan is None:
        return
    stock = str(tmp_path / "stock")
    assert "stock sources, in HumanMine's project.xml order: ncbi-fasta ncbi-gff" in plan \
        or "stock sources: ncbi-gff ncbi-fasta" in plan, plan
    fasta = next(c for c in _cmds(plan, "subset_stock_data") if "--format fasta" in c)
    assert f"--ids {stock}/idsets/chromosomes.txt" in fasta, fasta
    plan = _plan(tmp_path, "--only", "postprocess", "--intermine-src", src, "--stock-sources", "ncbi-gff",
                 "--with-genome-sequence")
    assert "-Pprocess=transfer-sequences" in plan and "-Pprocess=create-chromosome-locations-and-lengths" in plan


# ---- the reduced web config comes back from the pristine checkout [im-9n4.11]

def test_build_dbmodel_restores_the_two_reduced_files_before_it_reduces_them_again(tmp_path):
    plan = _plan(tmp_path, "--only", "build_dbmodel", *_stock(tmp_path))
    if plan is None:
        return
    cmds = _cmds(plan, "build_dbmodel")
    web = next(i for i, c in enumerate(cmds) if c.startswith("bash -c cat ") and "webconfig-model.xml" in c)
    osc = next(i for i, c in enumerate(cmds) if c.startswith("bash -c cat ") and "objectstoresummary.config.properties" in c)
    builddb = next(i for i, c in enumerate(cmds) if ":dbmodel:builddb" in c)
    reduce_web = next(i for i, c in enumerate(cmds) if "reduce_mine.py webconfig" in c)
    assert max(web, osc) < builddb < reduce_web, cmds
    assert any(c.startswith("sed -i s|localhost:[0-9]*/solr/|localhost:") and "objectstoresummary" in c for c in cmds[osc:builddb]), cmds


def test_panther_adds_rat_and_zebrafish_gene_info_to_the_resolver_and_is_cut_first(tmp_path):
    """im-9n4.11: PantherConverter resolves human, rat and fish genes; a resolver file of human genes only leaves
    the others passed through unresolved. One NCBI file per taxon, one cache group each, appended to `entrez`."""
    args = ("--intermine-src", _fake_intermine_60(tmp_path), "--stock-sources", "panther mgi-identifiers uniprot")
    plan = _plan(tmp_path, "--only", "fetch_stock_data", *args)
    if plan is None:
        return
    stock = tmp_path / "stock"
    saves = [c for c in _cmds(plan, "fetch_stock_data") if " cache save stock-raw-resolver" in c]
    assert [c.split()[5] for c in saves] == ["stock-raw-resolver", "stock-raw-resolver-10116", "stock-raw-resolver-7955"], saves
    assert any("/GENE_INFO/Mammalia/Rattus_norvegicus.gene_info.gz" in c for c in _cmds(plan, "fetch_stock_data"))
    plan = _plan(tmp_path, "--only", "subset_stock_data", *args)
    cmds = _cmds(plan, "subset_stock_data")
    flts = [c for c in cmds if "subset_raw.py filter --format gene_info" in c]
    assert [c.split("--taxon ")[1].split()[0] for c in flts] == ["9606", "10116", "7955"], flts
    assert flts[1].endswith(f"--out {stock}/unpacked/resolver-10116.gene_info")
    assert any(c.startswith("bash -c cat ") and c.endswith(f">> '{stock}/resolver/entrez'") for c in cmds)
    # panther is cut before mgi-identifiers, and its partner genes become the id set that file is cut to
    pan = next(i for i, c in enumerate(cmds) if "stock-panther " in c and "cache save" in c)
    part = next(i for i, c in enumerate(cmds) if "subset_raw.py partner-ids" in c)
    mgi = next(i for i, c in enumerate(cmds) if "subset_raw.py filter --format tab" in c and "MRK_List2.rpt" in c)
    assert pan < part < mgi, cmds
    assert f"--ids {stock}/idsets/mgi.txt" in cmds[mgi] and "--column 1" in cmds[mgi]


def test_psi_intact_and_biogrid_are_filtered_straight_from_their_zips_and_staged_under_member_names(tmp_path):
    """[im-9n4.13] psi-xml: subset_raw reads the zip and a member glob itself (no unzip of IntAct's 20 GB), writing
    one file per member into the work directory, which stage_src_data links file by file."""
    src = _fake_intermine_60(tmp_path)
    names = "psi-mi-ontology psi-intact biogrid"
    plan = _plan(tmp_path, "--only", "subset_stock_data", "--intermine-src", src, "--stock-sources", names)
    if plan is None:
        return
    cmds, stock = _cmds(plan, "subset_stock_data"), str(tmp_path / "stock")
    intact = next(c for c in cmds if "subset_raw.py filter --format psi-xml" in c and "human.zip" in c)
    assert intact == (f"python3 tools/subset_raw.py filter --format psi-xml --in {stock}/cache/stock-raw-psi-intact/"
                      f"data/human.zip --ids {stock}/idsets/uniprot.txt --xref-db uniprotkb --member *.xml "
                      f"--out {stock}/subset/psi-intact/human"), intact
    grid = next(c for c in cmds if "subset_raw.py filter --format psi-xml" in c and "BIOGRID" in c)
    assert f"--ids {stock}/idsets/entrez.txt --xref-db entrez gene/locuslink" in grid
    assert grid.endswith(f"--member BIOGRID-ORGANISM-Homo_sapiens-*.psi25.xml --out {stock}/subset/biogrid/organisms")
    assert not any(c.startswith("unzip") or "unzip -p" in c for c in cmds), cmds
    assert any("cache save stock-psi-intact " in c for c in cmds) and any("cache save stock-biogrid " in c for c in cmds)
    plan = _plan(tmp_path, "--only", "stage_src_data", "--intermine-src", src, "--stock-sources", names)
    staged = " ".join(_cmds(plan, "stage_src_data"))
    assert f"for f in '{stock}/subset/psi-intact/human'/*" in staged and "'/micklem/data/psi/intact/current'" in staged
    assert f"for f in '{stock}/subset/biogrid/organisms'/*" in staged


def test_protein2ipr_is_streamed_through_the_panel_filter_and_interpro_is_cut_to_its_entries(tmp_path):
    """[im-9n4.27] protein2ipr.dat.gz (13.8 GB) is never fetched into the raw cache: the filter reads the URL and
    the cut is cached as stock-protein2ipr; interpro.xml is cut to the entries of those rows."""
    src = _fake_intermine_60(tmp_path)
    args = ("--intermine-src", src, "--stock-sources", "uniprot protein2ipr interpro mgi-alleles panther")
    plan = _plan(tmp_path, "--only", "fetch_stock_data", *args)
    if plan is None:
        return
    fetch = _cmds(plan, "fetch_stock_data")
    assert not any("protein2ipr.dat.gz" in c for c in fetch), fetch
    assert any("interpro.xml.gz" in c and c.startswith("curl") for c in fetch)
    assert "streamed through the panel filter" in plan
    plan = _plan(tmp_path, "--only", "subset_stock_data", *args)
    cmds, stock = _cmds(plan, "subset_stock_data"), str(tmp_path / "stock")
    assert "streaming it from upstream through the panel filter" in plan
    p2i = next(i for i, c in enumerate(cmds) if "subset_raw.py filter --format tab --in https://ftp.ebi.ac.uk/" in c
               and "protein2ipr.dat.gz" in c)
    assert f"--ids {stock}/idsets/uniprot.txt --column 1" in cmds[p2i] and "--require 4=^(PF|SM|SSF" in cmds[p2i]
    assert f"--out {stock}/subset/protein2ipr/matches/protein2ipr.dat" in cmds[p2i], cmds[p2i]
    saved = next(i for i, c in enumerate(cmds) if "cache save stock-protein2ipr " in c)
    ipr = next(i for i, c in enumerate(cmds) if "subset_raw.py ipr-ids" in c)
    inter = next(i for i, c in enumerate(cmds) if "subset_raw.py filter --format interpro-xml" in c)
    assert p2i < saved < ipr < inter, cmds
    assert f"--ids {stock}/idsets/ipr.txt" in cmds[inter]
    # the alleles file is cut by the mouse genes of panther's rows and loses its Ensembl column
    pan = next(i for i, c in enumerate(cmds) if "cache save stock-panther " in c)
    part = next(i for i, c in enumerate(cmds) if "subset_raw.py partner-ids" in c)
    al = next(i for i, c in enumerate(cmds) if "--format tab" in c and "MGI_PhenotypicAllele.rpt" in c)
    assert pan < part < al and "--column 7 --drop-columns 10" in cmds[al] and f"--ids {stock}/idsets/mgi.txt" in cmds[al]
    # offline cannot stream: with no filtered group it says so rather than reaching for the network
    rc, out = _run(tmp_path, "--only", "subset_stock_data", "--offline", *args)
    assert rc == 0, out      # a dry run logs the plan; the check is the die() that --offline takes in a real run


def test_update_data_sources_gets_the_publication_key_in_the_copy_of_the_checkout(tmp_path):
    """[im-9n4.27] DataSourceUpdater writes a Publication per data source and its keys file keys only DataSource, so
    every run duplicated the papers the mine already had. The copy of the checkout (not the checkout) is edited.
    (The stand-in checkout has no module list, so the phase stops after the edit: only the log up to there is read.)"""
    src = _fake_intermine_60(tmp_path)
    rc, plan = _run(tmp_path, "--only", "publish_intermine", "--intermine-src", src, "--stock-sources", "update-data-sources")
    if "[check_prereqs] FATAL" in plan and "stock" not in plan.split("FATAL", 1)[1][:200]:
        return
    edit = [ln for ln in plan.splitlines() if "deployer edit:" in ln and "update-data-sources_keys.properties" in ln]
    assert edit and "Publication keyed on pubMedId" in edit[0], plan
    sed = [c for c in _cmds(plan, "publish_intermine") if c.startswith("sed -i") and "Publication.key_pubmed" in c]
    assert sed and "/trial_home/intermine-src/bio/sources/update-data-sources/" in sed[0] and src not in sed[0], sed
    rc, plan = _run(tmp_path, "--only", "publish_intermine", "--intermine-src", src, "--stock-sources", "go-annotation uniprot")
    assert "update-data-sources_keys" not in plan
