"""tools/apply_report_layout.py and tools/apply_humanmine_templates.py [im-9n4.16]: the filtering, on
small fixtures, and the committed HumanMine reference files; no mine is contacted."""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import apply_humanmine_templates as aht  # noqa: E402
import apply_report_layout as arl  # noqa: E402

MODEL = {"model": {"classes": {
    "BioEntity": {"attributes": {"primaryIdentifier": {}}},
    "Gene": {"extends": ["BioEntity"], "attributes": {"symbol": {}},
             "references": {"organism": {"referencedType": "Organism"}},
             "collections": {"proteins": {"referencedType": "Protein"}, "exons": {"referencedType": "Exon"}}},
    "Protein": {"extends": ["BioEntity"], "attributes": {"primaryAccession": {}}},
    "Exon": {"extends": ["BioEntity"]},
    "Organism": {"attributes": {"name": {}}},
    "Allele": {"extends": ["BioEntity"], "attributes": {"clinicalSignificance": {}}},
    "Gene2": {"extends": ["Gene"], "collections": {"alleles": {"referencedType": "Allele"}}},
}}}
CLASSES = arl.model_classes(MODEL)
TOOLS = {
    "protvis": {"config": {"classes": ["Gene", "Protein"]}},
    "needsatlas": {"config": {"classes": ["Gene"], "depends": ["AtlasExpression"]}},
    "proteinonly": {"config": {"classes": ["Protein"]}},
}


def entry(value, kind, label=None):
    return {arl.Kw("label"): label or value, arl.Kw("value"): value, arl.Kw("type"): kind, arl.Kw("collapse"): None}


def category(name, *children):
    return {arl.Kw("category"): name, arl.Kw("children"): list(children)}


def values(layout):
    return [[c["value"] for c in cat["children"]] for cat in layout["Gene"]]


def test_edn_round_trips_the_humanmine_reference_byte_for_byte():
    import json
    with open(os.path.join(ROOT, "curation", "humanmine_bluegenes_properties.json"), encoding="utf-8") as f:
        text = json.load(f)["bluegenes-properties"]["layout.report"]
    assert arl.edn_dumps(arl.edn_loads(text)) == text


def test_edn_reads_and_writes_strings_with_escapes_and_nil():
    v = arl.edn_loads('{"a" [{:k "x\\"y", :n nil, :t true}]}')
    assert v == {"a": [{"k": 'x"y', "n": None, "t": True}]}
    assert isinstance(next(iter(v["a"][0])), arl.Kw)
    assert arl.edn_dumps(v) == '{"a" [{:k "x\\"y", :n nil, :t true}]}'


def test_a_resolvable_path_is_kept_and_a_missing_class_or_field_is_dropped():
    layout = {"Gene": [category("P", entry("proteins", "class"), entry("nothere", "class"),
                                entry("symbol", "class"))]}
    kept, dropped = arl.filter_layout(layout, CLASSES, TOOLS, set())
    assert values(kept) == [["proteins"]]
    assert {r[4]: r[5] for r in dropped} == {
        "nothere": "Gene.nothere is not in the model",
        "symbol": "Gene.symbol is an attribute, not a collection or reference"}


def test_a_layout_class_missing_from_the_model_is_dropped_whole():
    kept, dropped = arl.filter_layout({"Gene": [category("P", entry("exons", "class"))],
                                       "Plant": [category("Q", entry("x", "class"))]}, CLASSES, TOOLS, set())
    assert list(kept) == ["Gene"]
    assert dropped[0][0] == "Plant" and "not in the model" in dropped[0][5]


def test_an_uninstalled_tool_or_one_with_a_missing_dependency_or_wrong_class_is_dropped():
    layout = {"Gene": [category("T", entry("protvis", "tool"), entry("gone", "tool"),
                                entry("needsatlas", "tool"), entry("proteinonly", "tool"))]}
    kept, dropped = arl.filter_layout(layout, CLASSES, TOOLS, set())
    assert values(kept) == [["protvis"]]
    why = {r[4]: r[5] for r in dropped}
    assert why["gone"] == "tool not installed in BlueGenes"
    assert "AtlasExpression" in why["needsatlas"]
    assert why["proteinonly"] == "tool does not accept Gene"


def test_a_template_the_mine_lacks_is_dropped():
    layout = {"Gene": [category("T", entry("Have", "template"), entry("Lack", "template"))]}
    kept, dropped = arl.filter_layout(layout, CLASSES, TOOLS, {"Have"})
    assert values(kept) == [["Have"]]
    assert [(r[4], r[5]) for r in dropped] == [("Lack", "template not in the mine")]


