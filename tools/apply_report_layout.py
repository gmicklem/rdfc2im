#!/usr/bin/env python3
"""Give the demo mine HumanMine's Gene report-page layout [im-9n4.16].

BlueGenes lays a report page out from the mine's `layout.report` property (EDN, in the userprofile
database, served at /service/bluegenes-properties). Without it every tool sits under "Visualizations",
collapsed, and a collapsed tool never runs. HumanMine's own layout names categories (Genomics,
Proteins, Interactions, ...) holding classes/collections, tools and templates, in order.

This script takes that reference (curation/humanmine_bluegenes_properties.json, the raw
/service/bluegenes-properties response of www.humanmine.org), keeps the entries that this mine can
show, drops the rest with a printed reason, and sets the result on the mine:

  class     kept when Gene.<value> is a collection or reference in the mine's /service/model
  tool      kept when BlueGenes lists it (/api/tools/all), accepts the class, the classes it
            depends on are in the model, and the paths it queries (TOOL_QUERIES) resolve
  template  kept when the mine serves a template of that name (/service/templates)

A category left with no entry is dropped too. Run it after tools/apply_humanmine_templates.py, so the
templates exist, and again after a later build loads more data: the dropped list shrinks.

The write goes through the web service an admin would use, as the superuser: POST (key not yet set)
or PUT (key set) /service/bluegenes-properties with key and value, using a token from /service/login.
The value is read back and compared. Running it twice changes nothing the second time.

  tools/apply_report_layout.py curation/humanmine_bluegenes_properties.json --dry-run
  tools/apply_report_layout.py curation/humanmine_bluegenes_properties.json

Standard library only.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MINE = "http://localhost:18090/humanmine"
DEFAULT_BLUEGENES = "http://localhost:15001"
PROPERTY_KEY = "layout.report"
# Paths a tool queries without declaring them in its package.json "depends" (found by running it: the
# Cytoscape tool asks the mine for Gene.interactions.* and the mine answers 400 when the model lacks it).
# The Cytoscape list is the view of the Gene_Interactions query bundled in its dist/bundle.js
# (@intermine/cytoscape-intermine), constrained on Gene.interactions.details.type = physical
# [im-9n4.13]: every one must resolve, or a model with Interaction but not, say, InteractionDetail.dataSets
# would still answer 400.
TOOL_QUERIES = {"bluegenesToolCytoscape": [
    "Gene.interactions.participant2.symbol", "Gene.interactions.participant2.primaryIdentifier",
    "Gene.interactions.details.name", "Gene.interactions.details.role1", "Gene.interactions.details.role2",
    "Gene.interactions.details.type", "Gene.interactions.details.dataSets.name"]}
# The three ArrayExpress tools ask for AtlasExpression.tStatistic and .pValue (E-MTAB-62: differential
# expression), which only the arrayexpress-atlas source declares. With atlas-express (E-MTAB-513 FPKM) alone
# the model lacks them and the mine answers 400, so the tools are dropped until E-MTAB-62 is loaded [im-9n4.14].
_ARRAYEXPRESS = ["Gene.atlasExpression.condition", "Gene.atlasExpression.type", "Gene.atlasExpression.tStatistic",
                 "Gene.atlasExpression.pValue", "Gene.atlasExpression.expression"]
for _tool in ("BlueGenesDiseaseExpressionArrayexpressVisualizer", "bluegenesTissueExpressionArrayexpressVisualizer",
              "bluegenesExpressionBoxSwarmVisualizer"):
    TOOL_QUERIES[_tool] = _ARRAYEXPRESS
MAX_QUERY = 6000   # a PUT carries its value in the query string; longer than this goes DELETE + POST


# ----------------------------------------------------------------------------- EDN (the subset used)

class Kw(str):
    """An EDN keyword; the text holds the name without the colon."""


def edn_loads(text):
    value, pos = _read(text, _skip(text, 0))
    if _skip(text, pos) != len(text):
        raise ValueError("EDN: text after the first value at offset %d" % _skip(text, pos))
    return value


def _skip(s, i):
    while i < len(s) and (s[i].isspace() or s[i] == ","):
        i += 1
    return i


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _read(s, i):
    if i >= len(s):
        raise ValueError("EDN: unexpected end")
    c = s[i]
    if c in "{[":
        close = "}" if c == "{" else "]"
        items, i = [], _skip(s, i + 1)
        while i < len(s) and s[i] != close:
            item, i = _read(s, i)
            items.append(item)
            i = _skip(s, i)
        if i >= len(s):
            raise ValueError("EDN: missing %s" % close)
        if c == "[":
            return items, i + 1
        if len(items) % 2:
            raise ValueError("EDN: map with an odd number of forms")
        return dict(zip(items[0::2], items[1::2])), i + 1
    if c == '"':
        out, i = [], i + 1
        while i < len(s) and s[i] != '"':
            if s[i] == "\\":
                i += 1
                out.append(_ESC.get(s[i], s[i]))
            else:
                out.append(s[i])
            i += 1
        if i >= len(s):
            raise ValueError("EDN: unterminated string")
        return "".join(out), i + 1
    j = i
    while j < len(s) and not s[j].isspace() and s[j] not in ',{}[]"':
        j += 1
    tok = s[i:j]
    if not tok:
        raise ValueError("EDN: unexpected %r at offset %d" % (c, i))
    if tok[0] == ":":
        return Kw(tok[1:]), j
    if tok in ("nil", "true", "false"):
        return {"nil": None, "true": True, "false": False}[tok], j
    try:
        return int(tok), j
    except ValueError:
        return float(tok), j


def edn_dumps(v):
    """Clojure's pr-str layout: ', ' between map entries, ' ' between everything else."""
    if v is None:
        return "nil"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, Kw):
        return ":" + v
    if isinstance(v, str):
        esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return '"' + esc + '"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + " ".join(edn_dumps(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(edn_dumps(k) + " " + edn_dumps(x) for k, x in v.items()) + "}"
    raise TypeError("EDN: cannot write %r" % (v,))


