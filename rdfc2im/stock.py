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
  stock resolver NAME...     one row per NCBI gene_info file the ID resolver needs: the --taxon one first, then the
                             `resolver_taxa` of the selected sources [im-9n4.11]

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
FORMATS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "gene_info", "psi-xml", "interpro-xml")
NEEDS_IDS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "psi-xml", "interpro-xml")
# formats whose filter reads a zip itself and writes one file per member of a glob (into the work
# directory, staged under the members' own names): PSI-MI XML, IntAct's human.zip holds dozens [im-9n4.13]
MULTI_MEMBER_FORMATS = ("psi-xml",)
# entrez..symbol: the panel id sets; chromosomes: the RefSeq accessions of the GRCh38 chromosomes
# the ncbi-gff loader maps (not panel-dependent; `subset_raw.py idsets` writes it too)
ID_KINDS = ("entrez", "ensembl", "uniprot", "symbol", "chromosomes", "mgi", "rgd", "hpo-diseases", "ipr", "none")
# ipr: the InterPro entries of the panel's protein2ipr rows (`subset_raw.py ipr-ids`), for cutting interpro.xml [im-9n4.27]
# mgi, rgd: the partner genes of the panel's PANTHER rows (`subset_raw.py partner-ids`), "MGI:97490" and "3258", for
# cutting mgi-identifiers' and rgd-identifiers' whole-genome files down to the genes panther will create [im-9n4.11]
# NCBI's per-organism gene_info files (the ID resolver reads them whole, one taxon at a time): taxon -> path under
# ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/. The resolver's own config maps yeast to strain 559292; add it with a
# source that resolves yeast.
GENE_INFO_URL = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/{}.gene_info.gz"
GENE_INFO_PATHS = {"9606": "Mammalia/Homo_sapiens", "10090": "Mammalia/Mus_musculus",
                   "10116": "Mammalia/Rattus_norvegicus", "7955": "Non-mammalian_vertebrates/Danio_rerio",
                   "7227": "Invertebrates/Drosophila_melanogaster"}
# The file a `chromosome_lengths` entry writes (tools/subset_raw.py chromosome-lengths), and the
# format word its row carries in `stock files`.
LENGTHS_FILE = "chromosome_lengths.xml"
LENGTHS_FORMAT = "chromosome-lengths"
UNPACK = ("zip", "tar.gz")
# none: project.xml's own data property stays (the source reads no staged data directory: update-publications and
# entrez-organism write their file themselves, update-data-sources reads one file named by `dataSourceFile`) [im-9n4.27]
DATA_PROPERTIES = ("src.data.dir", "src.data.file", "none")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GLOB_CHARS = set("*?[")
# The licence record of a source [im-9n4.45]: what the source states, where, when it was read. `licence` stays the
# short name (it goes into the cache group's META as licence=...); the rest is for the data-source pages and
# docs/LICENCES.md. Files: data/stock_sources.yaml, data/sources.yaml (RDF), data/other_licences.yaml.
OTHER_LICENCES = os.path.join(HERE, "data", "other_licences.yaml")
LICENCE_STATUSES = ("verified", "partial", "not-verified", "not-stated", "not-checked")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Sources taken out of the table, and why: a --stock-sources list that still names one stops with this text.
RETIRED = {
    "humanmine-static": "retired [im-9n4.52, Gos 20 Nov 2026]. HumanMine's datasets.xml of Feb 2022 made 40 DataSets, "
                        "34 of them with no data in this build and all with versions of 2011-22. DataSet.version now comes "
                        "from the build's own caches and the DataSource urls it gave from the stock mapping files, both "
                        "through the data-set-links source tools/full-build.sh adds (BUILD.md, \"DataSet versions\"). "
                        "Remove it from the list.",
}


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


