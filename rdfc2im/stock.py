"""Stock InterMine / HumanMine sources loaded beside the rdfc2im ones (the hybrid testbed, epic im-9n4).

The table is rdfc2im/data/stock_sources.yaml: one entry per HumanMine project.xml <source> name,
with where its loader jar comes from, where HumanMine keeps its data, the upstream files, how each
file is cut down to the gene panel, and whether the data may be redistributed. tools/full-build.sh
reads it only through `rdfc2im stock ...` (cli.run_stock), so bash never parses YAML.

  stock list                 every entry: name, type, jar origin, redistributable
  stock check NAME...        validate a --stock-sources list; prints it in HumanMine's project.xml order
  stock jars NAME...         one row per loader jar to build or check
  stock files NAME...        one row per upstream file: where it comes from, how it is filtered, where
                             it is staged
  stock postprocess NAME...  the postprocesses the selection needs, in HumanMine's order (plan 50 row 12)
  stock meta NAME            `--meta k=v` words for the source's filtered cache group

Rows are tab-separated with '-' for an empty field (bash `read` collapses empty tab fields).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

import yaml
from lxml import etree

HERE = os.path.dirname(__file__)
TABLE = os.path.join(HERE, "data", "stock_sources.yaml")
# HumanMine's own project.xml names every data path under this root; full-build.sh rewrites it to
# RDFC2IM_DATA_ROOT afterwards, as it already does for the rdfc2im sources.
HUMANMINE_DATA_ROOT = "/micklem/data"
JAR_ORIGINS = ("intermine", "humanmine-bio-sources")
# humanmine-bio-sources' Gradle project version (its build.gradle); every one of its entries in
# HumanMine's project.xml carries version="4.3.0", and the dbmodel plugin resolves that version.
HUMANMINE_BIO_VERSION = "4.3.0"
# tools/subset_raw.py's interface (plan 50, T0.2)
FORMATS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "gene_info")
NEEDS_IDS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab")
ID_KINDS = ("entrez", "ensembl", "uniprot", "symbol", "none")
UNPACK = ("zip", "tar.gz")
DATA_PROPERTIES = ("src.data.dir", "src.data.file")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GLOB_CHARS = set("*?[")


class StockError(Exception):
    """A table or selection problem. The message is meant for the build log as it stands."""


# ------------------------------------------------------------------ table

def load_table(path: Optional[str] = None) -> Dict[str, dict]:
    """The table, validated. Raises StockError listing every problem found."""
    with open(path or TABLE, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    table = doc.get("sources") or {}
    problems = validate_table(table)
    if problems:
        raise StockError("stock_sources.yaml: " + "; ".join(problems))
    return table


def validate_table(table: Dict[str, dict]) -> List[str]:
    out: List[str] = []
    if not isinstance(table, dict) or not table:
        return ["no `sources:` mapping"]
    for name, e in table.items():
        where = f"{name}"
        if not NAME_RE.match(str(name)):
            out.append(f"{where}: bad source name")
        if not isinstance(e, dict):
            out.append(f"{where}: entry is not a mapping")
            continue
        if not e.get("type") or not NAME_RE.match(str(e["type"])):
            out.append(f"{where}: `type` (the project.xml source type) is missing or malformed")
        if e.get("jar") not in JAR_ORIGINS:
            out.append(f"{where}: `jar` must be one of {', '.join(JAR_ORIGINS)}")
        if not isinstance(e.get("redistributable"), bool):
            out.append(f"{where}: `redistributable` must be true or false")
        if not e.get("licence"):
            out.append(f"{where}: `licence` is required (say 'unknown' if it is)")
        local = e.get("local_copy", "optional")
        if local not in ("optional", "required"):
            out.append(f"{where}: `local_copy` must be optional or required")
        if e.get("redistributable") is False and local != "required":
            out.append(f"{where}: redistributable: false needs local_copy: required (D-7: local copies only)")
        prop = e.get("data_property", "src.data.dir")
        if prop not in DATA_PROPERTIES:
            out.append(f"{where}: `data_property` must be one of {', '.join(DATA_PROPERTIES)}")
        ddir = e.get("data_dir")
        if not ddir or str(ddir).startswith("/") or ".." in str(ddir).split("/"):
            out.append(f"{where}: `data_dir` must be a relative path under {HUMANMINE_DATA_ROOT}")
        if prop == "src.data.file" and not e.get("data_file"):
            out.append(f"{where}: data_property src.data.file needs `data_file`")
        for key in ("after", "needs", "postprocess"):
            v = e.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                out.append(f"{where}: `{key}` must be a list of names")
        for n in e.get("needs", []) or []:
            if n not in table:
                out.append(f"{where}: needs '{n}', which is not in the table")
        if not isinstance(e.get("properties", {}) or {}, dict):
            out.append(f"{where}: `properties` must be a mapping")
        files = e.get("files")
        if not isinstance(files, list) or not files:
            out.append(f"{where}: `files` must be a non-empty list")
            continue
        seen = set()
        for f in files:
            if not isinstance(f, dict):
                out.append(f"{where}: a file entry is not a mapping")
                continue
            fid = f.get("id")
            fw = f"{where}/{fid}"
            if not fid or not FILE_ID_RE.match(str(fid)):
                out.append(f"{where}: file without a well-formed `id`")
            elif fid in seen:
                out.append(f"{fw}: duplicate file id")
            seen.add(fid)
            url = f.get("url")
            if url is None:
                if local != "required":
                    out.append(f"{fw}: no `url`, so the source needs local_copy: required")
                if not f.get("raw_name"):
                    out.append(f"{fw}: without a url, `raw_name` (the local file name) is required")
            elif not re.match(r"^https?://", str(url)):
                out.append(f"{fw}: `url` must be http(s)")
            if not isinstance(f.get("verified", False), bool):
                out.append(f"{fw}: `verified` must be true or false")
            unpack = f.get("unpack")
            member = f.get("member")
            if unpack is not None and unpack not in UNPACK:
                out.append(f"{fw}: `unpack` must be one of {', '.join(UNPACK)}")
            if unpack and not member:
                out.append(f"{fw}: unpack needs `member` (a name or glob inside the archive)")
            if member and not unpack:
                out.append(f"{fw}: `member` without `unpack`")
            multi = bool(member) and bool(GLOB_CHARS & set(str(member)))
            if not f.get("stage_as") and not multi:
                out.append(f"{fw}: `stage_as` (the file name the converter expects) is required")
            if f.get("stage_as") and ("/" in str(f["stage_as"]) or str(f["stage_as"]).endswith(".gz")):
                out.append(f"{fw}: `stage_as` is a plain file name (no '/', no .gz: the loaders read plain text)")
            flt = f.get("filter", "none")
            if flt != "none":
                if not isinstance(flt, dict):
                    out.append(f"{fw}: `filter` must be none or a mapping")
                    continue
                fmt, ids = flt.get("format"), flt.get("ids", "none")
                if fmt not in FORMATS:
                    out.append(f"{fw}: filter format must be one of {', '.join(FORMATS)}")
                if ids not in ID_KINDS:
                    out.append(f"{fw}: filter ids must be one of {', '.join(ID_KINDS)}")
                if fmt in NEEDS_IDS and ids == "none":
                    out.append(f"{fw}: format {fmt} filters by ids, so `ids` cannot be none")
                if fmt == "tab" and not flt.get("column"):
                    out.append(f"{fw}: format tab needs `column`")
                if flt.get("column") and not re.match(r"^\d+(,\d+)*$", str(flt["column"])):
                    out.append(f"{fw}: `column` is 1-based numbers, comma separated")
                if multi:
                    out.append(f"{fw}: a member glob unpacks several files; only a single file can be filtered")
    return out


def _row(*fields) -> str:
    return "\t".join("-" if f in (None, "") else str(f) for f in fields)


# ------------------------------------------------------------------ selection

def parse_names(words: Iterable[str]) -> List[str]:
    out: List[str] = []
    for w in words:
        out.extend(x for x in re.split(r"[\s,]+", w) if x)
    return out


def project_order(project_xml: str) -> List[str]:
    """Source names in HumanMine's project.xml, in order."""
    root = etree.parse(project_xml).getroot()
    return [s.get("name") for s in root.iter("source")]


