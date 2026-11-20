"""Every path in the public templates curation/demo_public_templates.sql installs must exist in
the mine's model, so a template cannot ship pointing at a field the build does not have
(im-ore.22).

The model is the HumanMine web service's JSON (/service/model?format=json), looked for in this
order: $RDFC2IM_MODEL_JSON (a file; point it at a live demo mine's model to check against what
the build really produced: curl -s 'http://localhost:8090/humanmine/service/model?format=json'),
in/humanmine_model.json, cached_raw_data/humanmine-model/data/humanmine_model.json.  The cached
copy is the full public HumanMine's, a superset of the demo's, so it catches typos but not
fields the demo build lacks; the live model does.  No model, no test (skipped with the reason).
"""
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "curation" / "demo_public_templates.sql"
# The metadata templates [im-9n4.60]: "All data sources", applied by phase apply_templates on every build
METADATA_SQL = ROOT / "curation" / "metadata_templates.sql"
SQLS = (SQL, METADATA_SQL)
MODEL_CANDIDATES = [
    ROOT / "in" / "humanmine_model.json",
    ROOT / "cached_raw_data" / "humanmine-model" / "data" / "humanmine_model.json",
]


def _model_file():
    env = os.environ.get("RDFC2IM_MODEL_JSON")
    if env:
        return Path(env)
    return next((p for p in MODEL_CANDIDATES if p.is_file()), None)


def template_paths(sql_text):
    """[(template name, path)] for every view, sort, join and constraint path of every
    <template> element in the SQL's INSERT statements."""
    out = []
    for m in re.finditer(r"<template\b.*?</template>", sql_text, re.S):
        xml = m.group(0)
        name = re.search(r'<template name="([^"]+)"', xml).group(1)
        for attr in re.findall(r'\bview="([^"]*)"', xml):
            out += [(name, p) for p in html.unescape(attr).split()]
        for attr in re.findall(r'\bsortOrder="([^"]*)"', xml):
            out += [(name, p) for p in html.unescape(attr).split() if p.lower() not in ("asc", "desc")]
        for tag in ("constraint", "join", "pathDescription"):
            for el in re.findall(rf"<{tag}\b[^>]*>", xml):
                for key in ("path", "pathString"):
                    mm = re.search(rf'\b{key}="([^"]*)"', el)
                    if mm:
                        out.append((name, html.unescape(mm.group(1))))
    return out


def resolves(classes, path):
    """Does `path` (Class.ref.ref.attribute) exist in the model's classes, walking `extends`?"""
    first, *steps = path.split(".")
    cls = first
    if cls not in classes:
        return False

    def field(c, f, seen=()):
        if c in seen or c not in classes:
            return None
        info = classes[c]
        for kind in ("attributes", "references", "collections"):
            if f in info.get(kind, {}):
                return kind, info[kind][f]
        for parent in info.get("extends", []):
            got = field(parent, f, seen + (c,))
            if got:
                return got
        return None

    for i, step in enumerate(steps):
        got = field(cls, step)
        if got is None:
            return False
        kind, spec = got
        if kind == "attributes":
            return i == len(steps) - 1
        cls = spec["referencedType"]
    return True


# -------------------------------------------------------------- the helpers themselves

CLASSES = {
    "Gene": {"extends": ["BioEntity"], "attributes": {"symbol": {}},
             "references": {"organism": {"referencedType": "Organism"}},
             "collections": {"publications": {"referencedType": "Publication"}}},
    "BioEntity": {"attributes": {"primaryIdentifier": {}}},
    "Organism": {"attributes": {"name": {}}},
    "Publication": {"attributes": {"pubMedId": {}}},
}


def test_resolves_follows_references_and_inheritance():
    assert resolves(CLASSES, "Gene.organism.name")
    assert resolves(CLASSES, "Gene.publications.pubMedId")
    assert resolves(CLASSES, "Gene.primaryIdentifier")


def test_resolves_rejects_bad_paths():
    assert not resolves(CLASSES, "Gene.firstAuthor")
    assert not resolves(CLASSES, "Gene.symbol.name")
    assert not resolves(CLASSES, "Nothing.name")


