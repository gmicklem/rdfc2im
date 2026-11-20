"""tools/full-build.sh --source-pages DIR and --data-set-links URL [im-9n4.42]: both off by default (phase list and
dry-run output as before), then a last phase write_source_manifest and, in prepare_mine_checkout, the DataSet link
source. Dry-run checks in the style of test_full_build_report_layout.py; they skip where check_prereqs cannot pass."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_full_build_stock import _cmds, _plan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://github.com/gmicklem/humanmine/blob/maint-2026/docs/data-sources"


def _phases(*args):
    r = subprocess.run(["bash", "tools/full-build.sh", "--list-phases", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.split()


def test_without_the_flag_the_phase_list_is_as_before():
    phases = _phases()
    assert phases[-1] == "verify" and "write_source_manifest" not in phases


def test_the_flag_adds_one_last_phase_after_verify():
    phases = _phases("--source-pages", "/tmp/pages")
    assert phases[-2:] == ["verify", "write_source_manifest"] and phases[:-1] == _phases()


def test_the_phase_writes_the_manifest_then_the_pages(tmp_path):
    plan = _plan(tmp_path, "--only", "write_source_manifest", "--source-pages", str(tmp_path / "pages"),
                 "--stack-name", "ut")
    if plan is None:
        return
    cmds = _cmds(plan, "write_source_manifest")
    man = next(i for i, c in enumerate(cmds) if "tools/source_manifest.py" in c)
    pages = next(i for i, c in enumerate(cmds) if "tools/source_pages.py pages" in c)
    assert man < pages, cmds
    assert "--out out/_mine/source_manifest.json" in cmds[man] and "--mine http://localhost:18090/humanmine" in cmds[man]
    assert "--reference-datasets curation/humanmine_2022_datasets.json" in cmds[man]
    assert f"--out {tmp_path / 'pages'}" in cmds[pages]


def test_without_data_set_links_the_source_still_carries_the_versions(tmp_path):
    """DataSet.version is written on every build [im-9n4.52]: the same source, from the caches, without the page links."""
    plan = _plan(tmp_path, "--only", "prepare_mine_checkout")
    if plan is None:
        return
    cmds = _cmds(plan, "prepare_mine_checkout")
    links = next(i for i, c in enumerate(cmds) if "source_pages.py data-set-links" in c)
    add = next(i for i, c in enumerate(cmds) if "source_pages.py add-links-source" in c)
    assert links < add and "--base-url" not in cmds[links], cmds[links]
    for opt in ("--stock-dir ", "--cache-dir "):
        assert opt in cmds[links], (opt, cmds[links])


def test_data_set_links_add_the_source_after_the_priorities_are_written(tmp_path):
    plan = _plan(tmp_path, "--only", "prepare_mine_checkout", "--data-set-links", URL)
    if plan is None:
        return
    cmds = _cmds(plan, "prepare_mine_checkout")
    reduce_ = next(i for i, c in enumerate(cmds) if "tools/reduce_mine.py sources" in c)
    links = next(i for i, c in enumerate(cmds) if "source_pages.py data-set-links" in c)
    add = next(i for i, c in enumerate(cmds) if "source_pages.py add-links-source" in c)
    assert reduce_ < links < add, cmds
    assert f"--base-url {URL} " in cmds[links] and "/rdfc2im/_data-set-links/data_set_links.xml" in cmds[links]
    assert "humanmine/project.xml" in cmds[add] and "genomic_priorities.properties" in cmds[add]
    write = next(i for i, c in enumerate(cmds) if c.startswith("write ") and "genomic_priorities.properties" in c)
    assert write < add, cmds       # the priorities file is deployed first, then ranked for DataSet.url/description/version