# ----------------------------------------------------------------------------- model

def model_classes(model):
    """The class table of a /service/model?format=json response (or its "model" part)."""
    return model.get("model", model)["classes"]


def class_fields(classes, cname, _seen=None):
    """name -> 'attribute' | 'reference' | 'collection' for cname and everything it extends."""
    _seen = _seen or set()
    if cname in _seen or cname not in classes:
        return {}
    _seen.add(cname)
    c, out = classes[cname], {}
    for parent in c.get("extends", []):
        out.update(class_fields(classes, parent, _seen))
    for kind in ("attributes", "references", "collections"):
        for name in c.get(kind, {}):
            out[name] = kind[:-1] if kind != "attributes" else "attribute"
    return out


def resolve_path(classes, path, subclasses=None):
    """None when `path` (Class.field.field...) exists in the model, else why not.

    `subclasses` maps a path prefix to the class a constraint narrows it to, which a template may
    rely on to reach a field only the subclass has.
    """
    subclasses = subclasses or {}
    parts = path.split(".")
    cur = parts[0]
    if cur not in classes:
        return "class %s is not in the model" % cur
    for n, name in enumerate(parts[1:], 1):
        prefix = ".".join(parts[:n])
        options = [cur] + ([subclasses[prefix]] if prefix in subclasses else [])
        hit = next((h for h in (_field(classes, c, name) for c in options) if h), None)
        if not hit:
            return "%s has no field %s" % (" or ".join(options), name)
        kind, entry = hit
        if n < len(parts) - 1:
            if kind == "attribute":
                return "%s is an attribute, so .%s cannot follow it" % (".".join(parts[:n + 1]), parts[n + 1])
            cur = entry["referencedType"]
    return None