def test_order_of_categories_and_entries_is_preserved_and_an_emptied_category_goes():
    layout = {"Gene": [
        category("One", entry("exons", "class"), entry("T1", "template"), entry("protvis", "tool")),
        category("Empty", entry("nothere", "class")),
        category("Two", entry("T2", "template"), entry("proteins", "class")),
    ]}
    kept, dropped = arl.filter_layout(layout, CLASSES, TOOLS, {"T1", "T2"})
    assert [c["category"] for c in kept["Gene"]] == ["One", "Two"]
    assert values(kept) == [["exons", "T1", "protvis"], ["T2", "proteins"]]
    assert ("Gene", "Empty", "", "category", "", "no entry left") in dropped
    # untouched keys survive: the label and :collapse nil of an entry
    assert kept["Gene"][0]["children"][0]["collapse"] is None


def test_the_filtered_layout_is_the_same_text_every_time():
    layout = {"Gene": [category("T", entry("exons", "class"), entry("T1", "template"))]}
    a = arl.edn_dumps(arl.filter_layout(layout, CLASSES, TOOLS, {"T1"})[0])
    b = arl.edn_dumps(arl.filter_layout(arl.edn_loads(a), CLASSES, TOOLS, {"T1"})[0])
    assert a == b


# ---------------------------------------------------------------------------- templates

def tpl(view, constraints="", sort="", extra=""):
    return ET.fromstring('<template name="T"><query name="T" model="genomic" view="%s" sortOrder="%s">%s%s'
                         "</query></template>" % (view, sort, constraints, extra))


def test_template_paths_resolve_through_references_and_inherited_fields():
    t = tpl("Gene.primaryIdentifier Gene.organism.name Gene.proteins.primaryAccession",
            '<constraint path="Gene" op="LOOKUP" value="x"/>', "Gene.symbol asc")
    assert aht.template_problem(t, CLASSES) is None


def test_template_with_a_missing_field_or_class_reports_the_first_path_and_the_count():
    t = tpl("Gene.symbol Gene.interactions.type Gene.homologues.id")
    assert aht.template_problem(t, CLASSES) == "Gene.interactions.type: Gene has no field interactions (+1 more)"
    assert aht.template_problem(tpl("Plant.name"), CLASSES) == "Plant.name: class Plant is not in the model"


def test_template_checks_constraint_paths_loop_paths_and_sort_order_too():
    assert "Gene.nothere" in aht.template_problem(tpl("Gene.symbol", '<constraint path="Gene.nothere" op="=" value="1"/>'), CLASSES)
    assert "Gene.zz" in aht.template_problem(
        tpl("Gene.symbol", '<constraint path="Gene.organism" op="!=" loopPath="Gene.zz"/>'), CLASSES)
    assert "Gene.zz" in aht.template_problem(tpl("Gene.symbol", sort="Gene.zz desc"), CLASSES)


def test_a_subclass_constraint_makes_the_subclass_fields_reachable():
    assert aht.template_problem(tpl("Gene.alleles.clinicalSignificance"), CLASSES) is not None
    narrowed = tpl("Gene.alleles.clinicalSignificance", '<constraint path="Gene" type="Gene2"/>')
    assert aht.template_problem(narrowed, CLASSES) is None
    isa = tpl("Gene.alleles.clinicalSignificance", '<constraint path="Gene" op="ISA" value="Gene2"/>')
    assert aht.template_problem(isa, CLASSES) is None


def test_a_path_cannot_continue_past_an_attribute():
    assert "attribute" in aht.template_problem(tpl("Gene.symbol.length"), CLASSES)


def test_classify_separates_kept_present_and_dropped():
    xml = ("<template-queries>"
           '<template name="Ok"><query model="genomic" view="Gene.symbol"/></template>'
           '<template name="Have"><query model="genomic" view="Gene.symbol"/></template>'
           '<template name="Bad"><query model="genomic" view="Gene.nothere"/></template>'
           "</template-queries>")
    keep, present, dropped = aht.classify(aht.split_templates(xml), CLASSES, {"Have"})
    assert [n for n, _ in keep] == ["Ok"] and present == ["Have"]
    assert dropped == [("Bad", "Gene.nothere: Gene has no field nothere")]


def test_the_committed_humanmine_templates_parse_and_every_name_is_unique():
    with open(os.path.join(ROOT, "curation", "humanmine_templates.xml"), encoding="utf-8") as f:
        templates = aht.split_templates(f.read())
    names = [n for n, _ in templates]
    assert len(names) > 50 and len(set(names)) == len(names)
    assert {"Gene_GO", "Gene_Orth2"} & set(names) == {"Gene_GO"}   # Gene_Orth2 is not public on humanmine.org
