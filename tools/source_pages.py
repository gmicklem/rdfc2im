#!/usr/bin/env python3
"""source_pages.py: data-source status pages (Markdown) from a build manifest [im-9n4.42].

  source_pages.py pages --manifest out/_mine/source_manifest.json --out DIR
      One page per source (DIR/<kind>-<name>.md) and an index (DIR/README.md), readable on GitHub as they
      are. The output is deterministic: the same manifest and mapping files give byte-identical pages, and
      the only dates in them are the manifest's.

  source_pages.py data-set-links --base-url URL --out ITEMS.xml [--sources "..."] [--stock-sources "..."]
      Items XML setting DataSet.url (the source's page) and DataSet.description on every data set the
      selected sources write, for an items source loaded last (see add-links-source).

  source_pages.py add-links-source --project project.xml --priorities genomic_priorities.properties
                                   --items PATH [--name data-set-links]
      Appends that source to a mine's project.xml (type humanmine-items, the version of the other
      humanmine-items entries) and gives it first priority for DataSet.url and DataSet.description.

Page contents: a header (data source, loader, licence, download), "This build" (scope, files with URL,
release, Last-Modified, fetch time, size, sha256, records read and kept, objects loaded), "Fields" (a
comma-separated "picked up" line, then one row per field of the source with what it maps to and how many
records carry it) and "Known gaps" (rdfc2im/data/source_gaps.yaml). Stock field rows come from
rdfc2im/data/stock_mappings/<source>.yaml joined with tools/field_counts.py counts; RDF field rows from
out/<source>/mapping_predicates.sssom.tsv joined with counts of the cached extract.
"""
import argparse
import os
import re
import sys
from xml.sax.saxutils import quoteattr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import yaml  # noqa: E402

MAPPINGS_DIR = os.path.join(HERE, "rdfc2im", "data", "stock_mappings")
SOURCES_YAML = os.path.join(HERE, "rdfc2im", "data", "sources.yaml")
REPO_URLS = {"intermine": "https://github.com/intermine/intermine/tree/{commit}/{path}",
             "humanmine-bio-sources": "https://github.com/gmicklem/humanmine-bio-sources/tree/{commit}/{path}"}
RDFC2IM_URL = "https://github.com/gmicklem/rdfc2im"
# rdfc2im's sssom ext_status -> (loaded?, reason for not loaded)
RDF_STATUS = {"sure": (True, ""), "human": (True, ""), "guess": (True, "loaded; the mapping is marked as a guess"),
              "todo": (False, "not yet done"), "drop": (False, "dropped on purpose"),
              "link": (False, "used only to link tables, not stored"), "pruned": (False, "pruned: no place in the model")}


def page_name(src):
    return f"{src['kind']}-{src['name']}.md"


def fmt_n(n):
    return "?" if n is None else f"{int(n):,}"


def cell(s):
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace("|", "\\|")


def short(s, n=220):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    m = re.match(r"^(.{60,}?[.;])\s", cut)
    return (m.group(1) if m else cut.rsplit(" ", 1)[0]) + " ..."


def day(ts):
    return (ts or "")[:10] or None


def utc(ts):
    if not ts:
        return None
    return ts.replace("T", " ").replace("Z", " UTC")


def load_mapping(name, mappings_dir=None):
    p = os.path.join(mappings_dir or MAPPINGS_DIR, f"{name}.yaml")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------- scope in words

def scope_words(src, build):
    panel = build.get("panel_genes")
    p = f"{panel}-gene panel" if panel else "the gene panel"
    if src["kind"] == "rdf":
        sc = ((src.get("cache_group") or {}).get("meta") or {}).get("scope")
        if sc == "full" and (src.get("items") or {}).get("Gene"):
            n = src["items"]["Gene"]
            return f"all human genes of the types the stock NCBI loader keeps ({fmt_n(n)} genes in the items file), as identifiers"
        if sc == "full":
            return "the whole data set for human (no gene filter)"
        if sc == "panel":
            return f"{p}, deep annotation"
        if sc == "pmid":
            return "the PubMed records the other sources cite"
        if sc == "none":
            return "the whole data set (not gene-shaped: no gene filter)"
        return f"scope {sc or 'not recorded'}"
    files = src.get("files") or []
    if any(isinstance(f.get("filter"), dict) for f in files):
        ids = {f["filter"].get("ids") for f in files if isinstance(f.get("filter"), dict)}
        if ids & {"mgi", "rgd"}:
            return f"the partner genes of the {p}'s PANTHER rows"
        return f"{p}"
    return "the whole file (no gene filter)"


