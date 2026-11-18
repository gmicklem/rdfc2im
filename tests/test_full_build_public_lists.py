"""tools/full-build.sh --public-lists DIR [im-9n4.22]: phase apply_public_lists, off by default, one call of
tools/apply_public_lists.py after apply_templates. Dry-run checks in the style of test_full_build_report_layout.py; they
skip where check_prereqs cannot pass."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_full_build_stock import _cmds, _plan, _run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dirs(tmp_path):
    cache, archive = tmp_path / "panelapp", tmp_path / "archive"
    cache.mkdir()
    archive.mkdir()
    return str(cache), str(archive)


def test_the_phase_follows_apply_templates_and_precedes_verify():
    r = subprocess.run(["bash", "tools/full-build.sh", "--list-phases"], cwd=ROOT, capture_output=True, text=True)
    phases = r.stdout.split()
    i = phases.index("apply_templates")
    assert phases[i:i + 3] == ["apply_templates", "apply_public_lists", "verify"], phases


def test_without_the_flag_the_phase_is_a_logged_no_op(tmp_path):
    plan = _plan(tmp_path, "--only", "apply_public_lists")
    if plan is None:
        return
    assert _cmds(plan, "apply_public_lists") == []
    assert "no --public-lists" in plan


def test_the_other_phases_are_the_same_with_and_without_the_flag(tmp_path):
    cache, archive = _dirs(tmp_path)
    a = _plan(tmp_path, "--only", "apply_templates")
    if a is None:
        return
    b = _plan(tmp_path, "--only", "apply_templates", "--public-lists", cache, "--public-lists-archive", archive)
    assert _cmds(a, "apply_templates") == _cmds(b, "apply_templates")


def test_the_flag_makes_one_call_of_the_tool_with_the_archive_and_the_default_names(tmp_path):
    cache, archive = _dirs(tmp_path)
    plan = _plan(tmp_path, "--only", "apply_public_lists", "--public-lists", cache, "--public-lists-archive", archive)
    if plan is None:
        return
    cmds = _cmds(plan, "apply_public_lists")
    assert len(cmds) == 1, cmds
    c = cmds[0]
    assert c.startswith("python3 tools/apply_public_lists.py --mine http://localhost:") and "/humanmine " in c
    assert f"--panelapp-cache {cache} " in c and "--legacy curation/public_lists " in c
    assert f"--archive-repo {archive} " in c and "--select all " in c and "--keep-2021-names " in c
    assert "--report " in c and "public-lists-test.json" in c and c.endswith("--wait 300")
    assert "--dry-run" not in c      # the build's own --dry-run only logs; the tool is not run


def test_select_and_names_switches_are_passed_on(tmp_path):
    cache, archive = _dirs(tmp_path)
    plan = _plan(tmp_path, "--only", "apply_public_lists", "--public-lists", cache, "--public-lists-archive", archive,
                 "--public-lists-select", "100k", "--public-lists-names", "current")
    if plan is None:
        return
    c = _cmds(plan, "apply_public_lists")[0]
    assert "--select 100k " in c and "--current-names " in c and "--keep-2021-names" not in c


def test_the_flag_needs_an_archive_and_the_values_are_checked(tmp_path):
    cache, archive = _dirs(tmp_path)
    for args, msg in ((("--public-lists", cache), "needs --public-lists-archive"),
                      (("--public-lists-select", "some"), "wants all or 100k"),
                      (("--public-lists-names", "old"), "wants 2021 or current")):
        rc, out = _run(tmp_path, "--only", "apply_public_lists", *args)
        assert rc == 2 and msg in out, out


def test_a_missing_directory_is_refused(tmp_path):
    cache, archive = _dirs(tmp_path)
    rc, out = _run(tmp_path, "--only", "apply_public_lists", "--public-lists", "/nonexistent/panelapp",
                   "--public-lists-archive", archive)
    if "[check_prereqs] FATAL" in out:
        return
    assert rc != 0 and "no such directory" in out, out
