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
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "curation" / "demo_public_templates.sql"
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
    bad = sorted({(n, p) for n, p in template_paths(SQL.read_text()) if not resolves(classes, p)})
    assert not bad, f"template paths missing from the model {f}: {bad}"