def replaced_by(rdf_sources: Iterable[str], sources_cfg: dict) -> Dict[str, List[str]]:
    """HumanMine source name -> the rdfc2im sources (humanmine-<src>) replacing it in this build."""
    out: Dict[str, List[str]] = {}
    for s in rdf_sources:
        for r in (sources_cfg.get(s) or {}).get("replaces") or []:
            out.setdefault(r, []).append(f"humanmine-{s}")
    return out


def local_path(local_dir: Optional[str], name: str, f: dict) -> Optional[str]:
    """The local copy of one file: <local_dir>/<source>/<raw name>, when it exists."""
    if not local_dir:
        return None
    p = os.path.join(local_dir, name, raw_name(f))
    return p if os.path.isfile(p) else None


def raw_name(f: dict) -> str:
    return f.get("raw_name") or os.path.basename(str(f["url"]).split("?", 1)[0])


def select(table: Dict[str, dict], names: List[str], project_xml: Optional[str] = None,
           rdf_sources: Iterable[str] = (), sources_cfg: Optional[dict] = None,
           local_dir: Optional[str] = None, taxa: Iterable[str] = ("9606",)) -> Tuple[List[str], List[str]]:
    """Validate a --stock-sources list. Returns (names in HumanMine's project.xml order, problems)."""
    problems: List[str] = []
    seen, dup = set(), []
    for n in names:
        if n in seen and n not in dup:
            dup.append(n)
        seen.add(n)
    if dup:
        problems.append(f"listed more than once: {', '.join(dup)}")
    unknown = [n for n in dict.fromkeys(names) if n not in table]
    if unknown:
        problems.append(f"unknown stock source(s) {', '.join(unknown)} - not in rdfc2im/data/stock_sources.yaml; "
                        f"known: {', '.join(sorted(table))}")
    chosen = [n for n in dict.fromkeys(names) if n in table]
    if not chosen:
        return [], problems
    taxa = [str(t) for t in taxa]
    if taxa != ["9606"]:
        problems.append(f"--taxon {','.join(taxa)}: the stock sources are set up for human (9606) only")
    for n in chosen:
        for need in table[n].get("needs") or []:
            if need not in chosen:
                problems.append(f"{n} needs {need} too (add it to --stock-sources)")
    rep = replaced_by(rdf_sources, sources_cfg or {})
    for n in chosen:
        if n in rep:
            problems.append(f"{n} is replaced by {', '.join(rep[n])} in this build (sources.yaml `replaces`); "
                            f"load one or the other")
    for n in chosen:
        e = table[n]
        if e.get("local_copy") == "required":
            missing = [raw_name(f) for f in e["files"] if not local_path(local_dir, n, f)]
            if missing:
                where = os.path.join(local_dir, n) if local_dir else "--stock-local DIR/" + n
                problems.append(f"{n} is {'not redistributable' if not e['redistributable'] else 'local-only'} "
                                f"({e.get('licence')}): it loads only from a local copy, and {where} lacks "
                                f"{', '.join(missing)}")
    order = chosen
    if project_xml:
        hm = project_order(project_xml)
        absent = [n for n in chosen if n not in hm]
        if absent:
            problems.append(f"not in HumanMine's project.xml ({project_xml}): {', '.join(absent)}")
        order = [n for n in hm if n in chosen] + absent
    return order, problems