def build_scope_line(build):
    panel = build.get("panel_genes")
    human = build.get("mine_human_genes")
    if build.get("gene_identifiers") == "all":
        h = f"all {fmt_n(human)} human genes" if human else "all human genes"
        return f"{panel}-gene panel, deep annotation; {h} as identifiers"
    return f"{panel}-gene panel"


# ---------------------------------------------------------------- stock field rows

def _parents(key):
    parts = key.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def stock_rows(mf, counts_raw, counts_input):
    """[(key, name, description, maps_to, status, reason, n_raw, n_input, listed)] for one file: the
    mapping's fields in their order, then the keys the counts found that it does not list (XML: only the
    top-most unlisted element of a subtree, and nothing under a listed not-loaded element)."""
    fields = mf.get("fields") or []
    listed = {f["key"]: f for f in fields}
    rk = (counts_raw or {}).get("keys") or {}
    ik = (counts_input or {}).get("keys") or {}
    names = dict((counts_raw or {}).get("names") or {}) or dict((counts_input or {}).get("names") or {})
    rows = []
    for f in fields:
        rows.append(dict(key=f["key"], name=f.get("name") or names.get(f["key"]), description=f.get("description"),
                         maps_to=f.get("maps_to") or [], status=f.get("status", "unknown"), reason=f.get("reason"),
                         note=f.get("note"), raw=rk.get(f["key"]), inp=ik.get(f["key"]), listed=True))
    covered = {k for k, f in listed.items() if f.get("status") == "not loaded"}
    seen = set(listed)
    xml = mf.get("format") == "xml"
    for k in sorted(set(rk) | set(ik), key=_order):
        if k in seen:
            continue
        if xml and any(p in covered or (p in seen and p not in listed) for p in _parents(k)):
            continue
        seen.add(k)
        un = mf.get("unlisted", "unknown")
        rows.append(dict(key=k, name=names.get(k), description=None, maps_to=[], status=un,
                         reason=mf.get("unlisted_reason") if un == "not loaded" else "not in the mapping file",
                         note=None, raw=rk.get(k), inp=ik.get(k), listed=False))
    return rows


def _order(k):
    m = re.match(r"^col:(\d+)$", k)
    return (0, int(m.group(1)), "") if m else (1, 0, k)


def _cnt(c):
    """'1,234' or '1,234 (5,678 values)' from a {with, values} count."""
    if not c:
        return "0"
    w, v = c.get("with", 0), c.get("values", 0)
    if w == 0 and v:
        return f"{fmt_n(v)} values"
    return fmt_n(w) if not v or v == w else f"{fmt_n(w)} ({fmt_n(v)} values)"


def status_cell(status, n):
    return f"**{status}** ({n})" if status in ("loaded", "not loaded") else f"**{status}** ({n})"


# ---------------------------------------------------------------- page parts

def generated_line(man):
    b = man["build"]
    ident = b.get("name") or "the build"
    commit = (b.get("rdfc2im_commit") or "")[:10]
    fin = utc(b.get("finished_at")) or "date not recorded"
    return (f"> Generated by rdfc2im `tools/source_pages.py` from the manifest of build **{ident}** "
            f"(rdfc2im {commit or 'commit not recorded'}, finished {fin}). Do not edit by hand: regenerate it "
            "(rdfc2im USAGE.md, \"Data-source status pages\").")


def _loader_line(mp):
    ld = (mp or {}).get("loader") or {}
    repo, path, commit = ld.get("repository"), ld.get("path"), str(ld.get("commit") or "")
    if not repo:
        return "not recorded"
    tmpl = REPO_URLS.get(repo)
    link = tmpl.format(commit=commit, path=path) if tmpl and commit and path else None
    classes = ", ".join(c.rsplit(".", 1)[-1] for c in ld.get("classes") or [])
    s = f"{repo} `{path}` at {commit}" if not link else f"[{repo} `{path}`]({link}) at {commit}"
    return s + (f" ({classes})" if classes else "")


