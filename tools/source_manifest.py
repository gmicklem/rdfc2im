#!/usr/bin/env python3
"""source_manifest.py: the build manifest of a hybrid HumanMine build, per data source [im-9n4.42].

Collects, for every source a build loaded, what the data-source status pages (tools/source_pages.py)
show: where each raw file came from (URL, the server's Last-Modified, the release the file states), when
it was fetched (UTC), its size and sha256, its licence, the build's scope and the filter that cut the file
to it, the records in the raw file and the records the filter kept, how many records carry each field
(tools/field_counts.py, cached under the file's sha256), and, with --mine, the objects loaded per class
and data set. It works from the caches, the out/ tree and the build logs alone, so it needs no running
mine; --mine adds the loaded counts.

  source_manifest.py --out out/_mine/source_manifest.json
      [--sources "go ncbigene ..."] [--stock-sources "uniprot go-annotation ..."]
      [--out-root out] [--cache-dir cached_raw_data] [--stock-dir DIR] [--filtered-cache DIR]
      [--logs DIR] [--count-cache DIR] [--max-seconds 300] [--mine URL]
      [--reference-datasets curation/humanmine_2022_datasets.json] [--endpoint-counts SRC ...]
      [--build-name NAME] [--intermine-src DIR] [--trial-home DIR] [--gene-identifiers panel|all]

Where each value comes from (USAGE.md, "Data-source status pages", has the full table):
  url, licence (name, status, URL, date read, quotation, conditions), redistributable
                                    rdfc2im/data/stock_sources.yaml (stock), sources.yaml (RDF), other_licences.yaml (stock reactome)
  last_modified, fetched_at        the raw cache group's META.json (meta last_modified.<id>, saved_at)
  size, sha256, md5                the cached raw file itself (sha256 computed here; md5 from MD5SUMS)
  release                          the file's own header (`release:` in the stock mapping file)
  records_raw, records_kept        field_counts.py over the raw file and over the filtered file the
                                   loader read (the same record definitions as subset_raw.py filter);
                                   the filter's own JSON line, when the build log has one, as filter_log
  loaded (per class, data set)     the mine (--mine): one count query per class and data set
  items (RDF)                      the items XML file rdfc2im wrote (objects per class)

--endpoint-counts SRC asks the RDF source's SPARQL endpoint one COUNT query per mapped predicate of the
root subject (sequential, --sleep seconds apart), for counts over the whole endpoint rather than the
build's extract. Off by default.

Standard library plus PyYAML (already an rdfc2im dependency, read through rdfc2im.stock).
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import yaml  # noqa: E402

import field_counts as fc  # noqa: E402
from rdfc2im import stock as st  # noqa: E402

MANIFEST_VERSION = 1
MAPPINGS_DIR = os.path.join(HERE, "rdfc2im", "data", "stock_mappings")
SOURCES_YAML = os.path.join(HERE, "rdfc2im", "data", "sources.yaml")
GAPS_YAML = os.path.join(HERE, "rdfc2im", "data", "source_gaps.yaml")
USER_AGENT = "rdfc2im-source-pages/1 (data-source status pages)"
csv.field_size_limit(1 << 30)


def log(msg):
    print(f"source_manifest: {msg}", file=sys.stderr)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _git_head(path):
    if not path or not os.path.isdir(path):
        return None
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def load_mapping(name, mappings_dir=MAPPINGS_DIR):
    path = os.path.join(mappings_dir, f"{name}.yaml")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def read_md5sums(gdir):
    out = {}
    p = os.path.join(gdir, "MD5SUMS")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split(None, 1)
                if len(parts) == 2:
                    out[parts[1].strip()] = parts[0]
    return out


def read_group(gdir):
    """META.json and MD5SUMS of a cache group, or None when the group is absent."""
    p = os.path.join(gdir, "META.json")
    if not os.path.exists(p):
        return None
    meta = _read_json(p)
    meta["md5sums"] = read_md5sums(gdir)
    return meta


# ---------------------------------------------------------------- the filter rule in words

_IDS_WORDS = {"uniprot": "UniProt accessions", "entrez": "NCBI Gene (Entrez) ids", "ensembl": "Ensembl gene ids",
              "mgi": "MGI ids", "rgd": "RGD ids", "hpo-diseases": "disease ids", "chromosomes": "chromosome accessions"}


def filter_rule(flt, idcounts):
    """One plain sentence for a stock_sources.yaml filter."""
    if not isinstance(flt, dict):
        return "none: the whole file is loaded"
    ids = flt.get("ids")
    n = idcounts.get(ids)
    what = _IDS_WORDS.get(ids, f"{ids} ids")
    nwhat = f"{n:,} {what}" if isinstance(n, int) else what
    base = {"uniprot": "of the panel genes", "entrez": "of the panel genes", "ensembl": "of the panel genes",
            "mgi": "of the mouse genes on the panel's PANTHER rows", "rgd": "of the rat genes on the panel's PANTHER rows",
            "hpo-diseases": "of the diseases the kept genes_to_phenotype rows name",
            "chromosomes": "of the 24 chromosomes the loader maps"}.get(ids, "")
    fmt = flt.get("format")
    if fmt == "gaf":
        s = f"rows whose column 2 is one of the {nwhat} {base} (isoforms match on their base accession)"
    elif fmt == "gff3":
        s = (f"rows whose Dbxref GeneID is one of the {nwhat} {base}, with every row under them "
             "(transcripts, exons, CDS) and their parents; every ##sequence-region line is kept")
    elif fmt == "uniprot-xml":
        s = f"entries with an accession among the {nwhat} {base}"
    elif fmt == "fasta":
        s = f"records whose header accession (or its base accession) is one of the {nwhat} {base}"
    elif fmt == "psi-xml":
        dbs = ", ".join(flt.get("xref_db") or []) or "any"
        s = (f"interactions with at least one participant whose interactor has a {dbs} xref among the {nwhat} "
             f"{base}, with the interactors and experiments they use; negative interactions dropped")
    elif fmt == "tab":
        cols = str(flt.get("column", "1"))
        which = f"column {cols}" if "," not in cols else "columns " + " or ".join(cols.split(","))
        s = f"rows whose {which} holds one of the {nwhat} {base}"
        kh = st.header_lines(flt)
        if kh:
            s += "; the first line (header) kept" if kh == 1 else f"; the first {kh} lines (header) kept"
    else:
        s = f"{fmt} filter on {nwhat}"
    return re.sub(r"\s+", " ", s).strip() + "."


# ---------------------------------------------------------------- release

def _first_lines(path, unpack, member, n=200):
    out = []
    try:
        for _name, fh in fc.iter_inputs(path, unpack, member):
            for line in fc._lines(fh, fc._Budget(None)):
                out.append(line.rstrip("\r\n"))
                if len(out) >= n:
                    break
            break
    except Exception as e:  # noqa: BLE001 - a release probe never fails the manifest
        log(f"release probe {path}: {e}")
    return out


def release_of(spec, raw_path, unpack, member, url, members):
    """The release/version the file itself states, from the mapping file's `release:` (a list of probes:
    {from: line, pattern, lines}, {from: member_name, pattern}, {from: url, pattern}); None when none matches."""
    if not spec:
        return None
    probes = spec if isinstance(spec, list) else [spec]
    found = []
    lines = None
    for p in probes:
        rx = re.compile(p["pattern"])
        src = p.get("from", "line")
        if src == "line":
            if lines is None:
                lines = _first_lines(raw_path, unpack, member, int(p.get("lines", 200)))
            for ln in lines:
                m = rx.search(ln)
                if m:
                    found.append((p.get("label", ""), m.group(1).strip()))
                    break
        elif src == "member_name":
            for mname in members or []:
                m = rx.search(mname)
                if m:
                    found.append((p.get("label", ""), m.group(1)))
                    break
        elif src == "url" and url:
            m = rx.search(url)
            if m:
                found.append((p.get("label", ""), m.group(1)))
    if not found:
        return None
    return "; ".join(f"{lab} {val}".strip() for lab, val in found)


# ---------------------------------------------------------------- build logs

_FILTER_CMD_RE = re.compile(r"subset_raw\.py filter (.*)$")


def filter_logs(logs_dir):
    """{out path: summary dict} from every `subset_raw.py filter ... --out OUT` line followed by its JSON
    summary line, in the build logs of logs_dir (later logs win)."""
    out = {}
    if not logs_dir or not os.path.isdir(logs_dir):
        return out
    for p in sorted(glob.glob(os.path.join(logs_dir, "build-*subset_stock_data*.log"))):
        pending = None
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _FILTER_CMD_RE.search(line)
                if m:
                    words = m.group(1).split()
                    pending = words[words.index("--out") + 1] if "--out" in words else None
                    continue
                if pending and line.startswith("{"):
                    try:
                        out[pending] = dict(json.loads(line), log=os.path.basename(p))
                    except ValueError:
                        pass
                    pending = None
    return out


# ---------------------------------------------------------------- the mine

class Mine:
    """Read-only path-query counts against an InterMine web service."""

    def __init__(self, base, timeout=120):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.requests = 0

    def _get(self, path, data=None):
        self.requests += 1
        req = urllib.request.Request(self.base + path, data=data, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8")

    def count(self, cls, ds_name):
        q = (f'<query model="genomic" view="{cls}.id"><constraint path="{cls}.dataSets.name" op="=" '
             f'value="{_xml_attr(ds_name)}"/></query>')
        body = urllib.parse.urlencode({"query": q, "format": "count"}).encode()
        return int(self._get("/service/query/results", body).strip())

    def model(self):
        return json.loads(self._get("/service/model?format=json"))["model"]

    def version(self):
        try:
            return {"api": self._get("/service/version").strip(), "release": self._get("/service/version/release").strip()}
        except OSError:
            return None

    def datasets(self):
        q = ('<query model="genomic" view="DataSet.name DataSet.version DataSet.url DataSet.description '
             'DataSet.licence DataSet.dataSource.name DataSet.dataSource.url" sortOrder="DataSet.name asc">'
             '<join path="DataSet.dataSource" style="OUTER"/></query>')
        body = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
        return [dict(zip(("name", "version", "url", "description", "licence", "data_source", "data_source_url"), r))
                for r in json.loads(self._get("/service/query/results", body))["results"]]


def _xml_attr(s):
    return (str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"))


def dataset_classes(model):
    return {c for c, d in model["classes"].items() if "dataSets" in d.get("collections", {})}


def leaf_total(model):
    """Objects in the mine: the counts of the classes no other class extends, summed (a class's count
    includes its subclasses')."""
    cls = model["classes"]
    parents = {p for d in cls.values() for p in d.get("extends", [])}
    return sum(int(d.get("count") or 0) for c, d in cls.items() if c not in parents)


def loaded_counts(mine, model, data_sets, classes):
    """{data set: {class: n}} for the classes that have a dataSets collection (others cannot be told
    apart by data set), with no zero rows."""
    have = dataset_classes(model)
    out = {}
    for ds in data_sets:
        row = {}
        for c in sorted(set(classes)):
            if c in have:
                n = mine.count(c, ds)
                if n:
                    row[c] = n
        out[ds] = row
    return out


def unlinked_counts(model, classes):
    """{class: objects in the whole mine} for the classes a source writes that have no dataSets collection:
    those cannot be counted per data set, so the page gives the mine's total and says so."""
    have = dataset_classes(model)
    return {c: int(model["classes"][c].get("count") or 0) for c in sorted(set(classes))
            if c in model["classes"] and c not in have}


# ---------------------------------------------------------------- stock sources

def _input_path(e, f, name, stock_dir, filtered_cache, raw):
    """(path, kind) of the file the loader read: the filtered file (from the filtered cache group, else the
    stock working area), the unpacked whole file, or the raw file itself."""
    flt = f.get("filter", "none")
    sname = f.get("stage_as") or st.raw_name(f)
    if flt != "none":
        for root in (os.path.join(filtered_cache or "", f"stock-{name}", "data", f["id"]),
                     os.path.join(stock_dir, "cache", f"stock-{name}", "data", f["id"]),
                     os.path.join(stock_dir, "subset", name, f["id"])):
            if not root or not os.path.isdir(root):
                continue
            p = os.path.join(root, sname)
            if f.get("unpack") == "zip" and (f.get("filter") or {}).get("format") == "psi-xml":
                return root, "filtered"      # one filtered file per zip member
            if os.path.exists(p):
                return p, "filtered"
        return None, "filtered"
    if f.get("repo_file"):
        return os.path.join(HERE, "rdfc2im", "data", f["repo_file"]), "repository"
    if f.get("unpack") or raw.endswith(".gz"):
        p = os.path.join(stock_dir, "whole", name, f["id"], sname)
        return (p if os.path.exists(p) else None), "whole"
    return raw, "as is"


def _count_spec(mf, unpack, member):
    return fc.spec_of(mf["format"], unpack, member, mf.get("comment"), mf.get("skip_lines") or 0,
                      mf.get("header_line"), mf.get("record_key"))


def stock_entry(name, table, args, idcounts, flogs, mine, model):
    e = table[name]
    mp = load_mapping(name, args.mappings) or {}
    mfiles = {f["id"]: f for f in (mp.get("files") or [])}
    raw_group = os.path.join(args.stock_dir, "cache", f"stock-raw-{name}")
    group = read_group(raw_group)
    filtered = read_group(os.path.join(args.filtered_cache or "", f"stock-{name}")) if args.filtered_cache else None
    files = []
    for f in e["files"]:
        fid = f["id"]
        mf = mfiles.get(fid) or {}
        rec = {"id": fid, "url": f.get("url"), "raw_name": st.raw_name(f) if not f.get("repo_file") else f["repo_file"],
               "unpack": f.get("unpack"), "member": f.get("member"), "stage_as": f.get("stage_as"),
               "table_size": f.get("size"), "table_last_modified": f.get("last_modified"), "verified": f.get("verified")}
        flt = f.get("filter", "none")
        rec["filter"] = flt if isinstance(flt, dict) else "none"
        rec["filter_rule"] = filter_rule(flt, idcounts)
        if f.get("repo_file"):
            raw = os.path.join(HERE, "rdfc2im", "data", f["repo_file"])
            rec["origin"] = "rdfc2im repository file (written by hand)"
        else:
            raw = os.path.join(raw_group, "data", st.raw_name(f))
            rec["origin"] = "download"
        if group and not f.get("repo_file"):
            m = group.get("meta", {})
            rec["fetched_at"] = group.get("saved_at")
            rec["last_modified"] = m.get(f"last_modified.{fid}")
            rec["cached_url"] = m.get(f"url.{fid}")
            rec["md5"] = group["md5sums"].get(f"data/{st.raw_name(f)}")
        if os.path.exists(raw):
            rec["raw_path"] = raw
            rec["size"] = os.path.getsize(raw)
            rec["sha256"] = fc.sha256_file(raw, args.count_cache)
        else:
            rec["raw_path"] = None
            log(f"{name}/{fid}: raw file {raw} not found")
        members = None
        if rec["raw_path"] and f.get("unpack") == "zip":
            import zipfile
            with zipfile.ZipFile(raw) as z:
                infos = [i for i in z.infolist() if not i.is_dir() and fc._match(i.filename, f.get("member"))]
                members = sorted(i.filename for i in infos)
                rec["uncompressed_bytes"] = sum(i.file_size for i in infos)
            rec["members"] = members if len(members) <= 20 else members[:3] + [f"... {len(members)} members"]
        if rec["raw_path"]:
            rec["release"] = release_of(mf.get("release"), raw, f.get("unpack"), f.get("member"), f.get("url"), members)
        inp, kind = _input_path(e, f, name, args.stock_dir, args.filtered_cache, raw)
        rec["input_kind"], rec["input_path"] = kind, inp
        if mf.get("format") and rec["raw_path"]:
            try:
                rc = fc.count_cached(raw, _count_spec(mf, f.get("unpack"), f.get("member")), args.count_cache,
                                     args.max_seconds, log)
                rec["counts_raw"] = _slim(rc)
                rec["records_raw"] = rc["records"]
            except (fc.CountError, OSError, Exception) as ex:  # noqa: BLE001
                log(f"{name}/{fid}: counting the raw file failed: {ex}")
                rec["counts_error"] = str(ex)
            if inp and kind == "filtered" and os.path.exists(inp):
                member = "*.xml" if os.path.isdir(inp) else None
                rk = fc.count_cached(inp, _count_spec(mf, None, member), args.count_cache, args.max_seconds, log)
                rec["counts_input"] = _slim(rk)
                rec["records_kept"] = rk["records"]
                rec["input_sha256"] = rk.get("sha256")
            elif kind in ("whole", "as is", "repository"):
                rec["records_kept"] = rec.get("records_raw")
        logged = [v for k, v in flogs.items() if f"/subset/{name}/{fid}" in k]
        if logged:
            rec["filter_log"] = logged[-1]
        files.append(rec)
    out = {"id": f"stock:{name}", "kind": "stock", "name": name, "type": e["type"], "jar": e["jar"],
           "licence": e.get("licence"), "licence_info": st.licence_info(e),
           "redistributable": bool(e.get("redistributable")), "data_dir": e.get("data_dir"), "properties": e.get("properties") or {},
           "mapping": _mapping_summary(mp, name), "files": files,
           "raw_group": {"path": raw_group, "saved_at": (group or {}).get("saved_at")},
           "filtered_group": ({"saved_at": filtered.get("saved_at"), "meta": filtered.get("meta")} if filtered else None)}
    if mine is not None and mp.get("data_sets"):
        out["loaded"] = loaded_counts(mine, model, mp["data_sets"], mp.get("writes") or [])
        out["loaded_unlinked"] = unlinked_counts(model, mp.get("writes") or [])
    return out


def _slim(res):
    keep = ("format", "records", "keys", "names", "inputs", "complete", "bytes_read", "sha256", "seconds", "peak_rss_mb")
    return {k: res.get(k) for k in keep}


def _mapping_summary(mp, name):
    if not mp:
        return {"present": False}
    return {"present": True, "file": f"rdfc2im/data/stock_mappings/{name}.yaml", "loader": mp.get("loader"),
            "basis": mp.get("basis"), "data_source": mp.get("data_source"), "data_sets": mp.get("data_sets") or [],
            "writes": mp.get("writes") or [], "partial": bool(mp.get("partial"))}


# stock reactome (UniProt2Reactome.txt): built by build_stock_sources for every build with reactome, its data
# in the RDF raw-data cache group reactome-uniprot-map, not in stock_sources.yaml
def reactome_entry(args, mine, model):
    mp = load_mapping("reactome", args.mappings) or {}
    gdir = os.path.join(args.cache_dir, "reactome-uniprot-map")
    group = read_group(gdir)
    if not group:
        return None
    mf = (mp.get("files") or [{}])[0]
    rlic = st.other_licences()["reactome"]
    raw = os.path.join(gdir, "data", "UniProt2Reactome.txt")
    url = group.get("meta", {}).get("url")
    rec = {"id": mf.get("id", "map"), "url": url, "cached_url": url, "raw_name": os.path.basename(raw),
           "fetched_at": group.get("saved_at"), "last_modified": None, "origin": "download",
           "md5": group["md5sums"].get("data/UniProt2Reactome.txt"), "filter": "none",
           "filter_rule": "none: the whole file is staged; the converter keeps the rows of the organisms in "
                          "reactome.organisms (9606 in this build).", "input_kind": "as is", "input_path": raw}
    if os.path.exists(raw):
        rec.update(raw_path=raw, size=os.path.getsize(raw), sha256=fc.sha256_file(raw, args.count_cache))
        rec["release"] = release_of(mp.get("release") or (mf.get("release")), raw, None, None, url, None)
        if mf.get("format"):
            rc = fc.count_cached(raw, _count_spec(mf, None, None), args.count_cache, args.max_seconds, log)
            rec["counts_raw"] = _slim(rc)
            rec["records_raw"] = rec["records_kept"] = rc["records"]
    out = {"id": "stock:reactome", "kind": "stock", "name": "reactome", "type": "reactome", "jar": "intermine",
           "licence": rlic.get("licence"), "licence_info": st.licence_info(rlic),
           "redistributable": bool(rlic.get("redistributable")), "data_dir": "reactome/current",
           "properties": {"reactome.organisms": "9606"}, "mapping": _mapping_summary(mp, "reactome"), "files": [rec],
           "raw_group": {"path": gdir, "saved_at": group.get("saved_at")}, "filtered_group": None,
           "levels": group.get("meta", {}).get("levels")}
    if mine is not None and mp.get("data_sets"):
        out["loaded"] = loaded_counts(mine, model, mp["data_sets"], mp.get("writes") or [])
        out["loaded_unlinked"] = unlinked_counts(model, mp.get("writes") or [])
    return out


# ---------------------------------------------------------------- RDF sources

def read_tsv_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader((ln for ln in fh if not ln.startswith("#")), delimiter="\t"))
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:]]


