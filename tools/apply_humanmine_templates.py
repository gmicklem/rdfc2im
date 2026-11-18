#!/usr/bin/env python3
"""Load HumanMine's public templates that this mine's model can run [im-9n4.16, TA.6].

Reads HumanMine's templates (curation/humanmine_templates.xml, the raw /service/templates?format=xml
response of www.humanmine.org: its production templates live in its userprofile database, not in
the humanmine repository, whose default-template-queries.xml holds only three), and keeps a template
when every path it names resolves in the mine's /service/model: the view, the sort order, each
constraint path and loop path, joins, path descriptions, and the classes of subclass constraints.
The rest are dropped with the first path that fails.

Each kept template is uploaded to the superuser's profile (POST /service/templates, XML body, token
from /service/login) and tagged im:public (POST /service/template/tags). One request per template,
because the service rejects a whole upload when one template in it is invalid; the server's own
verdict is reported as a drop too.

A template whose name the mine already serves is left alone and reported as present: that covers
the demo's nine (curation/demo_public_templates.sql and the three stock ones: BlueGenes' Cypress specs
and mines.toml count on them by name, and the SQL repoints two defaults to Homo sapiens) and a
second run of this script, which therefore changes nothing.

  tools/apply_humanmine_templates.py curation/humanmine_templates.xml --dry-run
  tools/apply_humanmine_templates.py curation/humanmine_templates.xml

Standard library only.
"""
import argparse
import sys
import xml.etree.ElementTree as ET

import apply_report_layout as arl


def template_paths(template):
    """(paths to resolve, subclass narrowing {path: class}, classes named) for a <template> element."""
    paths, narrow, classes = [], {}, []
    query = template.find("query")
    if query is None:
        return paths, narrow, classes
    paths += query.get("view", "").split()
    order = query.get("sortOrder", "").split()
    paths += [t for t in order if t.lower() not in ("asc", "desc")]
    for con in query.iter("constraint"):
        path, op = con.get("path"), con.get("op", "")
        if path:
            paths.append(path)
        if con.get("loopPath"):
            paths.append(con.get("loopPath"))
        if con.get("type"):
            narrow[path] = con.get("type")
            classes.append(con.get("type"))
        if op in ("ISA", "ISNT") and con.get("value"):
            narrow[path] = con.get("value")
            classes.append(con.get("value"))
    for join in query.iter("join"):
        if join.get("path"):
            paths.append(join.get("path"))
    for desc in query.iter("pathDescription"):
        if desc.get("pathString"):
            paths.append(desc.get("pathString"))
    return paths, narrow, classes


def template_problem(template, classes):
    """None when the model holds everything the template names, else the first reason (and how many)."""
    paths, narrow, named = template_paths(template)
    problems = []
    for c in named:
        if c not in classes:
            problems.append("class %s is not in the model" % c)
    for p in paths:
        why = arl.resolve_path(classes, p, narrow)
        if why:
            problems.append("%s: %s" % (p, why))
    if not problems:
        return None
    seen = list(dict.fromkeys(problems))
    return seen[0] + (" (+%d more)" % (len(seen) - 1) if len(seen) > 1 else "")


def split_templates(xml_text):
    """[(name, <template> element)] from a <template-queries> document, in file order."""
    root = ET.fromstring(xml_text)
    return [(t.get("name"), t) for t in root.iter("template")]


def classify(templates, classes, existing):
    """(keep [(name, element)], present [name], dropped [(name, reason)]): the model and the names already served."""
    keep, present, dropped = [], [], []
    for name, tpl in templates:
        if name in existing:
            present.append(name)
            continue
        why = template_problem(tpl, classes)
        if why:
            dropped.append((name, why))
        else:
            keep.append((name, tpl))
    return keep, present, dropped


def upload(mine, token, name, tpl):
    """Upload one template and tag it im:public; None on success, else the server's reason."""
    auth = {"Authorization": "Token " + token}
    body = "<template-queries>%s</template-queries>" % ET.tostring(tpl, encoding="unicode")
    status, text = arl.http("POST", mine + "/service/templates", body.encode("utf-8"),
                            dict(auth, **{"Content-Type": "application/xml"}))
    if status != 200:
        return "server refused it: HTTP %s %s" % (status, " ".join(text.split())[:160])
    status, text = arl.http("POST", mine + "/service/template/tags", {"name": name, "tags": "im:public"}, auth)
    if status != 200:
        return "uploaded but tagging failed: HTTP %s %s" % (status, " ".join(text.split())[:160])
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("templates", help="HumanMine's /service/templates?format=xml response (file)")
    ap.add_argument("--mine", default=arl.DEFAULT_MINE, help="mine base URL (default %(default)s)")
    ap.add_argument("--user", default="superuser@intermine.org", help="superuser (default %(default)s, the demo's)")
    ap.add_argument("--password", default="intermine", help="its password (default the demo's)")
    ap.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait this long for the mine to answer")
    ap.add_argument("--dry-run", action="store_true", help="print kept and dropped; write nothing")
    args = ap.parse_args(argv)
    mine = args.mine.rstrip("/")

    if args.wait:
        arl.wait_for_mine(mine, args.wait)
    with open(args.templates, encoding="utf-8") as f:
        templates = split_templates(f.read())
    classes = arl.model_classes(arl.get_json(mine + "/service/model?format=json"))
    token = None if args.dry_run else arl.login(mine, args.user, args.password)
    existing = arl.mine_templates(mine, token)
    keep, present, dropped = classify(templates, classes, existing)

    failed = []
    if not args.dry_run:
        for name, tpl in keep:
            why = upload(mine, token, name, tpl)
            if why:
                failed.append((name, why))
        dropped += failed

    print("%s: %d templates in the reference, %d %s, %d already in the mine (left alone), %d dropped"
          % (args.templates, len(templates), len(keep) - len(failed), "to load" if args.dry_run else "loaded",
             len(present), len(dropped)))
    for name in present:
        print("  have  %s" % name)
    for name, _ in keep:
        if name not in dict(failed):
            print("  keep  %s" % name)
    for name, why in dropped:
        print("  drop  %-36s %s" % (name, why))
    if not args.dry_run:
        served = arl.mine_templates(mine)
        absent = [n for n, _ in keep if n not in dict(failed) and n not in served]
        if absent:
            raise RuntimeError("uploaded but not served as public templates: %s" % ", ".join(absent))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, KeyError, ValueError, ET.ParseError) as e:
        print("apply_humanmine_templates: %s" % e, file=sys.stderr)
        sys.exit(1)