def _loaded_table(src, out):
    loaded = src.get("loaded") or {}
    rows = [(ds, c, n) for ds, per in sorted(loaded.items()) for c, n in sorted(per.items())]
    if loaded:
        out.append("Objects loaded, from the mine after the build, for the classes this source writes. A class that "
                   "links to its data sets is counted for this source's data set (a class counts its subclasses too); "
                   "a class without that link can only be counted over the whole mine, all sources together:")
        out.append("")
        out.append("| Data set | Class | Objects |")
        out.append("|---|---|---:|")
        for ds, per in sorted(loaded.items()):
            if not per:
                out.append(f"| {cell(ds)} | (none) | 0 |")
        for ds, c, n in rows:
            out.append(f"| {cell(ds)} | {c} | {fmt_n(n)} |")
        for c, n in sorted((src.get("loaded_unlinked") or {}).items()):
            if c in ("DataSet", "DataSource"):     # every source writes them; their mine totals say nothing here
                continue
            out.append(f"| (no link to a data set: all sources, whole mine) | {c} | {fmt_n(n)} |")
        out.append("")
    else:
        out.append("Objects loaded: not counted (the manifest was made without `--mine`).")
        out.append("")


STATUS_WORDS = {"verified": "verified: stated on the source's own page or file",
                "partial": "partly verified: a related statement was read, the full one was not (see the conditions)",
                "not-verified": "not verified: the source points to a page that could not be read",
                "not-stated": "not stated: nothing findable (see what was looked at, in the conditions)",
                "not-checked": "not checked"}


def licence_rows(info, legacy=None, redistributable=None, rdf=False):
    """The licence rows of a page's header table, from a manifest's `licence_info` (rdfc2im/stock.py
    licence_info). `legacy` is the plain `licence` string of a manifest made before the structured keys:
    it gives the one old row. Deterministic: the only date is the one recorded with the statement."""
    label = "Licence (upstream)" if rdf else "Licence"
    if not info or not info.get("name"):
        if rdf and not legacy:
            return [f"| {label} | not recorded in rdfc2im (see the data source's own terms) |",
                    "| Redistributable | the cached extract is published with rdfc2im's raw-data cache |"]
        out = [f"| {label} | {cell(legacy) or 'not recorded'} |"]
        if redistributable is not None:
            out.append(f"| Redistributable | {'yes' if redistributable else 'no'} |")
        return out
    url = info.get("url")
    name = cell(info["name"])
    out = [f"| {label} | {name} |",
           f"| Licence status | {cell(STATUS_WORDS.get(info.get('status'), info.get('status') or 'not recorded'))} |"]
    if url:
        shown = f"<{url}>" if re.match(r"^https?://\S+$", url) else cell(url)
        out.append(f"| Licence stated at | {shown} |")
    if info.get("checked"):
        out.append(f"| Licence read on | {cell(info['checked'])} (UTC) |")
    if info.get("quote"):
        out.append(f"| Licence wording | \"{cell(info['quote'])}\" |")
    if info.get("conditions"):
        out.append("| Conditions | " + " <br> ".join("- " + cell(c) for c in info["conditions"]) + " |")
    if rdf:
        if info.get("rdfportal"):
            rp = cell(info["rdfportal"])
            if info.get("rdfportal_url"):
                rp += f" (on <{info['rdfportal_url']}>)"
            out.append(f"| Licence (RDF Portal) | {rp}" + (f". {cell(info['rdfportal_note'])}" if info.get("rdfportal_note") else "") + " |")
        elif info.get("rdfportal_note"):
            out.append(f"| Licence (RDF Portal) | {cell(info['rdfportal_note'])} |")
    red = info.get("redistributable")
    if red is None:
        red = redistributable
    if red is not None:
        out.append(f"| Redistributable | {'yes' if red else 'no'}" + (f": {cell(info['reason'])}" if info.get("reason") else "") + " |")
    return out


def licence_cell(s):
    """The index's Licence column: the name, with the status when it is not a verified one."""
    info = s.get("licence_info") or {}
    name = info.get("name") or s.get("licence")
    if not name:
        return "not recorded"
    st_ = info.get("status")
    return cell(name) + (f" [{st_}]" if st_ and st_ != "verified" else "")