def sssom_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines()
    curie = {}
    in_map = False
    for ln in lines:
        if not ln.startswith("#"):
            break
        if ln.startswith("#curie_map:"):
            in_map = True
            continue
        if in_map:
            m = re.match(r"^#\s+([A-Za-z0-9_-]+):\s+(\S+)", ln)
            if m:
                curie[m.group(1)] = m.group(2)
            else:
                in_map = False
    body = [ln for ln in lines if not ln.startswith("#")]
    rows = list(csv.DictReader(body, delimiter="\t"))
    return rows, curie


def table_column_counts(path):
    """{column: {"with": rows with a value, "ids": distinct first-column values with one}, "_rows": n}."""
    with open(path, encoding="utf-8", newline="") as fh:
        r = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        head = next(r, None)
        if not head:
            return {"_rows": 0}
        head = [h.lstrip("?") for h in head]     # SPARQL TSV results name the columns ?var
        withs = [0] * len(head)
        ids = [set() for _ in head]
        n = 0
        for row in r:
            n += 1
            key = row[0] if row else ""
            for i, v in enumerate(row[:len(head)]):
                if v.strip():
                    withs[i] += 1
                    if len(ids[i]) < 5_000_000:
                        ids[i].add(key)
    out = {h: {"with": withs[i], "ids": len(ids[i])} for i, h in enumerate(head)}
    out["_rows"] = n
    return out


