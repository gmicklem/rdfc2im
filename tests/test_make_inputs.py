"""tools/make-inputs.sh: assembling in/ from the cached upstream clones.

The first fresh run of tools/full-build.sh died here: the script copied each clone with a plain
`cp -r`, .git and all, and then deleted the copied .git. On this project's virtiofs workspace mount
that `cp` failed on the clone's read-only pack file ("failed to extend ... pack: Permission
denied", leaving a 0-byte pack) and the build stopped at phase 2 - for a directory that was about
to be thrown away. In/ never needs any .git, so the copy must never touch one. An unreadable file
inside .git reproduces the failure on any filesystem: `cp -r` cannot read it.
"""
import hashlib
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "rdf-config/config/go/model.yaml": b"go: model\n",
    "rdf-config/config/hgnc/model.yaml": b"hgnc: model\n",
    "intermine/bio/sources/reactome/reactome.properties": b"x=1\n",
    "intermine/bio/core/build.gradle": b"apply plugin: 'java'\n",
    "humanmine/project.xml": b"<project/>\n",
    "humanmine/dbmodel/resources/genomic_priorities.properties": b"a = b\n",
    "humanmine-bio-sources/humanmine-go/go.xml": b"<items/>\n" * 100,
    "humanmine-bio-sources/settings.gradle": "include 'x'\n".encode(),
}


def _fake_upstream(cache):
    for rel, data in FILES.items():
        p = os.path.join(cache, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    for repo in ("rdf-config", "intermine", "humanmine", "humanmine-bio-sources"):
        subprocess.run(["git", "init", "-q", os.path.join(cache, repo)], check=True)
    # what a real clone's .git has that a plain copy trips over: something it cannot read
    hostile = os.path.join(cache, "humanmine-bio-sources", ".git", "objects", "pack")
    os.makedirs(hostile, exist_ok=True)
    p = os.path.join(hostile, "pack-x.pack")
    with open(p, "wb") as fh:
        fh.write(b"PACK")
    os.chmod(p, 0)


def _run(tmp_path):
    cache, work = str(tmp_path / "upstream"), tmp_path / "work"
    work.mkdir()
    _fake_upstream(cache)
    env = dict(os.environ, CACHE=cache, MINE="http://127.0.0.1:9")   # no live model: a tolerated warning
    return subprocess.run(["sh", os.path.join(ROOT, "tools", "make-inputs.sh")], cwd=work, env=env,
                          capture_output=True, text=True), work


def _md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def test_assembling_in_never_reads_the_clones_git_directories(tmp_path):
    if os.geteuid() == 0 or not shutil.which("git"):
        return   # root can read a mode-0 file, so the reproduction does not apply
    r, work = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any(".git" in d for d, _, _ in os.walk(work / "in")), "in/ must hold no .git"


def test_in_holds_byte_identical_copies_of_the_upstream_trees(tmp_path):
    if os.geteuid() == 0 or not shutil.which("git"):
        return
    r, work = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    want = {
        "in/config/go/model.yaml": "rdf-config/config/go/model.yaml",
        "in/config/hgnc/model.yaml": "rdf-config/config/hgnc/model.yaml",
        "in/intermine/bio/sources/reactome/reactome.properties": "intermine/bio/sources/reactome/reactome.properties",
        "in/intermine/bio/core/build.gradle": "intermine/bio/core/build.gradle",
        "in/humanmine-bio-sources/humanmine-go/go.xml": "humanmine-bio-sources/humanmine-go/go.xml",
        "in/humanmine-bio-sources/settings.gradle": "humanmine-bio-sources/settings.gradle",
        "in/humanmine_project.xml": "humanmine/project.xml",
        "in/humanmine_priorities.properties": "humanmine/dbmodel/resources/genomic_priorities.properties",
    }
    for dst, src in want.items():
        assert _md5(work / dst) == hashlib.md5(FILES[src]).hexdigest(), dst


def test_a_rerun_replaces_the_previous_copy_rather_than_merging_into_it(tmp_path):
    if os.geteuid() == 0 or not shutil.which("git"):
        return
    r, work = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    stale = work / "in" / "config" / "removed_upstream" / "model.yaml"
    stale.parent.mkdir()
    stale.write_text("stale")
    r2 = subprocess.run(["sh", os.path.join(ROOT, "tools", "make-inputs.sh")], cwd=work, capture_output=True,
                        text=True, env=dict(os.environ, CACHE=str(tmp_path / "upstream"), MINE="http://127.0.0.1:9"))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert not stale.exists()


def test_script_copies_trees_only_through_the_verified_copier():
    """Both `cp -r` and `tar | tar` failed on the virtiofs workspace mount (see test_copy_tree.py),
    and that mount cannot be reproduced here - so pin that the script does not go back to either."""
    text = open(os.path.join(ROOT, "tools", "make-inputs.sh")).read()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "cp -r" not in code and "tar " not in code
    assert "copy_tree.py" in code and code.count('copy_tree "') >= 3


# --- CACHED=1 (full-build.sh --use-cached-data) versus OFFLINE=1 (--offline) [im-ore.17] ---------
# The clones are not part of the raw-data cache. A fresh CI runner has none, so --use-cached-data
# must clone them; only --offline refuses to. GitHub is replaced by local repositories through
# git's url.<base>.insteadOf, so the test needs no network.

REPOS = ("rdf-config", "intermine", "humanmine", "humanmine-bio-sources")


def _fake_github(root):
    """root/<repo>.git for each upstream, holding FILES' files for that repo, one commit."""
    for repo in REPOS:
        work = os.path.join(root, "src-" + repo)
        for rel, data in FILES.items():
            top, _, sub = rel.partition("/")
            if top == repo:
                p = os.path.join(work, sub)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(data)
        g = ["git", "-C", work, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", work], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "x"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", work, os.path.join(root, repo + ".git")], check=True)
        subprocess.run(["git", "-C", os.path.join(root, repo + ".git"), "config", "uploadpack.allowFilter", "true"],
                       check=True)