def stock_page(src, man):
    mp = load_mapping(src["name"]) or {}
    msum = src.get("mapping") or {}
    files = src.get("files") or []
    out = [generated_line(man), "", f"# {src['name']}", ""]
    if msum.get("partial") or mp.get("partial"):
        out += ["**Partial page:** " + cell(mp.get("partial_reason") or "the field table covers the first level only."), ""]
    ds = msum.get("data_source") or mp.get("data_source")
    home = mp.get("home")
    out += ["| | |", "|---|---|",
            f"| Data source | {cell(ds) or 'not recorded'}" + (f" ([home page]({home}))" if home else "") + " |",
            f"| Loader | {_loader_line(mp)}; source type `{src.get('type')}` |",
            f"| Data sets in the mine | {cell(', '.join(msum.get('data_sets') or [])) or 'not recorded'} |",
            ]
    out += licence_rows(src.get("licence_info"), src.get("licence"), bool(src.get("redistributable")))
    for f in files:
        if f.get("url"):
            out.append(f"| Download ({cell(f['id'])}) | <{f['url']}> |")
    out += ["", "## This build", "", f"**Scope:** {scope_words(src, man['build'])}.", ""]
    out += ["| File | Release / version | Last-Modified (server) | Fetched at (UTC) | Size (bytes) | sha256 |",
            "|---|---|---|---|---:|---|"]
    for f in files:
        name = f.get("raw_name") or f["id"]
        out.append(f"| `{cell(name)}` | {cell(f.get('release')) or 'not stated in the file'} | "
                   f"{cell(utc(f.get('last_modified')) or f.get('table_last_modified') or 'not sent')} | "
                   f"{cell(utc(f.get('fetched_at')) or ('not fetched: ' + f['origin'] if (f.get('origin') or '').startswith('rdfc2im') else 'not recorded'))} | "
                   f"{fmt_n(f.get('size')) if f.get('size') else '?'} | "
                   f"`{(f.get('sha256') or '?')}` |")
    out.append("")
    for f in files:
        rr, kk = f.get("records_raw"), f.get("records_kept")
        what = ((mp_file(mp, f["id"]) or {}).get("record")) or "records"
        part = ""
        cr = f.get("counts_raw") or {}
        if cr and not cr.get("complete", True):
            tot = f.get("uncompressed_bytes")
            share = f"{100.0 * cr.get('bytes_read', 0) / tot:.0f}% of the file, " if tot else ""
            part = (f" (counted over the first {share}{fmt_n(cr.get('bytes_read'))} uncompressed bytes only: the count "
                    "stopped at its time limit, so every n below is a lower bound)")
        out.append(f"- `{cell(f.get('raw_name') or f['id'])}`: {fmt_n(rr)} records in the file{part} "
                   f"(one record: {cell(what)}); {fmt_n(kk)} kept. Filter: {cell(f.get('filter_rule'))}")
    out.append("")
    _loaded_table(src, out)
    out += ["## Fields", ""]
    all_rows = []
    for f in files:
        mf = mp_file(mp, f["id"])
        if not mf:
            continue
        all_rows.append((f, mf, stock_rows(mf, f.get("counts_raw"), f.get("counts_input"))))
    picked = []
    for _f, _mf, rows in all_rows:
        for r in rows:
            if r["status"] == "loaded":
                nm = r["name"] or r["key"]
                if nm not in picked:
                    picked.append(nm)
    out += [f"**Picked up:** {cell(', '.join(picked)) or 'nothing listed'}", ""]
    if not all_rows:
        out += ["No mapping file for this source yet (`rdfc2im/data/stock_mappings/" + src["name"] + ".yaml`).", ""]
    for f, mf, rows in all_rows:
        filt = isinstance(f.get("filter"), dict)
        whole = "the whole upstream file" + ("" if (f.get("counts_raw") or {}).get("complete", True) else " (first part only)")
        out.append(f"### `{cell(f.get('raw_name') or f['id'])}` ({cell(mf.get('format'))})")
        out.append("")
        out.append(f"n in the status column = records of {whole} that carry the field "
                   f"(records counted: {fmt_n(f.get('records_raw'))}; for a repeated element or tag the number of "
                   "values follows in brackets)." + (" The last column counts the same in this build's input, the "
                                                     f"file the filter kept (records: {fmt_n(f.get('records_kept'))})."
                                                     if filt else ""))
        out.append("")
        head = "| Field | Name | What it is | Maps to (HumanMine) | Status (n) | Reason or note |"
        sep = "|---|---|---|---|---|---|"
        if filt:
            head += " In this build's input |"
            sep += "---:|"
        out += [head, sep]
        for r in rows:
            reason = r["reason"] or ""
            if r.get("note"):
                reason = (reason + "; " if reason else "") + short(r["note"], 160)
            line = (f"| `{cell(r['key'])}` | {cell(r['name'])} | {cell(short(r['description'], 140))} | "
                    f"{cell(', '.join(r['maps_to']))} | {status_cell(r['status'], _cnt(r['raw']))} | {cell(reason)} |")
            if filt:
                line += f" {_cnt(r['inp'])} |"
            out.append(line)
        out.append("")
    out += gaps_section(src, man)
    return "\n".join(out).rstrip() + "\n"