_ITEM_CLASS_RE = re.compile(r'<item id="[^"]*" class="([^"]+)"')


def items_per_class(path):
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _ITEM_CLASS_RE.search(line)
            if m:
                for c in m.group(1).split():
                    out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items()))


def query_meta(out_dir):
    """{table: {endpoint, from: [graphs], type_triple: (var, type), prefixes: [lines]}} from queries/*.sparql."""
    res = {}
    for p in sorted(glob.glob(os.path.join(out_dir, "queries", "*.sparql"))):
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        ep = re.search(r"^# Endpoint:\s*(\S+)", text, re.M)
        tt = re.search(r"^\s*\?(\w+) a (\S+) \.", text, re.M)
        res[os.path.basename(p)[:-len(".sparql")]] = {
            "endpoint": ep.group(1) if ep else None, "from": re.findall(r"^FROM <([^>]+)>", text, re.M),
            "type_triple": [tt.group(1), tt.group(2)] if tt else None,
            "prefixes": re.findall(r"^PREFIX .*$", text, re.M)}
    return res


def rdf_entry(src, args, scfg, mine, model):
    out_dir = os.path.join(args.out_root, src)
    gdir = os.path.join(args.cache_dir, src)
    group = read_group(gdir)
    rows, curie = sssom_rows(os.path.join(out_dir, "mapping_predicates.sssom.tsv")) \
        if os.path.exists(os.path.join(out_dir, "mapping_predicates.sssom.tsv")) else ([], {})
    cols = read_tsv_rows(os.path.join(out_dir, "columns.tsv")) if os.path.exists(os.path.join(out_dir, "columns.tsv")) else []
    qmeta = query_meta(out_dir)
    tables = {}
    if group:
        for rel, md5 in sorted(group["md5sums"].items()):
            p = os.path.join(gdir, rel)
            if not os.path.exists(p):
                continue
            t = os.path.basename(rel)[:-4] if rel.endswith(".tsv") else os.path.basename(rel)
            tables[t] = {"file": rel, "size": os.path.getsize(p), "md5": md5,
                         "sha256": fc.sha256_file(p, args.count_cache),
                         "columns": table_column_counts(p) if rel.endswith(".tsv") else None}
    items = os.path.join(out_dir, "items", f"{src}.xml")
    report = {}
    rp = os.path.join(out_dir, "report.txt")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as fh:
            for ln in fh:
                k, sep, v = ln.partition(":")
                if sep and k.strip() in ("endpoint", "rows", "subjects", "tables with a query"):
                    report[k.strip()] = v.strip()
    ent = {"id": f"rdf:{src}", "kind": "rdf", "name": src, "loader": "rdfc2im (items XML, humanmine-items type)",
           "data_source": {"name": scfg.get("data_source_name"), "url": scfg.get("data_source_url")},
           "licence": scfg.get("licence"), "licence_info": st.licence_info(scfg),
           "data_set": scfg.get("data_set_title"), "replaces": scfg.get("replaces") or [],
           "alongside": scfg.get("alongside") or [],
           "cache_group": {"path": gdir, "saved_at": (group or {}).get("saved_at"), "meta": (group or {}).get("meta"),
                           "bytes": (group or {}).get("bytes"), "files": (group or {}).get("files")},
           "endpoint": report.get("endpoint") or next((q["endpoint"] for q in qmeta.values() if q["endpoint"]), None),
           "graphs": sorted({g for q in qmeta.values() for g in q["from"]}), "report": report,
           "tables": tables, "mapping_rows": rows, "curie_map": curie,
           "columns": [{k: c.get(k) for k in ("table", "column", "variable", "im_class", "im_field", "via", "status")}
                       for c in cols],
           "items": items_per_class(items) if os.path.exists(items) else None,
           "items_path": os.path.relpath(items, args.out_root) if os.path.exists(items) else None}
    if src in (args.endpoint_counts or []):
        ent["endpoint_counts"] = endpoint_counts(ent, qmeta, args.sleep)
    if mine is not None and scfg.get("data_set_title"):
        classes = {c["im_class"] for c in cols if c.get("im_class")}
        ent["loaded"] = loaded_counts(mine, model, [scfg["data_set_title"]], classes)
        ent["loaded_unlinked"] = unlinked_counts(model, classes)
    return ent


