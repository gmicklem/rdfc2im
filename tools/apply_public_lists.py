#!/usr/bin/env python3
"""Put HumanMine's public lists on a hybrid mine [im-9n4.22, T2.3].

Makes the Genomics England PanelApp lists (`PL_GenomicsEngland_GenePanel:<Panel_name>`, from the PanelApp cache, see
tools/panelapp_lists.py) and the 13 other public lists HumanMine had (curation/public_lists/) public lists of a mine,
through the web service, as the superuser:

  1. ARCHIVE FIRST. The mine's current public lists (names, descriptions, tags, types, sizes, member identifiers) are
     exported to <archive-repo>/<mine-label>-public-lists/<YYYY-MM-DD>[-N]/ with the T2.1 script
     (historic_artefacts/scripts/export_humanmine_public_lists.py, imported, not copied). A directory is never
     overwritten: a second run on the same day gets -2, and so on. A mine with no public list gets an empty dated
     record. If the archive step fails nothing is uploaded or removed.
  2. Resolve every panel's Green genes in the mine (HGNC id, then Ensembl id, then symbol, as panelapp_lists.py
     resolve does) and upload the mine's own Entrez primaryIdentifier, never symbols; resolve the legacy lists' members.
  3. POST /service/lists?name=&type=&description=&tags=a;b&extraValue=H. sapiens&replaceExisting=true (text/plain, one
     identifier per line), tagged `Genomics England gene panel` and `im:public` (the legacy lists keep their own tags).
     replaceExisting deletes a list of that name first, so a re-run replaces and never duplicates.
  4. Public PL_ lists tagged `Genomics England gene panel` that this run no longer produces (a retired or renamed
     panel, or a narrower --select) are deleted and reported. Other lists are never touched.
  5. Every list is read back (GET /service/lists, anonymous: name, type, size, tags, description) and a table printed.
  6. A JSON run report: lists uploaded and sizes, unresolved members, lists skipped and why, lists removed, archive path.

Names: the 17 panels renamed in PanelApp since 2021 keep their 2021 list name and the current panel name goes into the
description (KEEP_2021_NAMES_DEFAULT; --current-names flips it). --select all (every panel) or 100k (HumanMine's 2021
scope).

A mine whose host is public (www.humanmine.org, any *.org ...) is refused unless --i-know-this-is-production is given.
--dry-run archives nothing and writes nothing to the mine; it still resolves (read-only) and prints what would happen.

Standard library only.
"""
import argparse
import csv
import datetime
import importlib.util
import ipaddress
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apply_report_layout as AR  # noqa: E402  (the web-service helpers: http, login, wait_for_mine, model_classes)
import panelapp_lists as P  # noqa: E402

DEFAULT_MINE = AR.DEFAULT_MINE
KEEP_2021_NAMES_DEFAULT = True          # the one switch: the 17 renamed panels keep their 2021 list names
PUBLIC_TAG = "im:public"
PANEL_TAG = P.LIST_TAGS[0]              # "Genomics England gene panel"
NAME_PREFIX = "PL_"
ORGANISM = "H. sapiens"
EXPORT_SCRIPT_NAME = "export_humanmine_public_lists.py"
UPLOAD_TIMEOUT = 900
REPORT_CAP = 50                         # unresolved members listed per list in the report


class ApplyError(Exception):
    pass


class ArchiveError(ApplyError):
    pass


class GuardError(ApplyError):
    pass


# ---------------------------------------------------------------------------------------------- the guard

