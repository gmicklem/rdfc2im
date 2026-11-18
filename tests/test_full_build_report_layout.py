"""tools/full-build.sh --report-layout FILE [im-9n4.16]: off by default, then two tool calls after the
template restart. Dry-run checks in the style of test_full_build_wiring.py; they skip where
check_prereqs cannot pass."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_full_build_stock import _cmds, _plan  # noqa: E402

LAYOUT = "curation/humanmine_bluegenes_properties.json"


def test_without_the_flag_apply_templates_is_as_before(tmp_path):
    plan = _plan(tmp_path, "--only", "apply_templates")
    if plan is None:
        return
    cmds = _cmds(plan, "apply_templates")
    assert not any("apply_report_layout" in c or "apply_humanmine_templates" in c for c in cmds), cmds
    assert any("demo_public_templates.sql" in c for c in cmds) and any(c.startswith("docker restart") for c in cmds)


def test_the_flag_runs_templates_then_layout_after_the_restart(tmp_path):
    plan = _plan(tmp_path, "--only", "apply_templates", "--report-layout", LAYOUT)
    if plan is None:
        return
    cmds = _cmds(plan, "apply_templates")
    restart = next(i for i, c in enumerate(cmds) if c.startswith("docker restart"))
    tpl = next(i for i, c in enumerate(cmds) if "tools/apply_humanmine_templates.py" in c)
    lay = next(i for i, c in enumerate(cmds) if "tools/apply_report_layout.py" in c)
    assert restart < tpl < lay, cmds
    assert "curation/humanmine_templates.xml" in cmds[tpl] and "--wait 300" in cmds[tpl]
    assert f"apply_report_layout.py {LAYOUT} " in cmds[lay] and "--bluegenes http://localhost:" in cmds[lay]
    assert "/humanmine" in cmds[lay]


def test_the_flag_still_applies_with_skip_templates_and_without_the_sql_restart(tmp_path):
    plan = _plan(tmp_path, "--only", "apply_templates", "--skip-templates", "--report-layout", LAYOUT)
    if plan is None:
        return
    cmds = _cmds(plan, "apply_templates")
    assert not any("demo_public_templates.sql" in c for c in cmds)
    assert any("tools/apply_report_layout.py" in c for c in cmds)


def test_a_missing_layout_file_is_refused(tmp_path):
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(["bash", "tools/full-build.sh", "--dry-run", "--only", "apply_templates",
                        "--report-layout", "/nonexistent/layout.json"], cwd=root, capture_output=True, text=True,
                       env=dict(os.environ, LOG_DIR=str(tmp_path / "logs")))
    out = r.stdout + r.stderr
    if "[check_prereqs] FATAL" in out:
        return
    assert r.returncode != 0 and "no such file" in out, out