def _cached_run(tmp_path, extra, make_model=True):
    gh, work = str(tmp_path / "gh"), tmp_path / "work"
    os.makedirs(gh, exist_ok=True)
    work.mkdir(exist_ok=True)
    if not os.path.exists(os.path.join(gh, "rdf-config.git")):
        _fake_github(gh)
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    if make_model:
        for fmt in ("xml", "json"):
            (model / f"humanmine_model.{fmt}").write_text("model\n")
    env = dict(os.environ, CACHE=str(tmp_path / "upstream"), MODEL_DIR=str(model),
               MINE="http://127.0.0.1:9", GIT_CONFIG_COUNT="1",
               GIT_CONFIG_KEY_0=f"url.file://{gh}/.insteadOf", GIT_CONFIG_VALUE_0="https://github.com/",
               **extra)
    # The urls are https://github.com/<org>/<repo>.git: map the org away with a second rewrite.
    env.update(GIT_CONFIG_COUNT="4")
    for i, org in enumerate(("dbcls", "intermine"), start=1):
        env[f"GIT_CONFIG_KEY_{i}"] = f"url.file://{gh}/.insteadOf"
        env[f"GIT_CONFIG_VALUE_{i}"] = f"https://github.com/{org}/"
    env["GIT_CONFIG_KEY_3"] = "protocol.file.allow"
    env["GIT_CONFIG_VALUE_3"] = "always"
    return subprocess.run(["sh", os.path.join(ROOT, "tools", "make-inputs.sh")], cwd=work, env=env,
                          capture_output=True, text=True), work


def test_cached_clones_a_missing_upstream_repo_and_uses_the_restored_model(tmp_path):
    """The nightly's case: --use-cached-data on a runner with no in/.upstream."""
    if not shutil.which("git"):
        return
    r, work = _cached_run(tmp_path, {"CACHED": "1"})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    for repo in REPOS:
        assert os.path.isdir(tmp_path / "upstream" / repo / ".git"), repo
    assert "cloning" in out
    assert (work / "in" / "humanmine_model.xml").read_text() == "model\n", "the model comes from MODEL_DIR"
    assert (work / "in" / "humanmine_project.xml").exists()


def test_cached_leaves_an_existing_clone_alone_without_pulling(tmp_path):
    if not shutil.which("git"):
        return
    r, _ = _cached_run(tmp_path, {"CACHED": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    marker = tmp_path / "upstream" / "humanmine" / "local-marker"
    marker.write_text("kept\n")
    r, _ = _cached_run(tmp_path, {"CACHED": "1"})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "no pull" in out and "refreshing" not in out and "cloning" not in out
    assert marker.exists()


def test_offline_with_a_missing_clone_fails_naming_it_and_clones_nothing(tmp_path):
    if not shutil.which("git"):
        return
    r, _ = _cached_run(tmp_path, {"OFFLINE": "1"})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OFFLINE=1 and no clone" in r.stderr and "rdf-config" in r.stderr
    assert not (tmp_path / "upstream" / "rdf-config" / ".git").exists()


def test_offline_with_the_clones_present_makes_no_request(tmp_path):
    if not shutil.which("git"):
        return
    r, _ = _cached_run(tmp_path, {"CACHED": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    r, work = _cached_run(tmp_path, {"OFFLINE": "1"})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "using the existing clone" in out and "cloning" not in out
    assert (work / "in" / "humanmine_model.json").read_text() == "model\n"


def test_cached_without_the_restored_model_fails_naming_it(tmp_path):
    if not shutil.which("git"):
        return
    r, _ = _cached_run(tmp_path, {"CACHED": "1"}, make_model=False)
    assert r.returncode == 1 and "no $MODEL_DIR/humanmine_model" in r.stderr, r.stdout + r.stderr