def licence_problems(where: str, e: dict) -> List[str]:
    """Problems with the structured licence keys of one entry. All keys are optional here (a table
    written before im-9n4.45 has only `licence`); what is present must be well formed, and a status of
    verified or partial needs the page, the date and the quotation that make it so."""
    out: List[str] = []
    status = e.get("licence_status")
    if status is None:
        return out
    if status not in LICENCE_STATUSES:
        out.append(f"{where}: `licence_status` must be one of {', '.join(LICENCE_STATUSES)}")
    if e.get("licence_checked") is not None and not DATE_RE.match(str(e["licence_checked"])):
        out.append(f"{where}: `licence_checked` must be a date YYYY-MM-DD (quoted)")
    conds = e.get("licence_conditions")
    if conds is not None and not (isinstance(conds, list) and all(isinstance(c, str) for c in conds)):
        out.append(f"{where}: `licence_conditions` must be a list of strings")
    if status in ("verified", "partial"):
        for k in ("licence_url", "licence_checked", "licence_quote"):
            if not e.get(k):
                out.append(f"{where}: `{k}` is required when licence_status is {status}")
    return out


def licence_info(e: dict) -> dict:
    """The licence record of a stock_sources.yaml / sources.yaml / other_licences.yaml entry as one dict
    (what the manifest stores and the pages show). Missing keys are None; `conditions` is always a list."""
    return {"name": e.get("licence"), "status": e.get("licence_status"), "url": e.get("licence_url"),
            "checked": e.get("licence_checked"), "quote": e.get("licence_quote"),
            "conditions": list(e.get("licence_conditions") or []),
            "redistributable": e.get("redistributable"), "reason": e.get("redistributable_reason"),
            "rdfportal": e.get("rdfportal_licence"), "rdfportal_url": e.get("rdfportal_licence_url"),
            "rdfportal_note": e.get("rdfportal_licence_note")}