def mp_file(mp, fid):
    return next((f for f in (mp or {}).get("files") or [] if f.get("id") == fid), None)


def gaps_section(src, man):
    gaps = (man.get("gaps") or {}).get(src["id"]) or []
    out = ["## Known gaps", ""]
    if not gaps:
        return out + ["None recorded in BUILD.md or the expert review log.", ""]
    for g in gaps:
        out.append(f"- {cell(g.get('text'))} (Recorded in: {cell(g.get('from'))}.)")
    return out + [""]


# ---------------------------------------------------------------- RDF pages

def rdf_rows(src):
    tables = src.get("tables") or {}
    ep = src.get("endpoint_counts") or {}
    rows = []
    for r in src.get("mapping_rows") or []:
        pred = r.get("ext_predicate") or ""
        status = r.get("ext_status") or ""
        loaded, why = RDF_STATUS.get(status, (False, status or "unknown"))
        var, table = r.get("subject_label"), r.get("ext_table")
        if pred == "-const-":
            continue
        t = tables.get(table) or {}
        col = ((t.get("columns") or {}).get(var)) if var else None
        if pred == "-self-":
            pred_disp = "(the subject IRI itself)"
        else:
            pred_disp = pred
        if col:
            n = f"{fmt_n(col['with'])}" + (f" ({fmt_n(col['ids'])} subjects)" if col["ids"] != col["with"] else "")
        elif loaded:
            n = "0"
        else:
            n = "not fetched"
        e = ep.get(pred)
        en = (f"{fmt_n(e['with'])}" + (f" ({fmt_n(e['values'])} values)" if e["values"] != e["with"] else "")) \
            if e and "with" in e else ("error" if e else "")
        maps = r.get("object_label") or ""
        if r.get("ext_via"):
            maps = f"{maps} (via {r['ext_via']})" if maps else f"via {r['ext_via']}"
        rows.append(dict(pred=pred_disp, name=var, table=table, desc=short(r.get("comment"), 160),
                         maps=maps, loaded=loaded, why=why if not loaded or status == "guess" else "",
                         status=status, n=n, endpoint=en, subject=r.get("ext_subject")))
    return rows