def test_template_paths_reads_view_sort_and_constraints():
    sql = ("INSERT INTO t VALUES (1, '<template name=\"T\"><query name=\"T\" model=\"genomic\" "
           "view=\"Gene.symbol Gene.organism.name\" sortOrder=\"Gene.symbol asc\">"
           "<constraint path=\"Gene.primaryIdentifier\" op=\"=\" value=\"x\"/></query></template>');")
    assert {p for _, p in template_paths(sql)} == {
        "Gene.symbol", "Gene.organism.name", "Gene.primaryIdentifier"}


def test_demo_sql_has_templates():
    assert len({n for n, _ in template_paths(SQL.read_text())}) >= 6


# -------------------------------------------------------------- the check

def test_demo_template_paths_exist_in_the_model():
    f = _model_file()
    if f is None:
        pytest.skip("no HumanMine model JSON (set RDFC2IM_MODEL_JSON, or run `make inputs` / fetch "
                    "cached_raw_data/humanmine-model)")
    classes = json.loads(f.read_text())["model"]["classes"]
    bad = sorted({(n, p) for sql in SQLS for n, p in template_paths(sql.read_text()) if not resolves(classes, p)})
    assert not bad, f"template paths missing from the model {f}: {bad}"


# -------------------------------------------------------------- InterMine's rules for a template [im-9n4.60]

def templates_in(sql_text):
    """{name: <template> element} for every template the SQL inserts (the XML is in a single-quoted SQL string)."""
    out = {}
    for m in re.finditer(r"INSERT INTO savedtemplatequery [^;]*?VALUES \([^,]+, '(<template\b.*?</template>)'",
                         sql_text, re.S):
        el = ET.fromstring(m.group(1).replace("''", "'"))
        out[el.get("name")] = el
    return out


def template_tags(sql_text):
    """{template name: [tag names]} from the INSERT INTO tag rows of type 'template'."""
    out = {}
    for name, tag in re.findall(r"INSERT INTO tag \([^)]*\) VALUES \([^,]+, '([^']+)', 'template', '([^']+)', \d+\)",
                                sql_text):
        out.setdefault(name, []).append(tag)
    return out


def outer_joins(query):
    return {j.get("path") for j in query.iter("join") if (j.get("style") or "").upper() == "OUTER"}


def rule_problems(tpl):
    """What InterMine refuses or fails on, read from its source: a template needs at least one editable constraint
    (CreateTemplateAction, TemplatesImportAction: errors.createtemplate.noconstraints), may not have a non-editable
    LOOKUP (TemplateQuery.validateLookupConstraints), its name must be a valid InterMine name (NameUtil: letters,
    digits, underscore here so that it is also a clean BlueGenes route /templates/<name>), and every sort path must
    be in the root outer join group (the query service: "Order by element ... is not in the root outer join
    group", seen live 20 Nov 2026 with an OUTER DataSet.dataSource)."""
    problems = []
    q = tpl.find("query")
    if not re.fullmatch(r"[A-Za-z0-9_]+", tpl.get("name") or ""):
        problems.append("name %r" % tpl.get("name"))
    if q is None or q.get("name") != tpl.get("name"):
        problems.append("query name differs from the template name")
        return problems
    cons = list(q.iter("constraint"))
    if not any(c.get("editable") == "true" for c in cons):
        problems.append("no editable constraint")
    if any(c.get("op") == "LOOKUP" and c.get("editable") != "true" for c in cons):
        problems.append("non-editable LOOKUP")
    joins = outer_joins(q)
    order = [t for t in (q.get("sortOrder") or "").split() if t.lower() not in ("asc", "desc")]
    for p in order:
        parts = p.split(".")
        if any(".".join(parts[:i]) in joins for i in range(2, len(parts) + 1)):
            problems.append("sort path %s is outside the root outer join group" % p)
    # the query service: "Outer join status path DataSet.publication is not relevant to the query" (seen live
    # 20 Nov 2026) when no view or constraint path goes through a join's path
    used = (q.get("view") or "").split() + [c.get("path") or "" for c in cons]
    for j in sorted(joins):
        if not any(u == j or u.startswith(j + ".") for u in used):
            problems.append("join %s is not relevant to the query" % j)
    return problems