def _field(classes, cname, field, _seen=None):
    """(kind, entry) of a field of cname or of what it extends, else None."""
    _seen = _seen if _seen is not None else set()
    if cname in _seen or cname not in classes:
        return None
    _seen.add(cname)
    c = classes[cname]
    for kind in ("attributes", "references", "collections"):
        if field in c.get(kind, {}):
            return (kind[:-1] if kind != "attributes" else "attribute"), c[kind][field]
    for parent in c.get("extends", []):
        hit = _field(classes, parent, field, _seen)
        if hit:
            return hit
    return None


# ----------------------------------------------------------------------------- the filter

def _child_problem(cls, child, classes, tools, templates):
    kind, value = child.get("type"), child.get("value")
    if kind == "class":
        fields = class_fields(classes, cls)
        if value not in fields:
            return "%s.%s is not in the model" % (cls, value)
        if fields[value] == "attribute":
            return "%s.%s is an attribute, not a collection or reference" % (cls, value)
        return None
    if kind == "tool":
        tool = tools.get(value)
        if tool is None:
            return "tool not installed in BlueGenes"
        config = tool.get("config", {})
        if config.get("classes") and cls not in config["classes"]:
            return "tool does not accept %s" % cls
        missing = [d for d in (config.get("depends") or []) if d not in classes]
        if missing:
            return "tool depends on %s, not in the model" % ", ".join(missing)
        for path in TOOL_QUERIES.get(value, []):
            if resolve_path(classes, path):
                return "tool queries %s, not in the model" % path
        return None
    if kind == "template":
        return None if value in templates else "template not in the mine"
    return "unknown entry type %r" % (kind,)


def filter_layout(layout, classes, tools, templates):
    """(kept layout, dropped rows). Order of categories and of entries is preserved.

    `tools` maps a tool's cljs name to its config; `templates` is a set of template names.
    A dropped row is (class, category, label, type, value, reason).
    """
    kept, dropped = {}, []
    for cls, categories in layout.items():
        if cls not in classes:
            dropped.append((cls, "", "", "class", cls, "class not in the model"))
            continue
        out = []
        for cat in categories:
            children = []
            for child in cat.get("children", []):
                why = _child_problem(cls, child, classes, tools, templates)
                if why:
                    dropped.append((cls, cat.get("category", ""), child.get("label", ""),
                                    child.get("type", ""), child.get("value", ""), why))
                else:
                    children.append(child)
            if children:
                new = dict(cat)
                new[Kw("children")] = children
                out.append(new)
            else:
                dropped.append((cls, cat.get("category", ""), "", "category", "", "no entry left"))
        if out:
            kept[cls] = out
    return kept, dropped


def format_dropped(rows):
    if not rows:
        return "nothing dropped"
    head = ("class", "category", "type", "value", "reason")
    body = [(r[0], r[1], r[3], r[4], r[5]) for r in rows]
    widths = [max(len(str(x[i])) for x in [head] + body) for i in range(len(head))]
    fmt = "  ".join("%%-%ds" % w for w in widths)
    return "\n".join([fmt % head, fmt % tuple("-" * w for w in widths)] + [fmt % tuple(map(str, b)) for b in body])


# ----------------------------------------------------------------------------- web service

def http(method, url, data=None, headers=None, timeout=60):
    """(status, body text); HTTP errors come back as a status, not an exception."""
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data)
    if isinstance(data, str):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get_json(url, headers=None):
    status, body = http("GET", url, headers=headers)
    if status != 200:
        raise RuntimeError("GET %s: HTTP %s: %s" % (url, status, body[:200]))
    return json.loads(body)


def wait_for_mine(mine, seconds):
    """Wait up to `seconds` for /service/version to answer 200 (a rebuild or restart is in progress)."""
    end = time.time() + seconds
    while True:
        try:
            if http("GET", mine + "/service/version", timeout=10)[0] == 200:
                return
        except OSError:
            pass
        if time.time() >= end:
            raise RuntimeError("%s did not answer /service/version within %ss" % (mine, seconds))
        time.sleep(5)