def other_licences(path: Optional[str] = None) -> Dict[str, dict]:
    """data/other_licences.yaml: what is neither a stock source nor an RDF source (stock reactome, the ID
    resolver's gene_info files, the BlueGenes tool packages, imjs)."""
    with open(path or OTHER_LICENCES, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    problems = [p for n, e in doc.items() for p in licence_problems(n, e)]
    if problems:
        raise StockError("other_licences.yaml: " + "; ".join(problems))
    return doc


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
        out += licence_problems(where, e)
        local = e.get("local_copy", "optional")
        if local not in ("optional", "required"):
            out.append(f"{where}: `local_copy` must be optional or required")
        if e.get("redistributable") is False and local != "required":
            out.append(f"{where}: redistributable: false needs local_copy: required (D-7: local copies only)")
        prop = e.get("data_property", "src.data.dir")
        if prop not in DATA_PROPERTIES:
            out.append(f"{where}: `data_property` must be one of {', '.join(DATA_PROPERTIES)}")
        ddir = e.get("data_dir")
        no_data = prop == "none" and e.get("files") == []
        if not no_data and (not ddir or str(ddir).startswith("/") or ".." in str(ddir).split("/")):
            out.append(f"{where}: `data_dir` must be a relative path under {HUMANMINE_DATA_ROOT}")
        if prop == "src.data.file" and not e.get("data_file"):
            out.append(f"{where}: data_property src.data.file needs `data_file`")
        for key in ("after", "needs", "postprocess"):
            v = e.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                out.append(f"{where}: `{key}` must be a list of names")
        pf = e.get("priority_first", [])
        if not isinstance(pf, list) or not all(isinstance(x, str) and re.match(r"^[A-Z]\w*\.\w+$", x) for x in pf):
            out.append(f"{where}: `priority_first` must be a list of Class.field names")
        for n in e.get("needs", []) or []:
            if n not in table:
                out.append(f"{where}: needs '{n}', which is not in the table")
        rt = e.get("resolver_taxa", [])
        if not isinstance(rt, list) or not all(str(t) in GENE_INFO_PATHS for t in rt):
            out.append(f"{where}: `resolver_taxa` must be a list of taxon ids from {', '.join(GENE_INFO_PATHS)}")
        if not isinstance(e.get("load_first", False), bool):
            out.append(f"{where}: `load_first` must be true or false")
        if not isinstance(e.get("properties", {}) or {}, dict):
            out.append(f"{where}: `properties` must be a mapping")
        files = e.get("files")
        if no_data:
            continue
        if not isinstance(files, list) or not files:
            out.append(f"{where}: `files` must be a non-empty list (or [] with data_property: none)")
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
            if f.get("repo_file"):
                if url is not None:
                    out.append(f"{fw}: `repo_file` and `url` are alternatives")
                if not os.path.isfile(os.path.join(HERE, "data", str(f["repo_file"]))):
                    out.append(f"{fw}: repo_file {f['repo_file']} is not in rdfc2im/data/")
                if f.get("filter", "none") != "none":
                    out.append(f"{fw}: a repo_file is staged as it is (filter: none)")
            elif url is None:
                if local != "required":
                    out.append(f"{fw}: no `url`, so the source needs local_copy: required")
                if not f.get("raw_name"):
                    out.append(f"{fw}: without a url, `raw_name` (the local file name) is required")
            elif not re.match(r"^https?://", str(url)):
                out.append(f"{fw}: `url` must be http(s)")
            if f.get("stream"):
                # streamed: read from the URL by the filter itself, never stored (protein2ipr.dat.gz is 13.8 GB)
                if not url or f.get("unpack") or f.get("filter", "none") == "none":
                    out.append(f"{fw}: `stream` is for a url file that is filtered and not unpacked")
            if not isinstance(f.get("verified", False), bool):
                out.append(f"{fw}: `verified` must be true or false")
            ac = f.get("accept_cuts")
            if ac is not None:
                if not isinstance(ac, list):
                    out.append(f"{fw}: `accept_cuts` must be a list")
                else:
                    for k, c in enumerate(ac):
                        if not isinstance(c, dict) or not c.get("reason"):
                            out.append(f"{fw}: accept_cuts[{k}] needs a `reason` (why the old cut is still accepted)")
                        elif not isinstance(c.get("filter"), dict):
                            out.append(f"{fw}: accept_cuts[{k}] needs the old `filter` mapping")
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
                dc, rq = flt.get("drop_columns"), flt.get("require")
                if fmt in NEEDS_IDS and ids == "none" and not (fmt == "tab" and (dc or rq)):
                    out.append(f"{fw}: format {fmt} filters by ids, so `ids` cannot be none")
                if (dc or rq) and fmt != "tab":
                    out.append(f"{fw}: `drop_columns` and `require` are for format tab only")
                if dc is not None and not re.match(r"^\d+(,\d+)*$", str(dc)):
                    out.append(f"{fw}: `drop_columns` is 1-based numbers, comma separated")
                if rq is not None and not (isinstance(rq, list) and all(
                        isinstance(x, str) and re.match(r"^\d+=.+", x) for x in rq)):
                    out.append(f"{fw}: `require` must be a list of 'COLUMN=REGEX' strings")
                if fmt == "tab" and not flt.get("column"):
                    out.append(f"{fw}: format tab needs `column`")
                if flt.get("column") and not re.match(r"^\d+(,\d+)*$", str(flt["column"])):
                    out.append(f"{fw}: `column` is 1-based numbers, comma separated")
                kh = flt.get("keep_header")
                if kh is not None and not (isinstance(kh, bool) or (isinstance(kh, int) and kh >= 1)):
                    out.append(f"{fw}: `keep_header` is true or a number of lines (1 or more)")
                kt = flt.get("keep_types")
                if kt is not None:
                    if fmt != "gff3":
                        out.append(f"{fw}: `keep_types` is for format gff3 only")
                    if not isinstance(kt, list) or not kt or not all(
                            isinstance(t, str) and re.match(r"^[A-Za-z0-9_-]+$", t) for t in kt):
                        out.append(f"{fw}: `keep_types` must be a list of GFF feature types")
                if multi and fmt not in MULTI_MEMBER_FORMATS:
                    out.append(f"{fw}: a member glob unpacks several files; only a single file can be filtered "
                               f"(except by {', '.join(MULTI_MEMBER_FORMATS)})")
                if multi and unpack != "zip":
                    out.append(f"{fw}: format {fmt} reads several members from a zip only")
                xdb = flt.get("xref_db")
                if xdb is not None:
                    if fmt != "psi-xml":
                        out.append(f"{fw}: `xref_db` is for format psi-xml only")
                    if not isinstance(xdb, list) or not xdb or not all(
                            isinstance(d, str) and re.match(r"^[A-Za-z0-9_./ -]+$", d) for d in xdb):
                        out.append(f"{fw}: `xref_db` must be a list of xref db names")
        cl = e.get("chromosome_lengths")
        if cl is not None:
            if not isinstance(cl, dict):
                out.append(f"{where}: `chromosome_lengths` must be a mapping")
                continue
            src_f = next((f for f in files if isinstance(f, dict) and f.get("id") == cl.get("from")), None)
            if src_f is None:
                out.append(f"{where}: chromosome_lengths `from` must name one of the entry's file ids")
            elif not isinstance(src_f.get("filter"), dict) or src_f["filter"].get("format") != "gff3":
                out.append(f"{where}: chromosome_lengths reads a gff3-filtered file; {cl.get('from')} is not one")
            if not cl.get("source") or not NAME_RE.match(str(cl["source"])) or cl["source"] in table:
                out.append(f"{where}: chromosome_lengths `source` must be a new project.xml source name")
            cdir = cl.get("data_dir")
            if not cdir or str(cdir).startswith("/") or ".." in str(cdir).split("/") \
                    or str(cdir).strip("/") == str(ddir or "").strip("/"):
                out.append(f"{where}: chromosome_lengths `data_dir` must be a relative path under "
                           f"{HUMANMINE_DATA_ROOT}, not the source's own data_dir (its loader reads that)")
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
    """The local copy of one file: <local_dir>/<source>/<raw name>, when it exists. A `repo_file` (a small file
    this repository ships in rdfc2im/data/, e.g. HPA's tissue-to-organ grouping [im-9n4.14]) is always local."""
    if f.get("repo_file"):
        return os.path.join(HERE, "data", f["repo_file"])
    if not local_dir:
        return None
    p = os.path.join(local_dir, name, raw_name(f))
    return p if os.path.isfile(p) else None


def raw_name(f: dict) -> str:
    if f.get("repo_file"):
        return f["repo_file"]
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
    for n in dict.fromkeys(names):
        if n in RETIRED and n not in table:
            problems.append(f"{n} is no longer a stock source: {RETIRED[n]}")
    unknown = [n for n in dict.fromkeys(names) if n not in table and n not in RETIRED]
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
        if prop != "none":
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


def header_lines(flt: dict) -> int:
    """How many leading lines of a tab file the filter keeps whatever they hold: `keep_header: true` is 1, a
    number is that many (GTEx's GCT has a `#1.2` line, a dimensions line and then the header) [im-9n4.14]."""
    kh = flt.get("keep_header")
    if not kh:
        return 0
    return 1 if kh is True else int(kh)


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
        n = header_lines(flt)
        parts.append("keep_header" if n == 1 else f"keep_header={n}")
    if flt.get("keep_types"):
        parts.append("keep_types=" + "+".join(flt["keep_types"]))
    if flt.get("xref_db"):
        parts.append("xref_db=" + "+".join(flt["xref_db"]))
    if flt.get("drop_columns"):
        parts.append(f"drop_columns={flt['drop_columns']}")
    if flt.get("require"):
        parts.append("require=" + "+".join(flt["require"]))
    return ",".join(parts)


def lengths_sources(table: Dict[str, dict], names: List[str]) -> List[Tuple[str, str, str]]:
    """(stock source, lengths source name, lengths file location under HUMANMINE_DATA_ROOT) for every
    selected source with a `chromosome_lengths` entry: the extra humanmine-items <source> that loads
    Chromosome.length from the GFF's ##sequence-region lines [im-9n4.9]."""
    out = []
    for n in names:
        cl = table[n].get("chromosome_lengths")
        if cl:
            out.append((n, cl["source"], f"{HUMANMINE_DATA_ROOT}/{cl['data_dir'].strip('/')}/{LENGTHS_FILE}"))
    return out


# The id sets subset_stock_data derives from the gene panel (subset_raw.py idsets, partner-ids, disease-ids). A
# filter on one of them is a panel cut; `chromosomes` (the GRCh38 assembly's 24 RefSeq chromosomes, which cut the
# genome FASTA to what the ncbi-gff loader maps) is not, and stays in a full-scope build [im-9n4.26].
PANEL_ID_SETS = frozenset({"entrez", "ensembl", "uniprot", "symbol", "mgi", "rgd", "hpo-diseases", "ipr"})


def file_rows(table: Dict[str, dict], names: List[str], stock_dir: str, raw_cache: str,
              local_dir: Optional[str] = None, full: bool = False) -> List[str]:
    """One row per upstream file, 20 fields:

      source, file id, origin (download|local|derived), url, raw path, unpack, member,
      format, ids, column, taxon, keep_header (the number of leading lines kept, 0 for none),
      work dir (where filtering/unpacking writes; '-' when the raw file is staged as it is),
      kind (filtered|whole|asis|derived), stage dir (relative to the data root),
      stage name ('-' = member names), keep_types (gff3: comma-separated feature types),
      xref_db (psi-xml: comma-separated xref db names; '-' for any db),
      drop_columns (tab: 1-based columns taken out of every kept row), require (tab: ';'-separated COLUMN=REGEX)

    origin `stream` (a file with `stream: true`, panel scope only): the raw field is the URL, which the filter
    reads and cuts as it arrives; nothing is stored in the raw cache [im-9n4.27].

    `filtered` work dirs are what the source's filtered cache group holds; `whole` ones are files
    used complete but decompressed or unpacked (derived from the raw group again on every build,
    never cached twice); `asis` files are staged straight from the raw path. A `chromosome_lengths`
    entry adds a last `derived` row for the source: its raw path is the filtered GFF it reads, its
    format chromosome-lengths, and its work dir sits in the filtered group, so it is cached and
    restored with it [im-9n4.9].

    full (full-build.sh --scope full): no panel cut - a file filtered on a PANEL_ID_SETS id set is used whole
    instead (unpacked or decompressed, else staged as it is), as HumanMine's own build reads it [im-9n4.26]; a
    tab filter that also drops columns or requires values keeps doing that, on every row (ids none) [im-9n4.27]."""
    rows = []
    for n in names:
        e = table[n]
        works = {}
        for f in e["files"]:
            lp = local_path(local_dir, n, f)
            origin = "local" if lp else "download"
            raw = lp or os.path.join(raw_cache, f"stock-raw-{n}", "data", raw_name(f))
            if f.get("stream") and not lp and not full:
                origin, raw = "stream", f["url"]
            flt = f.get("filter", "none")
            if full and isinstance(flt, dict) and flt.get("ids") in PANEL_ID_SETS:
                flt = dict(flt, ids="none") if (flt.get("drop_columns") or flt.get("require")) else "none"
            packed = bool(f.get("unpack")) or raw.endswith(".gz")
            if origin == "stream":
                packed = False
            if flt != "none":
                kind, work = "filtered", os.path.join(stock_dir, "subset", n, f["id"])
            elif packed:
                kind, work = "whole", os.path.join(stock_dir, "whole", n, f["id"])
            else:
                kind, work = "asis", None
            works[f["id"]] = (work, f.get("stage_as"))
            fl = flt if isinstance(flt, dict) else {}
            rows.append(_row(n, f["id"], origin, f.get("url"), raw, f.get("unpack"), f.get("member"),
                             fl.get("format"), fl.get("ids"), fl.get("column"), fl.get("taxon"),
                             header_lines(fl), work, kind, e["data_dir"].strip("/"),
                             f.get("stage_as"), ",".join(fl.get("keep_types") or []),
                             ",".join(fl.get("xref_db") or []), fl.get("drop_columns"),
                             ";".join(fl.get("require") or [])))
        cl = e.get("chromosome_lengths")
        if cl:
            work, sname = works[cl["from"]]
            rows.append(_row(n, "chromosome-lengths", "derived", None, os.path.join(work, sname), None, None,
                             LENGTHS_FORMAT, None, None, "9606", 0,
                             os.path.join(stock_dir, "subset", n, "chromosome-lengths"), "derived",
                             cl["data_dir"].strip("/"), LENGTHS_FILE, None, None, None, None))
    return rows


def resolver_rows(table: Dict[str, dict], names: List[str], taxon: str = "9606") -> List[str]:
    """taxon, url, raw file name: the gene_info files the mine's ID resolver is built from. The --taxon one is
    always there (the T0.3 gate); a selected source adds its `resolver_taxa` (panther: the partner organisms its
    converter resolves, rat and zebrafish). In first-listed order, each once."""
    taxa = [str(taxon)]
    for n in names:
        taxa += [str(t) for t in table[n].get("resolver_taxa") or []]
    rows = []
    for t in dict.fromkeys(taxa):
        if t not in GENE_INFO_PATHS:
            raise StockError(f"no NCBI gene_info file known for taxon {t} (stock.GENE_INFO_PATHS)")
        url = GENE_INFO_URL.format(GENE_INFO_PATHS[t])
        rows.append(_row(t, url, os.path.basename(url)))
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


def _file_spec(f: dict, flt=None) -> dict:
    return {"id": f["id"], "url": f.get("url"), "raw": raw_name(f),
            "filter": filter_spec(f if flt is None else dict(f, filter=flt)),
            "unpack": f.get("unpack"), "member": f.get("member"), "stage_as": f.get("stage_as")}


def _spec_md5(e: dict, spec: list) -> str:
    # (a file's `stream` flag does not enter the key: it changes how the cut is read, not what it holds)
    spec = list(spec)
    if e.get("chromosome_lengths"):
        spec.append({"chromosome_lengths": e["chromosome_lengths"]["from"], "file": LENGTHS_FILE})
    return hashlib.md5(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def accepted_specs(table: Dict[str, dict], name: str) -> List[str]:
    """`spec_md5=...` words of earlier cuts of the source's filtered files that a build still accepts as its cache
    key, one per `accept_cuts` entry of a file: the table lists the filter a cached group was made with after the
    table dropped it, so a group that took a long time to make (a streamed 13.8 GB file) is not made again for a
    change that only widens what the next fetch keeps. Temporary: remove the entry (and the group) to fetch afresh
    [im-9n4.28]."""
    e = table[name]
    out: List[str] = []
    for f in e["files"]:
        for c in f.get("accept_cuts") or []:
            spec = [_file_spec(g, c["filter"] if g is f else None) for g in e["files"]
                    if (c["filter"] if g is f else g.get("filter", "none")) != "none"]
            out.append("spec_md5=" + _spec_md5(e, spec))
    return out


def cache_meta(table: Dict[str, dict], name: str) -> List[str]:
    """`--meta` words for the filtered cache group of one source. The restore-relevant part is the
    spec (what files, filtered how); genes_md5 and taxon are added by the caller, like the panel
    sources'. `redistributable` and `licence` are recorded for `cache save --for-release` (T0.3)."""
    e = table[name]
    spec = [_file_spec(f) for f in e["files"] if f.get("filter", "none") != "none"]
    spec_md5 = _spec_md5(e, spec)
    return [f"spec_md5={spec_md5}", f"redistributable={'true' if e['redistributable'] else 'false'}",
            "licence=" + re.sub(r"[^A-Za-z0-9.-]+", "_", str(e["licence"])).strip("_")]


def has_filtered(table: Dict[str, dict], name: str) -> bool:
    return any(f.get("filter", "none") != "none" for f in table[name]["files"])


def download_bytes(table: Dict[str, dict], names: List[str], local_dir: Optional[str] = None) -> int:
    """What the selection downloads and stores, from the table's recorded sizes (0 for an unknown size). A
    streamed file (`stream: true`) is cut as it arrives and stores only its panel rows: not counted (a
    --scope full build downloads it whole, which this count does not know) [im-9n4.27]."""
    return sum(int(f.get("size") or 0) for n in names for f in table[n]["files"]
               if f.get("url") and not f.get("stream") and not local_path(local_dir, n, f))