def rdf_page(src, man):
    out = [generated_line(man), "", f"# {src['name']} (RDF)", ""]
    dsrc = src.get("data_source") or {}
    cg = src.get("cache_group") or {}
    commit = (man["build"].get("rdfc2im_commit") or "")[:10]
    out += ["| | |", "|---|---|",
            f"| Data source | {cell(dsrc.get('name')) or 'not recorded'}" + (f" (<{dsrc['url']}>)" if dsrc.get("url") else "") + " |",
            f"| Loader | [rdfc2im]({RDFC2IM_URL}) at {commit or '?'}: SPARQL extract, projected to InterMine items, loaded "
            f"as source `humanmine-{src['name']}` (type `humanmine-items`) |",
            f"| Data set in the mine | {cell(src.get('data_set')) or 'not recorded'} |",
            f"| SPARQL endpoint | <{src.get('endpoint')}> |" if src.get("endpoint") else "| SPARQL endpoint | not recorded |",
            f"| Graphs | {cell(', '.join(src.get('graphs') or [])) or 'none named (the whole endpoint)'} |",
            ]
    out += licence_rows(src.get("licence_info"), src.get("licence"), None, rdf=True)
    if src.get("replaces"):
        out.append(f"| Replaces stock source | {cell(', '.join(src['replaces']))} |")
    if src.get("alongside"):
        out.append(f"| Loaded beside stock source | {cell(', '.join(src['alongside']))} |")
    out += ["", "## This build", "", f"**Scope:** {scope_words(src, man['build'])}.", ""]
    out.append(f"Fetched at (UTC): {utc(cg.get('saved_at')) or 'not recorded'}. Release / version: not stated in the "
               "SPARQL results (RDF Portal names a release on its data set page).")
    out.append("")
    out += ["| Table (cached TSV) | Rows | Size (bytes) | sha256 |", "|---|---:|---:|---|"]
    for t, d in sorted((src.get("tables") or {}).items()):
        rows = (d.get("columns") or {}).get("_rows")
        out.append(f"| `{cell(t)}` | {fmt_n(rows)} | {fmt_n(d.get('size'))} | `{d.get('sha256')}` |")
    out.append("")
    items = src.get("items") or {}
    if items:
        out.append("Objects written to the items file, per class: " +
                   ", ".join(f"{c} {fmt_n(n)}" for c, n in sorted(items.items())) + ".")
        out.append("")
    _loaded_table(src, out)
    rows = rdf_rows(src)
    picked = []
    for r in rows:
        if r["loaded"] and r["name"] and r["name"] not in picked:
            picked.append(r["name"])
    out += ["## Fields", "", f"**Picked up:** {cell(', '.join(picked)) or 'nothing'}", ""]
    has_ep = any(r["endpoint"] for r in rows)
    out.append("One row per predicate of the rdfc2im mapping (`out/" + src["name"] + "/mapping_predicates.sssom.tsv`). "
               "n = rows of this build's cached extract (the scope above, not the whole endpoint) that carry a value; "
               "where one subject has several values the number of subjects follows. A predicate the mapping does not "
               "load is not fetched, so the extract has no count for it" +
               (": the last column counts it over the whole endpoint graph (one COUNT query per predicate)." if has_ep
                else "; `source_manifest.py --endpoint-counts` can count it over the whole endpoint."))
    out.append("")
    head = "| Predicate | Name (rdfc2im column) | Mapping note | Maps to (HumanMine) | Status (n) | Reason |"
    sep = "|---|---|---|---|---|---|"
    if has_ep:
        head += " Whole endpoint (subjects) |"
        sep += "---:|"
    out += [head, sep]
    for r in rows:
        st = "loaded" if r["loaded"] else "not loaded"
        line = (f"| `{cell(r['pred'])}` | {cell(r['name'])} | {cell(r['desc'])} | {cell(r['maps'])} | "
                f"**{st}** ({r['n']}) | {cell(r['why'])} |")
        if has_ep:
            line += f" {cell(r['endpoint'])} |"
        out.append(line)
    out.append("")
    out += gaps_section(src, man)
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- index

def field_tally(src):
    if src["kind"] == "rdf":
        rows = rdf_rows(src)
        return sum(1 for r in rows if r["loaded"]), sum(1 for r in rows if not r["loaded"]), 0
    mp = load_mapping(src["name"]) or {}
    lo = nl = un = 0
    for f in src.get("files") or []:
        mf = mp_file(mp, f["id"])
        if not mf:
            continue
        for r in stock_rows(mf, f.get("counts_raw"), f.get("counts_input")):
            if r["status"] == "loaded":
                lo += 1
            elif r["status"] == "not loaded":
                nl += 1
            else:
                un += 1
    return lo, nl, un


def version_of(src):
    if src["kind"] == "rdf":
        return "not stated", day((src.get("cache_group") or {}).get("saved_at"))
    vs, fetched = [], []
    for f in src.get("files") or []:
        v = f.get("release") or (("Last-Modified " + day(f["last_modified"])) if f.get("last_modified")
                                 and f["last_modified"] != "unknown" else None)
        if v and v not in vs:
            vs.append(v)
        if f.get("fetched_at") and day(f["fetched_at"]) not in fetched:
            fetched.append(day(f["fetched_at"]))
    return "; ".join(vs) or "not stated", ", ".join(fetched) or None


def reference_for(src, ref):
    """Public HumanMine's DataSet records for the source: by the source's own name, its replaced or
    supplemented stock sources' names, and the data set names the mapping lists."""
    if not ref:
        return []
    names = [src["name"]] + list(src.get("replaces") or []) + list(src.get("alongside") or [])
    if src["kind"] == "stock":
        names += (src.get("mapping") or {}).get("data_sets") or []
    recs = ref.get("datasets") or []
    out = []
    for n in names:
        for r in recs:
            if r.get("name") == n and r not in out and (r.get("version") or r.get("description")):
                out.append(r)
    return out