def is_local_host(host):
    """True for hosts that cannot be a public mine: loopback, private addresses, single-label names (a compose
    service), localhost, host.docker.internal and the reserved local suffixes."""
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    if h in ("localhost", "host.docker.internal", "gateway.docker.internal") or h.endswith(
            (".localhost", ".local", ".internal", ".test", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return "." not in h


def guard_mine(url, production_ok=False):
    """Refuse a public mine unless --i-know-this-is-production was given. Returns the normalised URL."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise GuardError(f"--mine {url!r} is not an http(s) URL")
    if not is_local_host(u.hostname) and not production_ok:
        raise GuardError(
            f"refusing to write to {u.hostname}: it is not a local or private host. This tool replaces the public lists "
            "of a mine; against a public mine pass --i-know-this-is-production (and only for a production rebuild).")
    return url.rstrip("/")


# ---------------------------------------------------------------------------------------------- the web service

class WebService:
    """The mine's web service as this tool uses it. Tests replace the whole object with a fake."""

    def __init__(self, mine, user, password, http=AR.http):
        self.mine, self.user, self.password, self.http = mine.rstrip("/"), user, password, http
        self._token = None
        self._ids_http = P.MineHttp()

    def wait(self, seconds):
        if seconds:
            AR.wait_for_mine(self.mine, seconds)

    def version(self):
        status, body = self.http("GET", self.mine + "/service/version", timeout=30)
        return body.strip() if status == 200 else "unknown"

    def login(self):
        self._token = AR.login(self.mine, self.user, self.password)
        return self._token

    def _auth(self, token):
        return {"Authorization": "Token " + token} if token else {}

    def lists(self, token=None):
        """The lists GET /service/lists?format=json shows to an anonymous reader (the public ones) or, with a token,
        to that user."""
        status, body = self.http("GET", self.mine + "/service/lists?format=json", headers=self._auth(token), timeout=300)
        if status != 200:
            raise ApplyError(f"GET /service/lists: HTTP {status}: {body[:200]}")
        return json.loads(body)["lists"]

    def model_classes(self):
        return AR.model_classes(AR.get_json(self.mine + "/service/model?format=json"))

    def upload(self, name, type_, description, tags, identifiers, extra=ORGANISM):
        query = urllib.parse.urlencode({"name": name, "type": type_, "description": description,
                                        "tags": ";".join(tags), "extraValue": extra, "replaceExisting": "true"})
        headers = dict(self._auth(self._token), **{"Content-Type": "text/plain; charset=utf-8"})
        status, body = self.http("POST", self.mine + "/service/lists?" + query, "\n".join(identifiers) + "\n",
                                 headers, timeout=UPLOAD_TIMEOUT)
        if status != 200:
            raise ApplyError(f"upload of {name}: HTTP {status}: {body[:300]}")
        out = json.loads(body)
        if not out.get("wasSuccessful"):
            raise ApplyError(f"upload of {name}: {out.get('error')}")
        return {"size": out.get("listSize"), "unmatched": out.get("unmatchedIdentifiers") or []}

    def delete(self, name):
        status, body = self.http("DELETE", self.mine + "/service/lists?" + urllib.parse.urlencode({"name": name}),
                                 headers=self._auth(self._token), timeout=120)
        if status != 200:
            raise ApplyError(f"delete of {name}: HTTP {status}: {body[:300]}")

    def resolve(self, type_, values):
        """{value (lower case): {"status": unique|ambiguous|unresolved, "genes": [...], "categories": [...],
        "summaries": {...}}} by the mine's /service/ids (read-only jobs of P.JOB_BATCH identifiers)."""
        values = sorted(set(values))
        out = {}
        for i in range(0, len(values), P.JOB_BATCH):
            batch = values[i:i + P.JOB_BATCH]
            results = P.run_ids_job(self.mine, batch, self._ids_http, ORGANISM, type_=type_)
            found, _ = P.parse_ids_results(results)
            for v in batch:
                e = found.get(v.lower())
                out[v.lower()] = (dict(e, status="unique" if len(e["genes"]) == 1 else "ambiguous") if e else
                                  {"status": "unresolved", "genes": [], "categories": [], "summaries": {}})
        return out


# ---------------------------------------------------------------------------------------------- definitions

def locate_panelapp(cache):
    """The directory with META.json and panels/: a rawcache group directory (data/ inside it) or the data itself."""
    for cand in (os.path.join(cache, "data"), cache):
        if os.path.isfile(os.path.join(cand, "META.json")):
            return cand
    raise ApplyError(f"--panelapp-cache {cache}: no META.json (neither in it nor in its data/)")


def verify_cache(cache, log):
    """Check the cache group's md5s when it is one (MD5SUMS there) and rawcache can be imported."""
    if not os.path.isfile(os.path.join(cache, "MD5SUMS")):
        log(f"panelapp cache {cache}: no MD5SUMS, not verified")
        return
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from rdfc2im import rawcache
    try:
        rawcache.verify(os.path.basename(os.path.abspath(cache)), os.path.dirname(os.path.abspath(cache)))
    except rawcache.CacheError as e:
        raise ApplyError(f"the PanelApp cache does not verify: {e}")
    log(f"panelapp cache {cache}: md5s verified")


def panel_definitions(in_dir, select, keep_2021_names):
    """(meta, definitions of the selected panels' lists). A definition is panelapp_lists.build_list's, plus the
    current panel name in the description when the list keeps a 2021 name."""
    meta, panels = P.read_panels(in_dir)
    defs = []
    for p in select_panels(panels, select):
        d = P.build_list(p, meta["fetch_date"], keep_2021_names)
        d["kind"] = "panelapp"
        if keep_2021_names and p["id"] in P.RENAMED_SINCE_2021:
            d["description"] += (f" PanelApp now names this panel \"{p['name']}\"; the list keeps the name it had in 2021.")
        defs.append(d)
    names = [d["name"] for d in defs]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ApplyError("two panels would get the same list name: " + ", ".join(dup))
    return meta, defs


def select_panels(panels, select):
    return P.select_panels(panels, select)


def legacy_definitions(legacy_dir):
    """The legacy lists of a directory laid out like an archive: lists.json (the /service/lists answer),
    members/INDEX.tsv (file, list name, rows) and members/<file>.tsv (header row, identifier in the first column)."""
    with open(os.path.join(legacy_dir, "lists.json"), encoding="utf-8") as fh:
        lists = json.load(fh)["lists"]
    files = {}
    with open(os.path.join(legacy_dir, "members", "INDEX.tsv"), encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            files[row["list_name"]] = row["file"]
    defs = []
    for l in lists:
        fn = files.get(l["name"])
        if not fn:
            raise ApplyError(f"{legacy_dir}: no member file for the list {l['name']!r} in members/INDEX.tsv")
        ids = []
        with open(os.path.join(legacy_dir, "members", fn), encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                v = line.rstrip("\n").split("\t")[0].strip().strip('"')
                if v and v not in ids:
                    ids.append(v)
        defs.append({"kind": "legacy", "name": l["name"], "type": l["type"], "description": l.get("description") or "",
                     "tags": list(l.get("tags") or []), "members": ids, "original_size": l.get("size", len(ids))})
    return defs


# ---------------------------------------------------------------------------------------------- the archive

def load_exporter(script):
    """Import the T2.1 export script as a module and return a callable (service_url, out_dir)."""
    if not script or not os.path.isfile(script):
        raise ArchiveError(f"the archive export script {script!r} does not exist (--export-script, or "
                           f"<archive-repo>/scripts/{EXPORT_SCRIPT_NAME})")
    spec = importlib.util.spec_from_file_location("export_humanmine_public_lists", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def export(service_url, out_dir):
        mod.log_lines, mod.refusals = [], 0
        if is_local_host(urllib.parse.urlparse(service_url).hostname):
            mod.PAUSE = 0                       # the 0.3 s pause is courtesy to a public server
        mod.main(service_url, out_dir)
    return export


def new_archive_dir(archive_repo, label, today):
    """Create <archive_repo>/<label>-public-lists/<today>[-N] and return it; an existing directory is never reused."""
    base = os.path.join(archive_repo, f"{label}-public-lists")
    os.makedirs(base, exist_ok=True)
    n = 1
    while True:
        path = os.path.join(base, today if n == 1 else f"{today}-{n}")
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            n += 1


def archive_current_lists(mine, archive_repo, label, exporter, today, log):
    """Export the mine's public lists to a new dated directory. Raises ArchiveError (after leaving FAILED.txt in the
    directory, which a later run never reuses) if anything goes wrong or the export does not add up."""
    path = new_archive_dir(archive_repo, label, today)
    t0 = time.time()
    try:
        exporter(mine + "/service", path)
        with open(os.path.join(path, "lists.json"), encoding="utf-8") as fh:
            lists = json.load(fh)["lists"]
        with open(os.path.join(path, "members", "INDEX.tsv"), encoding="utf-8") as fh:
            rows = max(0, sum(1 for _ in fh) - 1)
        if rows != len(lists):
            raise ArchiveError(f"{len(lists)} lists but {rows} member files")
        log_path = os.path.join(path, "export.log")
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8") as fh:
                bad = [l.strip() for l in fh if l.startswith("MISMATCH")]
            if bad:
                raise ArchiveError("the export does not match the list sizes: " + "; ".join(bad[:3]))
    except SystemExit as e:
        _failed(path, f"the export script exited with {e.code}")
        raise ArchiveError(f"archive step failed ({path}): the export script stopped ({e.code})")
    except Exception as e:                                  # noqa: BLE001  any failure stops the run
        _failed(path, f"{type(e).__name__}: {e}")
        raise ArchiveError(f"archive step failed ({path}): {e}")
    info = {"mine": mine, "label": label, "date": today, "lists": len(lists), "seconds": round(time.time() - t0, 1),
            "written_by": "tools/apply_public_lists.py", "export_script": EXPORT_SCRIPT_NAME}
    P.dump_json(os.path.join(path, "archive.json"), info)
    log(f"archived {len(lists)} public lists of {mine} to {path}")
    return {"path": path, "lists": len(lists), "seconds": info["seconds"]}


def _failed(path, why):
    try:
        with open(os.path.join(path, "FAILED.txt"), "w", encoding="utf-8") as fh:
            fh.write(why + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------- resolution

def gene_key(rec):
    return rec["hgnc_id"] or ("symbol:" + str(rec["symbol"]))


def resolve_panel_genes(service, defs, log):
    """{gene key: Entrez primaryIdentifier} for every Green gene of every list definition, by the chain HGNC id, Ensembl
    GRCh38 id, symbol (the first that gives exactly one gene, as panelapp_lists.py resolve); the keys left over."""
    pending = {}
    for d in defs:
        for rec in d["genes"]:
            pending.setdefault(gene_key(rec), rec)
    result = {}
    for kind in P.ID_ORDER:
        want = {k: dict(P.candidate_identifiers(r)).get(kind) for k, r in pending.items()}
        values = {v for v in want.values() if v}
        if not values:
            continue
        outcome = service.resolve("Gene", values)
        for k, v in want.items():
            o = outcome.get(v.lower()) if v else None
            if o and o["status"] == "unique":
                pid = (o.get("summaries", {}).get(o["genes"][0]) or {}).get("primaryIdentifier")
                if pid:
                    result[k] = pid
                    del pending[k]
        log(f"  {kind}: {len(values)} identifiers, {len(pending)} genes still unplaced")
    return result, pending


def resolve_legacy(service, defs, classes, log):
    """Per legacy definition: the members the mine holds ('uploadable') and those it does not. A member counts when the
    mine matches it to exactly one object by a key field (category MATCH): the same test the upload applies."""
    by_type = {}
    for d in defs:
        by_type.setdefault(d["type"], set()).update(d["members"])
    outcome = {}
    for t, values in by_type.items():
        if t in classes:
            outcome[t] = service.resolve(t, values)
            log(f"  {t}: {len(values)} legacy identifiers")
    for d in defs:
        o = outcome.get(d["type"])
        if o is None:
            d["uploadable"], d["unresolved"] = [], list(d["members"])
            d["not_in_model"] = True
            continue
        d["not_in_model"] = False
        d["uploadable"] = [m for m in d["members"] if o[m.lower()]["status"] == "unique"
                           and o[m.lower()]["categories"] == ["MATCH"]]
        ok = set(d["uploadable"])
        d["unresolved"] = [m for m in d["members"] if m not in ok]


# ---------------------------------------------------------------------------------------------- the run

def plan_uploads(service, panel_defs, legacy_defs, log):
    """(uploads, skipped): the lists to upload ({name, kind, type, description, tags, identifiers, ...}) and the ones
    left out with a reason."""
    uploads, skipped = [], []
    todo = [d for d in panel_defs if d["genes"]]
    for d in panel_defs:
        if not d["genes"]:
            skipped.append({"name": d["name"], "kind": "panelapp", "reason": "the panel has no Green gene (a list cannot be empty)"})
    pids, unplaced = resolve_panel_genes(service, todo, log) if todo else ({}, {})
    log(f"  PanelApp: {len(pids)} distinct genes placed, {len(unplaced)} not")
    for d in todo:
        ids, bad = [], []
        for rec in d["genes"]:
            pid = pids.get(gene_key(rec))
            if pid is None:
                bad.append(rec["symbol"] or rec["hgnc_id"])
            elif pid not in ids:
                ids.append(pid)
        if not ids:
            skipped.append({"name": d["name"], "kind": "panelapp", "reason": "none of the panel's genes resolves in this mine"})
            continue
        uploads.append({"name": d["name"], "kind": "panelapp", "type": d["type"], "description": d["description"],
                        "tags": list(d["tags"]), "identifiers": ids, "members_in": len(d["genes"]),
                        "unresolved": bad, "panel_id": d["panel"]["id"], "panel_version": d["panel"]["version"]})
    for d in legacy_defs:
        n_in, n_ok = len(d["members"]), len(d["uploadable"])
        log(f"  legacy list {d['name']} ({d['type']}): {n_ok} of {n_in} members are in this mine")
        if d.get("not_in_model"):
            skipped.append({"name": d["name"], "kind": "legacy", "reason": f"the type {d['type']} is not in this mine's model"})
            continue
        if n_ok == 0:
            skipped.append({"name": d["name"], "kind": "legacy",
                            "reason": f"none of its {n_in} members is in this mine"})
            continue
        desc = d["description"]
        if n_ok < n_in:
            desc = (desc + " " if desc else "") + (f"[Note: this mine holds {n_ok} of the {n_in} members of the "
                                                   f"original HumanMine list.]")
        tags = list(d["tags"])
        if PUBLIC_TAG not in tags:
            tags.append(PUBLIC_TAG)
        uploads.append({"name": d["name"], "kind": "legacy", "type": d["type"], "description": desc, "tags": tags,
                        "identifiers": list(d["uploadable"]), "members_in": n_in, "unresolved": d["unresolved"]})
    names = [u["name"] for u in uploads] + [s["name"] for s in skipped]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ApplyError("a list name is produced twice (a legacy list and a panel?): " + ", ".join(dup))
    return uploads, skipped


def stale_lists(snapshot, produced):
    """Public PL_ lists tagged as Genomics England panels that this run does not produce."""
    return sorted(l["name"] for l in snapshot
                  if l["name"].startswith(NAME_PREFIX) and PUBLIC_TAG in (l.get("tags") or [])
                  and PANEL_TAG in (l.get("tags") or []) and l["name"] not in produced)


def verify_lists(service, uploads, removed):
    """Read every uploaded list back (anonymously: what a visitor sees). Returns (rows, problems)."""
    after = service.lists()
    count = {}
    for l in after:
        count[l["name"]] = count.get(l["name"], 0) + 1
    by = {l["name"]: l for l in after}
    rows, problems = [], []
    for u in uploads:
        l = by.get(u["name"])
        why = []
        if l is None:
            why.append("not visible to an anonymous reader (not public?)")
        else:
            if count[u["name"]] > 1:
                why.append(f"{count[u['name']]} lists of this name")
            if PUBLIC_TAG not in (l.get("tags") or []):
                why.append("no im:public tag")
            if not set(u["tags"]) <= set(l.get("tags") or []):
                why.append("tags differ")
            if l.get("size") != len(u["identifiers"]):
                why.append(f"size {l.get('size')} instead of {len(u['identifiers'])}")
            if l.get("type") != u["type"]:
                why.append(f"type {l.get('type')}")
            if (l.get("description") or "") != u["description"]:
                why.append("description differs")
        rows.append({"name": u["name"], "type": u["type"], "size": l.get("size") if l else None,
                     "expected": len(u["identifiers"]), "tags": ";".join(l.get("tags") or []) if l else "",
                     "ok": not why, "why": "; ".join(why)})
        if why:
            problems.append(f"{u['name']}: " + "; ".join(why))
    for n in removed:
        if n in by:
            problems.append(f"{n}: removed but still listed")
    return rows, problems


def format_table(rows):
    head = ("list", "type", "size", "expected", "public", "ok")
    body = [(r["name"][:78], r["type"], str(r["size"]), str(r["expected"]),
             "yes" if PUBLIC_TAG in r["tags"].split(";") else "no", "ok" if r["ok"] else r["why"])
            for r in rows]
    widths = [max(len(x[i]) for x in [head] + body) for i in range(len(head) - 1)]
    fmt = "  ".join("%%-%ds" % w for w in widths) + "  %s"
    return "\n".join([fmt % head, fmt % tuple(["-" * w for w in widths] + ["--"])] + [fmt % b for b in body])


def run(args, service, exporter=None, today=None, log=print, clock=time.time):
    """The whole job. Returns the run report (a dict); raises ApplyError (ArchiveError, GuardError) when it must stop."""
    t0 = clock()
    mine = guard_mine(args.mine, args.i_know_this_is_production)
    label = args.mine_label or urllib.parse.urlparse(mine).path.rstrip("/").split("/")[-1] or "mine"
    today = today or datetime.date.today().isoformat()
    keep = args.keep_2021_names
    in_dir = locate_panelapp(args.panelapp_cache)
    if not args.dry_run:
        verify_cache(args.panelapp_cache, log)
    meta, panel_defs = panel_definitions(in_dir, args.select, keep)
    legacy_defs = legacy_definitions(args.legacy) if args.legacy else []
    log(f"{len(panel_defs)} panels selected ({args.select}; PanelApp fetched {meta['fetch_date']}), "
        f"{len(legacy_defs)} legacy lists; names: {'2021 names kept' if keep else 'current panel names'}")
    service.wait(args.wait)
    report = {"tool": "tools/apply_public_lists.py", "mine": mine, "mine_label": label, "dry_run": args.dry_run,
              "date": today, "select": args.select, "keep_2021_names": keep, "panelapp_fetch_date": meta["fetch_date"],
              "panels_selected": len(panel_defs), "archive": None, "uploaded": [], "skipped": [], "removed": [],
              "removal_failed": [], "verification": None, "failures": []}

    # 1. archive first
    if args.dry_run:
        n = len(service.lists())
        base = os.path.join(args.archive_repo, f"{label}-public-lists")
        log(f"--dry-run: would archive the {n} current public lists of {mine} to {base}/{today}[-N]/")
        report["archive"] = {"path": None, "lists": n, "would_write_under": base}
    else:
        exporter = exporter or load_exporter(args.export_script or os.path.join(args.archive_repo, "scripts", EXPORT_SCRIPT_NAME))
        report["archive"] = archive_current_lists(mine, args.archive_repo, label, exporter, today, log)

    # 2. resolve
    classes = service.model_classes()
    snapshot = service.lists()
    log("resolving the PanelApp genes in the mine")
    uploads, skipped = plan_uploads_with_legacy(service, panel_defs, legacy_defs, classes, log)
    report["skipped"] = skipped
    stale = stale_lists(snapshot, {u["name"] for u in uploads})
    for s in skipped:
        log(f"  skipped {s['name']}: {s['reason']}")
    log(f"{len(uploads)} lists to upload ({sum(1 for u in uploads if u['kind'] == 'panelapp')} PanelApp, "
        f"{sum(1 for u in uploads if u['kind'] == 'legacy')} legacy), {len(skipped)} skipped, {len(stale)} stale")
    for u in uploads:
        report["uploaded"].append({"name": u["name"], "kind": u["kind"], "type": u["type"], "size": len(u["identifiers"]),
                                   "members_in": u["members_in"], "unresolved_count": len(u["unresolved"]),
                                   "unresolved": u["unresolved"][:REPORT_CAP], "tags": u["tags"],
                                   **({"panel_id": u["panel_id"], "panel_version": u["panel_version"]} if u["kind"] == "panelapp" else {})})
    if args.dry_run:
        log("--dry-run: nothing written to the mine or to the archive")
        report["would_remove"] = stale
        report["seconds"] = round(clock() - t0, 1)
        return report

    # 3. upload as the superuser
    service.login()
    failed = []
    for i, u in enumerate(uploads, 1):
        try:
            res = service.upload(u["name"], u["type"], u["description"], u["tags"], u["identifiers"])
            if res["size"] != len(u["identifiers"]):
                failed.append(f"{u['name']}: the mine made {res['size']} members of {len(u['identifiers'])} identifiers "
                              f"(unmatched: {res['unmatched'][:5]})")
        except ApplyError as e:
            failed.append(str(e))
        if i % 50 == 0:
            log(f"  uploaded {i}/{len(uploads)}")
    # 4. stale lists
    for n in stale:
        try:
            service.delete(n)
            report["removed"].append(n)
            log(f"  removed stale list {n}")
        except ApplyError as e:
            report["removal_failed"].append(str(e))
    # 5. read back
    rows, problems = verify_lists(service, uploads, report["removed"])
    print(format_table(rows))
    report["verification"] = {"lists": len(rows), "ok": sum(1 for r in rows if r["ok"]), "problems": problems, "rows": rows}
    report["failures"] = failed + report["removal_failed"] + problems
    report["seconds"] = round(clock() - t0, 1)
    log(f"{len(uploads) - len(failed)} lists uploaded, {len(report['removed'])} stale removed, {len(skipped)} skipped, "
        f"{len(report['failures'])} problems, {report['seconds']} s")
    return report


def plan_uploads_with_legacy(service, panel_defs, legacy_defs, classes, log):
    if legacy_defs:
        log("resolving the legacy lists' members in the mine")
        resolve_legacy(service, legacy_defs, classes, log)
    return plan_uploads(service, panel_defs, legacy_defs, log)


# ---------------------------------------------------------------------------------------------- command line

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--mine", default=DEFAULT_MINE, help="mine base URL (default %(default)s)")
    ap.add_argument("--user", default="superuser@intermine.org", help="superuser (default %(default)s, the demo's)")
    ap.add_argument("--password", default="intermine", help="its password (default the demo's)")
    ap.add_argument("--panelapp-cache", required=True, help="the PanelApp cache group directory (META.json in it or in data/)")
    ap.add_argument("--legacy", help="the legacy lists: a directory like an archive (lists.json, members/), "
                                     "curation/public_lists")
    ap.add_argument("--archive-repo", required=True,
                    help="the archive repository (historic_artefacts); each run adds <mine-label>-public-lists/<date>[-N]/")
    ap.add_argument("--export-script", default=os.environ.get("PUBLIC_LISTS_EXPORT_SCRIPT"),
                    help=f"the T2.1 export script (default <archive-repo>/scripts/{EXPORT_SCRIPT_NAME}; also PUBLIC_LISTS_EXPORT_SCRIPT)")
    ap.add_argument("--mine-label", help="names the archive directory <label>-public-lists (default: the last path part of --mine)")
    ap.add_argument("--select", choices=sorted(P.PANEL_SELECTIONS), default="all",
                    help="all panels (default) or 100k, the 'rare-disease-100k' type HumanMine's 2021 set was")
    names = ap.add_mutually_exclusive_group()
    names.add_argument("--keep-2021-names", dest="keep_2021_names", action="store_true", default=KEEP_2021_NAMES_DEFAULT,
                       help="the 17 renamed panels keep their 2021 list names%s" % (" (default)" if KEEP_2021_NAMES_DEFAULT else ""))
    names.add_argument("--current-names", dest="keep_2021_names", action="store_false",
                       help="name every list after the panel's current PanelApp name%s" % ("" if KEEP_2021_NAMES_DEFAULT else " (default)"))
    ap.add_argument("--dry-run", action="store_true", help="resolve and print the plan; archive and write nothing")
    ap.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait this long for the mine to answer")
    ap.add_argument("--report", help="write the JSON run report here")
    ap.add_argument("--i-know-this-is-production", action="store_true",
                    help="allow a mine on a public host (refused otherwise)")
    return ap.parse_args(argv)


def main(argv=None, service=None, exporter=None):
    args = parse_args(argv)
    try:
        mine = guard_mine(args.mine, args.i_know_this_is_production)
        service = service or WebService(mine, args.user, args.password)
        report = run(args, service, exporter)
    except ApplyError as e:
        print(f"apply_public_lists: {e}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError, P.FetchError, RuntimeError) as e:
        print(f"apply_public_lists: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if args.report and not args.dry_run:
        P.dump_json(args.report, report)
        print(f"run report: {args.report}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
