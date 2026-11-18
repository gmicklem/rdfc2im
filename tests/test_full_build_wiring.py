"""tools/full-build.sh wiring added by im-9n4.4: --jbrowse2-src, --with-front, the humanmine.properties heredoc.

Dry-run checks in the style of test_full_build_stock.py (which provides the helpers); they skip where
check_prereqs cannot pass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_full_build_stock import _cmds, _plan, _show  # noqa: E402


def test_stage_artifacts_stages_the_patched_tool_set_only_with_jbrowse2_src(tmp_path):
    plain = _plan(tmp_path, "--only", "stage_artifacts")
    if plain is None:
        return
    assert not any("stage-bluegenes-tools" in c for c in _cmds(plain, "stage_artifacts")), plain
    assert any("tools/trial-stage.sh" in c for c in _cmds(plain, "stage_artifacts"))
    plan = _plan(tmp_path, "--only", "stage_artifacts", "--jbrowse2-src", "/x/jbrowse2/bluegenes-tool")
    cmds = _cmds(plan, "stage_artifacts")
    stage = next(i for i, c in enumerate(cmds) if "tools/trial-stage.sh" in c)
    bg = next(i for i, c in enumerate(cmds) if c.startswith("tools/stage-bluegenes-tools.sh"))
    assert stage < bg, "after trial-stage.sh"
    art = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trial", "artifacts")
    assert "--jbrowse2-src /x/jbrowse2/bluegenes-tool" in cmds[bg]
    assert f"--out {art}/bluegenes-tools-patched --install-to {art}/bluegenes-tools" in cmds[bg]
    assert "--src-cache " in cmds[bg] and "/cached_raw_data/bluegenes-tools/data" in cmds[bg]
    # the environment variable does the same, and a named stack's artifacts directory is used
    plan = _plan(tmp_path, "--only", "stage_artifacts", env_extra={"JBROWSE2_SRC": "/y/tool",
                                                                     "RDFC2IM_ARTIFACTS": str(tmp_path / "art")})
    bg = next(c for c in _cmds(plan, "stage_artifacts") if c.startswith("tools/stage-bluegenes-tools.sh"))
    assert "--jbrowse2-src /y/tool" in bg and f"--install-to {tmp_path}/art/bluegenes-tools" in bg


def test_start_mine_stack_starts_the_front_only_with_with_front(tmp_path):
    plain = _plan(tmp_path, "--only", "start_mine_stack")
    if plain is None:
        return
    assert not any("front/up.sh" in c for c in _cmds(plain, "start_mine_stack")), plain
    cmds = _cmds(_plan(tmp_path, "--only", "start_mine_stack", "--with-front"), "start_mine_stack")
    up = next(i for i, c in enumerate(cmds) if c == "trial/front/up.sh")
    restart = next(i for i, c in enumerate(cmds) if c.startswith("docker restart"))
    assert any(" up -d mine bluegenes" in c for c in cmds[:restart]) and restart < up, cmds


def test_the_properties_comment_with_backticks_is_written_intact(tmp_path):
    """The heredoc was unquoted, so backticks in a comment ran as commands ("syntax error near
    `webapp.hostname`") on every run and the words in them vanished from the file."""
    plan = _show(tmp_path, "--only", "prepare_mine_checkout")
    if plan is None:
        return
    assert "syntax error" not in plan and "command substitution" not in plan, plan
    assert '# should skip this via `if (props.hasProperty("webapp.hostname")) ... else getServerName(...)`,' in plan
    assert "so the `else`" in plan
    assert "superuser.initialPassword=intermine" in plan


def test_the_other_generated_properties_are_unchanged(tmp_path):
    """Only the comment changed: the non-comment lines are exactly what the script always wrote."""
    plan = _show(tmp_path, "--only", "prepare_mine_checkout")
    if plan is None:
        return
    lines = plan.splitlines()
    i = lines.index("db.production=psql")
    body = [l for l in lines[i:i + 60] if l and not l.startswith("#")]
    assert body[0] == "db.production=psql" and "webapp.path=humanmine" in body
    assert any(l.startswith("webapp.deploy.url=http://localhost:") for l in body)
    assert "superuser.account=superuser@intermine.org" in body