def index_page(man):
    b = man["build"]
    out = [generated_line(man), "", "# HumanMine data sources: status of this build", ""]
    out += ["What each source of this hybrid HumanMine build loaded, from which file and release, and what it "
            "did not load. One page per source; the field tables say, for every field of the source, whether it "
            "is loaded and how many records carry it.", ""]
    out += ["| | |", "|---|---|",
            f"| Build | {cell(b.get('name')) or 'not named'} |",
            f"| Scope | {cell(build_scope_line(b))} |",
            f"| Finished (UTC) | {cell(utc(b.get('finished_at')) or 'not recorded')} |",
            f"| rdfc2im | [{(b.get('rdfc2im_commit') or '?')[:10]}]({RDFC2IM_URL}/commit/{b.get('rdfc2im_commit') or ''}) |",
            f"| InterMine | {cell(b.get('intermine_version') or '?')} at {cell((b.get('intermine_commit') or '?')[:10])} |",
            "| humanmine-bio-sources | " + (cell(b["humanmine_bio_sources_commit"][:10]) if b.get("humanmine_bio_sources_commit")
                                           else "not recorded by the build (each source page names the commit its "
                                                "mapping was read at)") + " |"]
    if b.get("mine_total_objects") is not None:
        out.append(f"| Objects in the mine | {fmt_n(b['mine_total_objects'])} (the counts of the classes no other class "
                   "extends, summed) |")
    out.append("")
    out += ["| Source | Data source | Release / date | Fetched (UTC) | Scope | Fields loaded / not loaded / unknown | Licence |",
            "|---|---|---|---|---|---|---|"]
    for s in man["sources"]:
        lo, nl, un = field_tally(s)
        ver, fetched = version_of(s)
        if s["kind"] == "rdf":
            dsrc = (s.get("data_source") or {}).get("name")
        else:
            dsrc = (s.get("mapping") or {}).get("data_source")
        lic = licence_cell(s)
        label = f"{s['name']} ({'RDF' if s['kind'] == 'rdf' else 'stock'})"
        out.append(f"| [{cell(label)}]({page_name(s)}) | {cell(dsrc)} | {cell(ver)} | {cell(fetched)} | "
                   f"{cell(scope_words(s, b))} | {lo} / {nl} / {un} | {cell(lic)} |")
    out.append("")
    ref = man.get("reference")
    if ref:
        out += ["## Compared with public HumanMine", "",
                f"Public HumanMine ({cell(ref.get('mine'))}, read {cell(ref.get('read_at'))}) describes its sources in "
                "DataSet records; its data are from February 2022. Matched by source name (and, for an RDF source, by "
                "the stock source it replaces or supplements).", "",
                "| Source | This build | Public HumanMine data set | Its version | Its description |", "|---|---|---|---|---|"]
        for s in man["sources"]:
            ver, _ = version_of(s)
            recs = reference_for(s, ref)
            label = f"[{cell(s['name'])} ({'RDF' if s['kind'] == 'rdf' else 'stock'})]({page_name(s)})"
            if not recs:
                out.append(f"| {label} | {cell(ver)} | (none) | | |")
            for r in recs:
                out.append(f"| {label} | {cell(ver)} | {cell(r.get('name'))} | {cell(r.get('version'))} | "
                           f"{cell(short(r.get('description'), 120))} |")
        out.append("")
    out += ["## How these pages are made", "",
            "`tools/source_manifest.py` (rdfc2im) collects the build manifest from the raw-data caches, the build "
            "logs and the mine; `tools/source_pages.py pages` turns it and the mapping files into these pages. "
            "`tools/full-build.sh --source-pages DIR` does both after the build's last phase. The field mappings "
            "of the stock loaders are in rdfc2im `rdfc2im/data/stock_mappings/`, read from the loaders' code; those "
            "of the RDF sources are rdfc2im's own mapping files. Counts over a raw file are made by streaming it "
            "(`tools/field_counts.py`) and cached under its sha256.", ""]
    return "\n".join(out).rstrip() + "\n"


def write_pages(man, out_dir, mappings_dir=None):
    global MAPPINGS_DIR
    saved = MAPPINGS_DIR
    MAPPINGS_DIR = mappings_dir or MAPPINGS_DIR
    try:
        return _write_pages(man, out_dir)
    finally:
        MAPPINGS_DIR = saved


