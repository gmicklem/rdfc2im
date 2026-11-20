"""The BlueGenes home page links the "All data sources" template [im-9n4.60].

BlueGenes reads its home-page call-to-action blocks from the mine's web properties (/service/web-properties,
"bluegenes.homepage.cta.<n>.label/text" and one of route, dispatch or url: bluegenes events/webproperties.cljs and
specs.cljs). The mine serves every WEB-INF/<word>.web.properties of the exploded webapp before WEB-INF/web.properties
(InterMine InitialiserPlugin.loadWebProperties), so tools/trial-stage.sh puts curation/rdfc2im.web.properties there
on every build. A custom list replaces BlueGenes' eight default blocks, so the file gives all eight again, with
"Browse sources" (BlueGenes' own four-column DataSet query) replaced by a link to the template.
"""
import os
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPS = ROOT / "curation" / "rdfc2im.web.properties"
METADATA_SQL = ROOT / "curation" / "metadata_templates.sql"
COMPOSE = ROOT / "trial" / "docker-compose.yml"

# bluegenes route.cljs names (bluegenes.route/<name>) and re-frame events that take no argument
BLUEGENES_ROUTES = {"home", "admin", "tools", "profile", "templates", "upload", "upgrade", "search", "querybuilder",
                    "regions", "lists", "resetpassword"}
BLUEGENES_EVENTS = {"home/query-data-sources", "home/scroll-to-feedback"}


def read_properties(text):
    """Java .properties, the subset this file uses: key=value lines, # comments, no continuation lines."""
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "!")):
            continue
        assert not s.endswith("\\"), "no continuation lines: %r" % line
        key, _, value = s.partition("=")
        out[key.strip()] = value.strip()
    return out


def cta_items(props):
    """[{label, text, route|dispatch|url}] in BlueGenes' order (the numbers, as integers)."""
    items = {}
    for key, value in props.items():
        m = re.fullmatch(r"bluegenes\.homepage\.cta\.(\d+)\.(\w+)", key)
        assert m, "only bluegenes.homepage.cta.<n>.<field> belongs here: %s" % key
        items.setdefault(int(m.group(1)), {})[m.group(2)] = value
    return [items[n] for n in sorted(items)]


def _items():
    return cta_items(read_properties(PROPS.read_text(encoding="ascii")))


def test_the_file_is_one_the_mine_loads():
    # InitialiserPlugin: Pattern.compile("/WEB-INF/(?!global)\\w+\\.web\\.properties$")
    assert re.search(r"/WEB-INF/(?!global)\w+\.web\.properties$", "/WEB-INF/" + PROPS.name)
    PROPS.read_text(encoding="ascii")   # Properties.load reads ISO-8859-1: keep it ASCII


def test_every_block_is_valid_for_bluegenes():
    """BlueGenes drops the whole custom list (console error "Invalid web property bluegenes.homepage.cta") when one
    block lacks label or text or has none of route, dispatch, url."""
    items = _items()
    assert len(items) == 8
    for it in items:
        assert it.get("label") and it.get("text"), it
        kinds = [k for k in ("route", "dispatch", "url") if k in it]
        assert len(kinds) == 1 and set(it) == {"label", "text", kinds[0]}, it
        if "route" in it:
            assert it["route"] in BLUEGENES_ROUTES, it
        if "dispatch" in it:
            assert it["dispatch"] in BLUEGENES_EVENTS, it


def test_the_home_page_links_the_all_data_sources_template():
    """The second block (where BlueGenes' "Browse sources" was) opens the template's page,
    <BlueGenes>/<mine namespace>/templates/<template name>: the namespace is the compose file's, the name the
    template's in curation/metadata_templates.sql."""
    items = _items()
    ns = re.search(r'BLUEGENES_DEFAULT_NAMESPACE: "([^"]+)"', COMPOSE.read_text()).group(1)
    link = items[1]
    assert link["label"] == "All data sources"
    assert link["url"] == "/%s/templates/All_data_sources" % ns
    assert '<template name="All_data_sources" title="All data sources"' in METADATA_SQL.read_text()
    assert not any(it.get("dispatch") == "home/query-data-sources" for it in items), "the old query is replaced"


def test_the_other_default_blocks_are_kept():
    labels = [it["label"] for it in _items()]
    assert labels == ["Analyse data", "All data sources", "Build your own query", "Tutorials", "Web services",
                      "Submit feedback", "What's new", "Cite us"]


# -------------------------------------------------------------- staged on every build

def _fake_trial_home(tmp_path, web_properties="project.title=x\n"):
    home = tmp_path / "home"
    war = home / "humanmine" / "webapp" / "build" / "libs" / "webapp.war"
    war.parent.mkdir(parents=True)
    with zipfile.ZipFile(war, "w") as z:
        z.writestr("WEB-INF/web.properties", web_properties)
        z.writestr("WEB-INF/global.web.properties", "a=b\n")
    (home / "bgdeps").mkdir()
    (home / "bgdeps" / "classpath.txt").write_text("")
    return home


def _stage(tmp_path, home):
    art = tmp_path / "art"
    env = dict(os.environ, TRIAL_HOME=str(home), RDFC2IM_ARTIFACTS=str(art))
    r = subprocess.run(["sh", str(ROOT / "tools" / "trial-stage.sh")], cwd=ROOT, env=env, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return art, r.stdout + r.stderr


def test_trial_stage_puts_the_file_in_the_webapp(tmp_path):
    art, _ = _stage(tmp_path, _fake_trial_home(tmp_path))
    staged = art / "humanmine" / "WEB-INF" / "rdfc2im.web.properties"
    assert staged.read_bytes() == PROPS.read_bytes()


def test_trial_stage_warns_when_the_wars_own_web_properties_would_override_it(tmp_path):
    """WEB-INF/web.properties is loaded last and wins: a mine whose own file sets the home-page blocks hides ours."""
    _, out = _stage(tmp_path, _fake_trial_home(tmp_path, "bluegenes.homepage.cta.1.label=Theirs\n"))
    assert "WARNING" in out and "bluegenes.homepage.cta" in out
    _, out = _stage(tmp_path, _fake_trial_home(tmp_path / "b"))
    assert "WARNING" not in out