def _expand(curie_or_iri, curie_map):
    if curie_or_iri.startswith("http"):
        return f"<{curie_or_iri}>"
    pre, _, local = curie_or_iri.partition(":")
    if pre in curie_map:
        return f"<{curie_map[pre]}{local}>"
    return curie_or_iri


def endpoint_counts(ent, qmeta, sleep):
    """One COUNT query per mapped predicate of the root subject over the whole endpoint graph(s),
    sequential and `sleep` seconds apart. {predicate: {values, with, seconds} | {error}}."""
    main = qmeta.get("main") or next(iter(qmeta.values()), None)
    if not main or not main["type_triple"] or not main["endpoint"]:
        return {"_error": "no main query with a type triple"}
    root_subject = next((r.get("ext_subject") for r in ent["mapping_rows"] if r.get("ext_table") == "main"), None)
    out = {"_endpoint": main["endpoint"], "_graphs": main["from"], "_type": main["type_triple"][1]}
    preds = []
    for r in ent["mapping_rows"]:
        p = r.get("ext_predicate") or ""
        if p.startswith("-") or r.get("ext_subject") != root_subject or p in preds:
            continue
        preds.append(p)
    for p in preds:
        q = "\n".join(main["prefixes"] + [
            "SELECT (COUNT(?o) AS ?values) (COUNT(DISTINCT ?s) AS ?with)"] +
            [f"FROM <{g}>" for g in main["from"]] +
            [f"WHERE {{ ?s a {main['type_triple'][1]} . ?s {_expand(p, ent['curie_map'])} ?o . }}"])
        t0 = time.time()
        try:
            body = urllib.parse.urlencode({"query": q}).encode()
            req = urllib.request.Request(main["endpoint"], data=body, headers={
                "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                b = json.loads(r.read().decode("utf-8"))["results"]["bindings"][0]
            out[p] = {"values": int(b["values"]["value"]), "with": int(b["with"]["value"]),
                      "seconds": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            out[p] = {"error": str(e)[:200], "seconds": round(time.time() - t0, 1)}
        log(f"endpoint count {ent['name']} {p}: {out[p]}")
        time.sleep(sleep)
    return out


# ---------------------------------------------------------------- build identity

def build_identity(args, idsets, mine, model):
    b = {"name": args.build_name, "gene_identifiers": args.gene_identifiers,
         "panel_genes": (idsets or {}).get("counts", {}).get("entrez"),
         "panel_ids": (idsets or {}).get("counts"), "genes_md5": (idsets or {}).get("genes_md5"),
         "rdfc2im_commit": args.rdfc2im_commit or _git_head(HERE)}
    if args.intermine_src:
        toml = os.path.join(args.intermine_src, "gradle", "libs.versions.toml")
        if os.path.exists(toml):
            with open(toml, encoding="utf-8") as fh:
                m = re.search(r'^intermine\s*=\s*"([^"]+)"', fh.read(), re.M)
            b["intermine_version"] = m.group(1) if m else None
        b["intermine_commit"] = _git_head(args.intermine_src)
    if args.trial_home:
        b["humanmine_bio_sources_commit"] = _git_head(os.path.join(args.trial_home, "humanmine-bio-sources"))
        b["humanmine_commit"] = _git_head(os.path.join(args.trial_home, "humanmine"))
    if args.logs and os.path.isdir(args.logs):
        tt = sorted(glob.glob(os.path.join(args.logs, "build-*.timing.tsv")), key=os.path.getmtime)
        if tt:
            b["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(tt[-1])))
        b["logs"] = args.logs
    if mine is not None:
        b["mine"] = mine.base
        b["mine_version"] = mine.version()
        b["mine_total_objects"] = leaf_total(model)
        human = None
        try:
            q = ('<query model="genomic" view="Gene.id"><constraint path="Gene.organism.taxonId" op="=" '
                 'value="9606"/></query>')
            human = int(mine._get("/service/query/results",
                                  urllib.parse.urlencode({"query": q, "format": "count"}).encode()).strip())
        except (OSError, ValueError):
            pass
        b["mine_human_genes"] = human
        b["mine_classes"] = {c: d.get("count") for c, d in sorted(model["classes"].items()) if d.get("count")}
    return b


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--sources", default="")
    ap.add_argument("--stock-sources", default="")
    ap.add_argument("--no-stock-reactome", action="store_true",
                    help="the build did not load stock reactome (it does whenever reactome is in --sources)")
    ap.add_argument("--out-root", default=os.path.join(HERE, "out"))
    ap.add_argument("--cache-dir", default=os.path.join(HERE, "cached_raw_data"))
    ap.add_argument("--stock-dir")
    ap.add_argument("--filtered-cache")
    ap.add_argument("--stock-table", default=st.TABLE)
    ap.add_argument("--mappings", default=MAPPINGS_DIR)
    ap.add_argument("--logs")
    ap.add_argument("--count-cache")
    ap.add_argument("--max-seconds", type=float, default=300)
    ap.add_argument("--mine")
    ap.add_argument("--reference-datasets")
    ap.add_argument("--endpoint-counts", nargs="*", default=[])
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--build-name", default="")
    ap.add_argument("--rdfc2im-commit")
    ap.add_argument("--intermine-src")
    ap.add_argument("--trial-home")
    ap.add_argument("--gene-identifiers", default="panel", choices=("panel", "all"))
    a = ap.parse_args(argv)
    stock_names = a.stock_sources.replace(",", " ").split()
    rdf_names = a.sources.replace(",", " ").split()
    if stock_names and not a.stock_dir:
        ap.error("--stock-sources needs --stock-dir")
    a.count_cache = a.count_cache or (os.path.join(a.stock_dir, "field-counts") if a.stock_dir else None)
    table = st.load_table(a.stock_table)
    unknown = [n for n in stock_names if n not in table]
    if unknown:
        ap.error("unknown stock source(s): " + ", ".join(unknown))
    with open(SOURCES_YAML, encoding="utf-8") as fh:
        scfg = yaml.safe_load(fh) or {}
    idsets = None
    if a.stock_dir and os.path.exists(os.path.join(a.stock_dir, "idsets", "idsets.json")):
        idsets = _read_json(os.path.join(a.stock_dir, "idsets", "idsets.json"))
    idcounts = dict((idsets or {}).get("counts", {}))
    if a.stock_dir:
        for k in ("mgi", "rgd", "hpo-diseases", "chromosomes"):
            p = os.path.join(a.stock_dir, "idsets", f"{k}.txt")
            if os.path.exists(p):
                idcounts[k] = len(st_read_ids(p))
    mine = model = None
    if a.mine:
        mine = Mine(a.mine)
        try:
            model = mine.model()
        except OSError as e:
            log(f"--mine {a.mine}: {e}; the loaded counts are left out")
            mine = None
    flogs = filter_logs(a.logs)
    sources = []
    for n in rdf_names:
        log(f"rdf {n}")
        sources.append(rdf_entry(n, a, scfg.get(n) or {}, mine, model))
    if "reactome" in rdf_names and not a.no_stock_reactome:
        r = reactome_entry(a, mine, model)
        if r:
            sources.append(r)
    for n in stock_names:
        log(f"stock {n}")
        sources.append(stock_entry(n, table, a, idcounts, flogs, mine, model))
    man = {"manifest_version": MANIFEST_VERSION, "build": build_identity(a, idsets, mine, model),
           "sources": sources}
    if a.reference_datasets and os.path.exists(a.reference_datasets):
        man["reference"] = _read_json(a.reference_datasets)
    if mine is not None:
        man["build"]["mine_datasets"] = mine.datasets()
        man["build"]["mine_requests"] = mine.requests
    if os.path.exists(GAPS_YAML):
        with open(GAPS_YAML, encoding="utf-8") as fh:
            man["gaps"] = (yaml.safe_load(fh) or {}).get("gaps") or {}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out + ".part", "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(a.out + ".part", a.out)
    log(f"wrote {a.out}: {len(sources)} sources")
    return 0


def st_read_ids(path):
    with open(path, encoding="utf-8") as fh:
        return {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}


if __name__ == "__main__":
    sys.exit(main())