def order_problems(names_in_order: List[str], table: Dict[str, dict], selected: Iterable[str],
                   replacements: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """Integrate-order constraints (plan 50 row 11) against a project.xml's source order.

    `after` names HumanMine sources; one replaced by an rdfc2im source in this build stands for its
    replacement (ncbi-gene -> humanmine-ncbigene). A constraint whose other end is not loaded is
    satisfied."""
    pos = {n: i for i, n in enumerate(names_in_order)}
    out = []
    for n in selected:
        if n not in pos:
            continue
        for a in table[n].get("after") or []:
            for b in (replacements or {}).get(a, [a]):
                if b in pos and pos[b] > pos[n]:
                    out.append(f"{n} must integrate after {b}, but project.xml lists it before")
    return out


# ------------------------------------------------------------------ project.xml

def apply_to_project(sources_el: etree._Element, table: Dict[str, dict], names: List[str]) -> List[str]:
    """Rewrite the kept stock <source> entries of a HumanMine project.xml in place.

    Each named entry gets its data property set from the table (data_dir, data_file, under
    HUMANMINE_DATA_ROOT, which full-build.sh maps to RDFC2IM_DATA_ROOT) and the table's
    `properties` overrides (organisms cut down to human, ...). Returns problems: a name with no
    <source> (it was replaced, or HumanMine never had it), or a version attribute that does not
    match the jar's origin."""
    problems: List[str] = []
    by_name = {s.get("name"): s for s in sources_el if isinstance(s.tag, str) and s.tag == "source"}
    for n in names:
        e = table[n]
        s = by_name.get(n)
        if s is None:
            problems.append(f"stock source {n} has no <source name=\"{n}\"> left in project.xml "
                            f"(replaced by an rdfc2im source, or not a HumanMine source)")
            continue
        if s.get("type") != e["type"]:
            problems.append(f"stock source {n}: project.xml type {s.get('type')!r}, table type {e['type']!r}")
        want_version = HUMANMINE_BIO_VERSION if e["jar"] == "humanmine-bio-sources" else None
        if s.get("version") != want_version:
            problems.append(f"stock source {n}: jar origin {e['jar']} needs version={want_version!r} in "
                            f"project.xml, which has {s.get('version')!r}")
        prop = e.get("data_property", "src.data.dir")
        loc = f"{HUMANMINE_DATA_ROOT}/{e['data_dir'].strip('/')}"
        if prop == "src.data.file":
            loc = f"{loc}/{e['data_file']}"
        _set_property(s, prop, location=loc)
        for k, v in (e.get("properties") or {}).items():
            _set_property(s, k, value=str(v).replace("{data_root}", HUMANMINE_DATA_ROOT))
    return problems


def _set_property(source: etree._Element, name: str, value: Optional[str] = None,
                  location: Optional[str] = None) -> None:
    for p in source.iter("property"):
        if p.get("name") == name:
            break
    else:
        p = etree.SubElement(source, "property", name=name)
    for attr in ("value", "location"):
        if attr in p.attrib:
            del p.attrib[attr]
    if location is not None:
        p.set("location", location)
    else:
        p.set("value", value or "")


# ------------------------------------------------------------------ rows for full-build.sh

def jar_rows(table: Dict[str, dict], names: List[str], im_version: str) -> List[str]:
    """source, type, origin, artifact, version - one row per distinct jar (uniprot-fasta and
    ncbi-fasta share bio-source-fasta)."""
    rows, done = [], set()
    for n in names:
        e = table[n]
        art = f"bio-source-{e['type']}"
        if art in done:
            continue
        done.add(art)
        ver = HUMANMINE_BIO_VERSION if e["jar"] == "humanmine-bio-sources" else im_version
        rows.append(_row(n, e["type"], e["jar"], art, ver))
    return rows


def filter_spec(f: dict) -> str:
    """A canonical one-word description of how a file is cut down, for cache META and logs."""
    flt = f.get("filter", "none")
    if flt == "none":
        return "none"
    parts = [flt["format"], f"ids={flt.get('ids', 'none')}"]
    for k in ("column", "taxon"):
        if flt.get(k):
            parts.append(f"{k}={flt[k]}")
    if flt.get("keep_header"):
        parts.append("keep_header")
    return ",".join(parts)


def file_rows(table: Dict[str, dict], names: List[str], stock_dir: str, raw_cache: str,
              local_dir: Optional[str] = None) -> List[str]:
    """One row per upstream file, 16 fields:

      source, file id, origin (download|local), url, raw path, unpack, member,
      format, ids, column, taxon, keep_header (0|1),
      work dir (where filtering/unpacking writes; '-' when the raw file is staged as it is),
      kind (filtered|whole|asis), stage dir (relative to the data root), stage name ('-' = member names)

    `filtered` work dirs are what the source's filtered cache group holds; `whole` ones are files
    used complete but decompressed or unpacked (derived from the raw group again on every build,
    never cached twice); `asis` files are staged straight from the raw path."""
    rows = []
    for n in names:
        e = table[n]
        for f in e["files"]:
            lp = local_path(local_dir, n, f)
            origin = "local" if lp else "download"
            raw = lp or os.path.join(raw_cache, f"stock-raw-{n}", "data", raw_name(f))
            flt = f.get("filter", "none")
            packed = bool(f.get("unpack")) or raw.endswith(".gz")
            if flt != "none":
                kind, work = "filtered", os.path.join(stock_dir, "subset", n, f["id"])
            elif packed:
                kind, work = "whole", os.path.join(stock_dir, "whole", n, f["id"])
            else:
                kind, work = "asis", None
            fl = flt if isinstance(flt, dict) else {}
            rows.append(_row(n, f["id"], origin, f.get("url"), raw, f.get("unpack"), f.get("member"),
                             fl.get("format"), fl.get("ids"), fl.get("column"), fl.get("taxon"),
                             1 if fl.get("keep_header") else 0, work, kind, e["data_dir"].strip("/"),
                             f.get("stage_as")))
    return rows


def postprocess_order(project_xml: str) -> List[str]:
    """Post-process names in HumanMine's project.xml <post-processing> block, in order."""
    root = etree.parse(project_xml).getroot()
    return [p.get("name") for p in root.iter("post-process")]


def postprocess_rows(table: Dict[str, dict], names: List[str],
                     project_xml: Optional[str] = None) -> List[str]:
    """postprocess, sources wanting it. In HumanMine's <post-processing> order when project_xml is
    given (phase_postprocess runs them in the order printed) [im-9n4.6]; a postprocess HumanMine does
    not list, and every one without project_xml, keeps first-wanted order after those it does."""
    want: Dict[str, List[str]] = {}
    for n in names:
        for p in table[n].get("postprocess") or []:
            want.setdefault(p, []).append(n)
    order = postprocess_order(project_xml) if project_xml else []
    first = list(want)
    ranked = sorted(want, key=lambda p: (order.index(p) if p in order else len(order), first.index(p)))
    return [_row(p, ",".join(want[p])) for p in ranked]


def cache_meta(table: Dict[str, dict], name: str) -> List[str]:
    """`--meta` words for the filtered cache group of one source. The restore-relevant part is the
    spec (what files, filtered how); genes_md5 and taxon are added by the caller, like the panel
    sources'. `redistributable` and `licence` are recorded for `cache save --for-release` (T0.3)."""
    e = table[name]
    spec = [{"id": f["id"], "url": f.get("url"), "raw": raw_name(f), "filter": filter_spec(f),
             "unpack": f.get("unpack"), "member": f.get("member"), "stage_as": f.get("stage_as")}
            for f in e["files"] if f.get("filter", "none") != "none"]
    spec_md5 = hashlib.md5(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    return [f"spec_md5={spec_md5}", f"redistributable={'true' if e['redistributable'] else 'false'}",
            "licence=" + re.sub(r"[^A-Za-z0-9.-]+", "_", str(e["licence"])).strip("_")]


def has_filtered(table: Dict[str, dict], name: str) -> bool:
    return any(f.get("filter", "none") != "none" for f in table[name]["files"])


def download_bytes(table: Dict[str, dict], names: List[str], local_dir: Optional[str] = None) -> int:
    """What the selection downloads, from the table's recorded sizes (0 for an unknown size)."""
    return sum(int(f.get("size") or 0) for n in names for f in table[n]["files"]
               if f.get("url") and not local_path(local_dir, n, f))