def _write_pages(man, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for s in man["sources"]:
        text = rdf_page(s, man) if s["kind"] == "rdf" else stock_page(s, man)
        p = os.path.join(out_dir, page_name(s))
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(p)
    p = os.path.join(out_dir, "README.md")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(index_page(man))
    written.append(p)
    return written


# ---------------------------------------------------------------- DataSet links

def data_set_pages(stock_names, rdf_names, mappings_dir=None, sources_yaml=SOURCES_YAML):
    """{DataSet name: [page file names]} for the selected sources, in source order."""
    with open(sources_yaml, encoding="utf-8") as fh:
        scfg = yaml.safe_load(fh) or {}
    out = {}
    for n in rdf_names:
        t = (scfg.get(n) or {}).get("data_set_title")
        if t:
            out.setdefault(t, []).append(f"rdf-{n}.md")
    names = list(stock_names) + (["reactome"] if "reactome" in rdf_names else [])
    for n in names:
        mp = load_mapping(n, mappings_dir) or {}
        for ds in mp.get("data_sets") or []:
            if f"stock-{n}.md" not in out.setdefault(ds, []):
                out[ds].append(f"stock-{n}.md")
    return out


def data_set_links_xml(pages, base_url):
    base = base_url.rstrip("/") + "/"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             "<!-- generated by rdfc2im tools/source_pages.py data-set-links: DataSet.url and description point at",
             "     the data-source status pages; load as the last source (add-links-source) -->", "<items>"]
    for i, (ds, files) in enumerate(sorted(pages.items()), 1):
        names = ", ".join(f[:-3] for f in files)
        desc = (f"Status page of this data set's source ({names}): the file, release and fetch date this build "
                "loaded, and which fields of the source are loaded and which are not.")
        lines += [f'  <item id="0_{i}" class="DataSet" implements="">',
                  f'    <attribute name="name" value={quoteattr(ds)}/>',
                  f'    <attribute name="url" value={quoteattr(base + files[0])}/>',
                  f'    <attribute name="description" value={quoteattr(desc)}/>',
                  "  </item>"]
    lines.append("</items>")
    return "\n".join(lines) + "\n"


def add_links_source(project, priorities, items, name="data-set-links"):
    """Append <source name=NAME type=humanmine-items> reading ITEMS to project.xml (idempotent) and put NAME
    first for DataSet.url and DataSet.description in the priorities file. Text edits, so the rest of both
    files stays byte for byte as it was."""
    with open(project, encoding="utf-8") as fh:
        text = fh.read()
    if f'<source name="{name}"' not in text:
        m = re.search(r'<source name="[^"]+" type="humanmine-items"( version="[^"]+")?', text)
        version = m.group(1) if m and m.group(1) else ""
        block = (f'    <source name="{name}" type="humanmine-items"{version}>\n'
                 f'      <property name="src.data.file" location="{items}"/>\n'
                 f'    </source>\n')
        idx = text.rfind("</sources>")
        if idx < 0:
            raise SystemExit(f"{project}: no </sources>")
        line_start = text.rfind("\n", 0, idx) + 1
        text = text[:line_start] + block + text[line_start:]
        with open(project, "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(priorities, encoding="utf-8") as fh:
        ptext = fh.read()
    keep = [ln for ln in ptext.splitlines() if not re.match(r"^DataSet\.(url|description)\s*=", ln)]
    keep += [f"# DataSet.url/description: the data-source status pages (rdfc2im source_pages.py, {name})",
             f"DataSet.url = {name}, *", f"DataSet.description = {name}, *"]
    with open(priorities, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keep) + "\n")


# ---------------------------------------------------------------- CLI

def main(argv=None):
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pages")
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mappings", help="the stock mapping files (default rdfc2im/data/stock_mappings)")
    d = sub.add_parser("data-set-links")
    d.add_argument("--base-url", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--sources", default="")
    d.add_argument("--stock-sources", default="")
    s = sub.add_parser("add-links-source")
    s.add_argument("--project", required=True)
    s.add_argument("--priorities", required=True)
    s.add_argument("--items", required=True)
    s.add_argument("--name", default="data-set-links")
    a = ap.parse_args(argv)
    if a.cmd == "pages":
        with open(a.manifest, encoding="utf-8") as fh:
            man = json.load(fh)
        for w in write_pages(man, a.out, a.mappings):
            print(w)
    elif a.cmd == "data-set-links":
        pages = data_set_pages(a.stock_sources.replace(",", " ").split(), a.sources.replace(",", " ").split())
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(data_set_links_xml(pages, a.base_url))
        print(f"{a.out}: {len(pages)} data sets")
    else:
        add_links_source(a.project, a.priorities, a.items, a.name)
        print(f"{a.project}: source {a.name} added; {a.priorities}: DataSet.url and DataSet.description first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