def test_rule_problems_catches_what_intermine_refuses():
    bad = ET.fromstring('<template name="All data"><query name="All data" model="genomic" view="DataSet.name" '
                        'sortOrder="DataSet.dataSource.name asc"><join path="DataSet.dataSource" style="OUTER"/>'
                        '<constraint path="DataSet" op="LOOKUP" value="x" editable="false"/></query></template>')
    got = rule_problems(bad)
    assert any("name" in p for p in got)
    assert "no editable constraint" in got and "non-editable LOOKUP" in got
    assert any("root outer join group" in p for p in got)
    assert "join DataSet.dataSource is not relevant to the query" in got


def test_every_template_the_build_applies_parses_and_follows_intermines_rules():
    for sql in SQLS:
        tpls = templates_in(sql.read_text())
        assert tpls, sql
        bad = {n: rule_problems(t) for n, t in tpls.items() if rule_problems(t)}
        assert not bad, (sql.name, bad)


DATA_SOURCES = "All_data_sources"
DATA_SOURCES_VIEW = ("DataSet.dataSource.name DataSet.name DataSet.version DataSet.description DataSet.url "
                     "DataSet.licence DataSet.publication.year "
                     "DataSet.publication.title DataSet.publication.pubMedId").split()


def _data_sources():
    return templates_in(METADATA_SQL.read_text())[DATA_SOURCES]


def test_all_data_sources_lists_every_data_set_with_its_source_version_licence_and_citation():
    tpl = _data_sources()
    q = tpl.find("query")
    assert tpl.get("title") == "All data sources"
    assert q.get("longDescription"), "the description BlueGenes shows under the title"
    assert q.get("view").split() == DATA_SOURCES_VIEW
    # The publication is an outer join, so a DataSet without a citation shows. The data source is an inner join:
    # a sort path must be in the root outer join group, and the table is sorted by data source, then data set
    # name. The one DataSet that had no DataSource ("modMine gene flanking regions") is no longer built (Gos
    # Micklem, 20 Nov 2026); the live test fails if a mine has a DataSet the template leaves out.
    assert q.get("sortOrder").split() == ["DataSet.dataSource.name", "asc", "DataSet.name", "asc"]
    assert outer_joins(q) == {"DataSet.publication"}
    assert "firstAuthor" not in q.get("view")   # Gos Micklem, 20 Nov 2026: year, title and PubMed id only
    # licence, version, description and url are attributes of DataSet itself: no join, a missing one is empty


def test_all_data_sources_has_one_harmless_editable_constraint():
    """InterMine needs one editable constraint; DataSet.name = * matches every data set (MainHelper turns = with a
    wildcard into a case-insensitive LIKE, as HumanMine's own Disease_Genes2 uses), and the user can type a name."""
    cons = list(_data_sources().find("query").iter("constraint"))
    assert len(cons) == 1
    c = cons[0]
    assert (c.get("path"), c.get("op"), c.get("value"), c.get("editable")) == ("DataSet.name", "=", "*", "true")
    assert c.get("description")


def test_all_data_sources_is_public_and_in_the_metadata_category():
    """BlueGenes' Templates page makes a category of every im:aspect:<Name> tag it finds on a template (no
    definition is needed mine-side); im:public makes the superuser's template everybody's."""
    tags = template_tags(METADATA_SQL.read_text())
    assert sorted(tags[DATA_SOURCES]) == ["im:aspect:Metadata", "im:public"]


def test_metadata_sql_can_run_again_and_takes_its_own_ids():
    """Unlike demo_public_templates.sql, running it again replaces the template rather than adding a copy (so it can
    be applied to a built mine), and its ids come from its own batch of the userprofile 'serial' sequence."""
    text = METADATA_SQL.read_text()
    assert "\\set ON_ERROR_STOP on" in text
    assert "SELECT nextval('serial') * 1000000 AS idbase \\gset" in text
    first_insert = text.index("INSERT INTO savedtemplatequery")
    for stmt in (f"DELETE FROM tag WHERE type = 'template' AND objectidentifier = '{DATA_SOURCES}'",
                 f"DELETE FROM savedtemplatequery WHERE templatequery LIKE '<template name=\"{DATA_SOURCES}\" %'"):
        assert stmt in text and text.index(stmt) < first_insert, stmt
    ids = re.findall(r"VALUES \(:idbase \+ (\d+),", text)
    assert len(ids) == len(set(ids)) == 3, ids
    assert "BEGIN;" in text and "COMMIT;" in text