def login(mine, user, password):
    status, body = http("POST", mine + "/service/login", {"username": user, "password": password})
    if status != 200:
        raise RuntimeError("login as %s: HTTP %s: %s" % (user, status, body[:200]))
    return json.loads(body)["output"]["token"]


def mine_templates(mine, token=None):
    headers = {"Authorization": "Token " + token} if token else {}
    return set(get_json(mine + "/service/templates?format=json", headers)["templates"])


def get_property(mine, key=PROPERTY_KEY):
    props = get_json(mine + "/service/bluegenes-properties")["bluegenes-properties"]
    return props.get(key)


def set_property(mine, token, key, value):
    """POST when the key is new, PUT when it is set (DELETE then POST if the query would be long)."""
    auth = {"Authorization": "Token " + token}
    url = mine + "/service/bluegenes-properties"
    if get_property(mine, key) is None:
        status, body = http("POST", url, {"key": key, "value": value}, auth)
    else:
        query = urllib.parse.urlencode({"key": key, "value": value})
        if len(query) <= MAX_QUERY:
            status, body = http("PUT", url + "?" + query, headers=auth)
        else:
            status, body = http("DELETE", url + "?" + urllib.parse.urlencode({"key": key}), headers=auth)
            if status == 200:
                status, body = http("POST", url, {"key": key, "value": value}, auth)
    if status != 200:
        raise RuntimeError("setting %s: HTTP %s: %s" % (key, status, body[:300]))


# ----------------------------------------------------------------------------- main

def load_reference(path, key=PROPERTY_KEY):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return edn_loads(data["bluegenes-properties"][key])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reference", help="HumanMine's /service/bluegenes-properties response (JSON file)")
    ap.add_argument("--mine", default=DEFAULT_MINE, help="mine base URL (default %(default)s)")
    ap.add_argument("--bluegenes", default=DEFAULT_BLUEGENES, help="BlueGenes base URL (default %(default)s)")
    ap.add_argument("--user", default="superuser@intermine.org", help="superuser (default %(default)s, the demo's)")
    ap.add_argument("--password", default="intermine", help="its password (default the demo's)")
    ap.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait this long for the mine to answer")
    ap.add_argument("--dry-run", action="store_true", help="print the layout and what would change; write nothing")
    args = ap.parse_args(argv)
    mine = args.mine.rstrip("/")

    if args.wait:
        wait_for_mine(mine, args.wait)
    classes = model_classes(get_json(mine + "/service/model?format=json"))
    tools = {t["names"]["cljs"]: t for t in get_json(args.bluegenes.rstrip("/") + "/api/tools/all")["tools"]}
    templates = mine_templates(mine)
    layout, dropped = filter_layout(load_reference(args.reference), classes, tools, templates)
    value = edn_dumps(layout)

    print("layout.report for the demo mine:")
    for cls, cats in layout.items():
        for cat in cats:
            print("  %s / %s: %s" % (cls, cat["category"], ", ".join(c["value"] for c in cat["children"])))
    print("\ndropped (%d):" % len(dropped))
    print(format_dropped(dropped))

    current = get_property(mine)
    if current == value:
        print("\nunchanged: the mine already holds this layout")
        return 0
    if args.dry_run:
        print("\n--dry-run: would %s %s (%d characters)" % ("set" if current is None else "replace", PROPERTY_KEY, len(value)))
        return 0
    set_property(mine, login(mine, args.user, args.password), PROPERTY_KEY, value)
    if get_property(mine) != value:
        raise RuntimeError("read back a different %s from %s" % (PROPERTY_KEY, mine))
    print("\nset %s on %s and read it back (%d characters)" % (PROPERTY_KEY, mine, len(value)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, KeyError, ValueError) as e:
        print("apply_report_layout: %s" % e, file=sys.stderr)
        sys.exit(1)
