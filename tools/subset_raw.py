#!/usr/bin/env python3
"""subset_raw.py: cut raw upstream files down to a gene panel before a stock InterMine loader reads them.

The stock loaders (UniProt XML, GO annotation GAF, NCBI GFF3, FASTA, interaction and orthologue
tab files) have no gene filter, so for a demo build the raw files are pre-filtered here. Python 3
standard library only; every filter streams (input files can be 400 MB) and `.gz` is read and
written transparently by file suffix.

  subset_raw.py idsets --genes FILE --out DIR [--items-root DIR] [--lookup-dir DIR] [--taxon ID]
      Derive the panel id sets (entrez.txt, ensembl.txt, uniprot.txt, symbol.txt, idsets.json).

  subset_raw.py filter --format gaf|gff3|uniprot-xml|fasta|tab|gene_info --in PATH --out PATH
                       [--ids FILE] [--column N[,N...]] [--taxon ID] [--keep-comments]
      Filter one raw file; prints one JSON line with the record counts.

Per-format rules are in each filter function's docstring and in USAGE.md.
"""
import argparse
import glob
import gzip
import hashlib
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

FORMATS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "gene_info")
NEEDS_IDS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab")


class SubsetError(Exception):
    """A usage or input problem (reported on stderr, exit status 2)."""


# ---------------------------------------------------------------- file helpers

def open_text(path, mode="r"):
    """Open a text file for reading ('r') or writing ('w'); `.gz` suffix means gzip.
    Newlines are not translated, so output is byte-faithful to the input lines. gzip output has
    a zero mtime and no stored file name, so the same input always gives the same bytes."""
    if path.endswith(".gz"):
        if mode == "r":
            return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
        raw = open(path, "wb")
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        return _ClosingWrapper(io.TextIOWrapper(gz, encoding="utf-8", newline=""), gz, raw)
    return open(path, mode, encoding="utf-8", newline="")


class _ClosingWrapper:
    """TextIOWrapper whose close() also closes the gzip layer and the file under it."""

    def __init__(self, text, *inner):
        self._text, self._inner = text, inner

    def write(self, s):
        return self._text.write(s)

    def close(self):
        self._text.close()
        for f in self._inner:
            f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_id_file(path):
    """One id per line; blank lines and '#' lines ignored; surrounding whitespace stripped."""
    ids = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line)
    return ids


def read_panel(path):
    """Panel symbols: whitespace-separated tokens, '#' comment lines (same as the rdfc2im --genes @file)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.extend(line.split())
    return out


def _summary(fmt, n_in, n_out, ids, matched):
    return {"format": fmt, "records_in": n_in, "records_out": n_out,
            "ids_given": len(ids), "ids_matched": len(matched)}


def _base_accession(acc):
    """P10635-2 -> P10635 (isoform suffix); anything else unchanged."""
    m = re.match(r"^([A-Za-z0-9_]+)-\d+$", acc)
    return m.group(1) if m else acc


# ---------------------------------------------------------------- GAF

def filter_gaf(src, dst, ids):
    """Keep '!' header lines and rows whose column 2 (DB object id) is in ids. An isoform id
    (P10635-2) also matches on its base accession. Blank lines are dropped."""
    n_in = n_out = 0
    matched = set()
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            if line.startswith("!"):
                fout.write(line)
                continue
            if not line.strip():
                continue
            n_in += 1
            cols = line.split("\t", 2)
            if len(cols) < 2:
                continue
            obj = cols[1]
            hit = obj if obj in ids else (_base_accession(obj) if _base_accession(obj) in ids else None)
            if hit:
                matched.add(hit)
                n_out += 1
                fout.write(line)
    return _summary("gaf", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- GFF3

_DBXREF_RE = re.compile(r"(?:^|;)Dbxref=([^;\n]*)")
_ID_RE = re.compile(r"(?:^|;)ID=([^;\n]*)")
_PARENT_RE = re.compile(r"(?:^|;)Parent=([^;\n]*)")


def _gff_fields(line):
    """(attributes column) of a feature line, or None if it has fewer than 9 columns."""
    cols = line.rstrip("\r\n").split("\t")
    return cols[8] if len(cols) >= 9 else None


def _gff_geneids(attrs):
    out = []
    m = _DBXREF_RE.search(attrs)
    if m:
        for x in m.group(1).split(","):
            if x.startswith("GeneID:"):
                out.append(x[len("GeneID:"):])
    return out


def filter_gff3(src, dst, ids):
    """Keep every directive/comment line ('#...', so each ##sequence-region), features whose Dbxref
    has GeneID:<id> with <id> in ids, and the Parent closure of those: all descendants (exons, CDS,
    transcripts, grandchildren) and, so that no kept feature has a dangling Parent, its ancestors.
    Children may appear before their parents, so this makes two passes over the input: the first
    finds the matching features and the ID/Parent links, the second writes. A '##FASTA' section
    (embedded sequence) ends the features and is not copied.

    Memory: the first pass keeps one small dict entry per feature that has both ID and Parent."""
    parents = {}      # child ID -> set of parent IDs
    seeds = set()     # IDs of matching features
    matched = set()
    n_in = 0
    with open_text(src) as fin:
        for line in fin:
            if line.startswith("##FASTA"):
                break
            if line.startswith("#") or not line.strip():
                continue
            attrs = _gff_fields(line)
            if attrs is None:
                continue
            n_in += 1
            m_id = _ID_RE.search(attrs)
            m_par = _PARENT_RE.search(attrs)
            fid = m_id.group(1) if m_id else None
            if fid and m_par:
                parents.setdefault(fid, set()).update(m_par.group(1).split(","))
            hits = [g for g in _gff_geneids(attrs) if g in ids]
            if hits:
                matched.update(hits)
                if fid:
                    seeds.add(fid)
    children = {}
    for child, pars in parents.items():
        for p in pars:
            children.setdefault(p, set()).add(child)
    keep = set(seeds)
    stack = list(seeds)
    while stack:                              # descendants
        for c in children.get(stack.pop(), ()):
            if c not in keep:
                keep.add(c)
                stack.append(c)
    stack = list(seeds)
    while stack:                              # ancestors (of the matching features only)
        for p in parents.get(stack.pop(), ()):
            if p not in keep:
                keep.add(p)
                stack.append(p)
    n_out = 0
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            if line.startswith("##FASTA"):
                break
            if line.startswith("#"):
                fout.write(line)
                continue
            if not line.strip():
                continue
            attrs = _gff_fields(line)
            if attrs is None:
                continue
            m_id = _ID_RE.search(attrs)
            m_par = _PARENT_RE.search(attrs)
            ok = bool(m_id and m_id.group(1) in keep)
            if not ok and m_par and any(p in keep for p in m_par.group(1).split(",")):
                ok = True                     # child without an ID of its own
            if not ok and any(g in ids for g in _gff_geneids(attrs)):
                ok = True
            if ok:
                n_out += 1
                fout.write(line)
    return _summary("gff3", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- UniProt XML

_ENTRY_OPEN_RE = re.compile(r"<entry(?=[\s>/])")
_ACCESSION_RE = re.compile(r"<accession>\s*([^<\s]+)\s*</accession>")
_CHUNK = 1 << 20


def filter_uniprot_xml(src, dst, ids):
    """Keep the XML declaration, root start tag (with its attributes and namespace), every <entry>
    with any <accession> in ids, and everything after the last </entry> (the <copyright> element
    and the root end tag). Entries are copied as text, byte for byte, so nothing is re-serialised;
    the whitespace that preceded each kept entry is kept with it. The result is well-formed XML
    when the input is."""
    n_in = n_out = 0
    matched = set()
    with open_text(src) as fin, open_text(dst, "w") as fout:
        buf = ""
        eof = False
        wrote_prefix = False
        pending_ws = ""     # whitespace between the previous entry (or prefix) and the next one

        def fill():
            nonlocal buf, eof
            chunk = fin.read(_CHUNK)
            if chunk:
                buf += chunk
            else:
                eof = True

        while True:
            m = _ENTRY_OPEN_RE.search(buf)
            if m is None:
                if eof:
                    break
                fill()
                continue
            end = buf.find("</entry>", m.start())
            if end < 0:
                if eof:
                    raise SubsetError(f"{src}: unterminated <entry>")
                fill()
                continue
            end += len("</entry>")
            before = buf[:m.start()]
            if not wrote_prefix:
                stripped = before.rstrip()
                fout.write(stripped)
                pending_ws = before[len(stripped):]
                wrote_prefix = True
            else:
                pending_ws = before
            entry = buf[m.start():end]
            buf = buf[end:]
            n_in += 1
            accs = _ACCESSION_RE.findall(entry)
            hit = [a for a in accs if a in ids]
            if hit:
                matched.update(hit)
                n_out += 1
                fout.write(pending_ws + entry)
        # no more entries: what is left is the tail (copyright, root end tag) - or the whole file
        fout.write(buf)
    return _summary("uniprot-xml", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- FASTA

def fasta_accession(header):
    """Accession from a FASTA header line (without the leading '>'):
    'sp|P10635-2|CP2D6_HUMAN ...' -> 'P10635-2'; 'P10635 desc' -> 'P10635'."""
    first = header.split(None, 1)[0] if header.strip() else ""
    if "|" in first:
        parts = first.split("|")
        return parts[1] if len(parts) > 1 and parts[1] else parts[0]
    return first


def filter_fasta(src, dst, ids):
    """Keep records whose header accession is in ids; an isoform header (>sp|P10635-2|...) matches
    on its base accession, and a plain '>ACC description' header is accepted. Text before the
    first header is dropped."""
    n_in = n_out = 0
    matched = set()
    keeping = False
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            if line.startswith(">"):
                n_in += 1
                acc = fasta_accession(line[1:])
                base = _base_accession(acc)
                hit = acc if acc in ids else (base if base in ids else None)
                keeping = hit is not None
                if keeping:
                    matched.add(hit)
                    n_out += 1
            if keeping:
                fout.write(line)
    return _summary("fasta", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- tab files

_TOKEN_SPLIT_RE = re.compile(r"[|;,]")


def _cell_hit(cell, ids):
    """The id matched by a tab cell, or None. The whole cell is tried first, then each '|' ';' ','
    separated token, each also without a 'db:' prefix (PSI-MITAB 'uniprotkb:P10635') and, for an
    isoform, on its base accession."""
    cell = cell.strip()
    if not cell:
        return None
    if cell in ids:
        return cell
    for tok in _TOKEN_SPLIT_RE.split(cell):
        tok = tok.strip()
        for cand in (tok, tok.rsplit(":", 1)[-1]):
            if cand in ids:
                return cand
            base = _base_accession(cand)
            if base in ids:
                return base
    return None


def parse_columns(spec):
    cols = []
    for part in spec.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) < 1:
            raise SubsetError(f"--column wants 1-based column numbers, got {spec!r}")
        cols.append(int(part) - 1)
    return cols


def filter_tab(src, dst, ids, columns, keep_comments=False):
    """Keep a row when ANY listed column holds an id from ids ('at least one panel gene').
    Lines starting with '#' are always kept; with keep_comments the first line is kept too (a
    header row that has no '#'). Neither counts as a record."""
    n_in = n_out = 0
    matched = set()
    first = True
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            was_first, first = first, False
            if line.startswith("#") or (was_first and keep_comments):
                fout.write(line)
                continue
            if not line.strip():
                continue
            n_in += 1
            cells = line.rstrip("\r\n").split("\t")
            hit = False
            for c in columns:
                if c < len(cells):
                    h = _cell_hit(cells[c], ids)
                    if h is not None:
                        matched.add(h)
                        hit = True
            if hit:
                n_out += 1
                fout.write(line)
    return _summary("tab", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- gene_info

def filter_gene_info(src, dst, ids=None, taxon=None):
    """NCBI gene_info: keep the header line ('#tax_id ...'), rows of tax_id `taxon` (column 1) and,
    when ids is given, rows whose GeneID (column 2) is in ids. With only taxon 9606 this is the
    all-human-genes resolver file."""
    ids = ids or set()
    n_in = n_out = 0
    matched = set()
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            if line.startswith("#"):
                fout.write(line)
                continue
            if not line.strip():
                continue
            n_in += 1
            cols = line.split("\t", 2)
            if len(cols) < 2:
                continue
            if taxon is not None and cols[0] != str(taxon):
                continue
            if ids:
                if cols[1] not in ids:
                    continue
                matched.add(cols[1])
            n_out += 1
            fout.write(line)
    return _summary("gene_info", n_in, n_out, ids, matched)


# ---------------------------------------------------------------- idsets

ITEM_SOURCES = ("ncbigene", "hgnc", "ensembl", "uniprot")


def _iter_items(path):
    """Stream <item> elements of an InterMine items XML file, clearing each after use."""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "item":
            yield el
            el.clear()


def _attrs(item):
    return {a.get("name"): a.get("value") for a in item.findall("attribute")}


def _refs(item, name):
    return [r.get("ref_id") for c in item.findall("collection") if c.get("name") == name
            for r in c.findall("reference")]


def _read_items(root, source, notes):
    paths = sorted(glob.glob(os.path.join(root, source, "items", "*.xml")))
    if not paths:
        notes.append(f"no items for {source} under {root}")
    return paths


def _read_lookup(lookup_dir, symbols, taxon):
    """ids from the resolver cache files for this panel (scope.resolve_gene_ids names them
    <resolver>-<taxon>-<md5 of sorted symbols joined by newline>.txt, in lookup_dir or lookup_dir/data)."""
    key = hashlib.md5("\n".join(sorted(symbols)).encode("utf-8")).hexdigest()
    found = {}
    for resolver, kind in (("resolve_ncbigene_symbols", "entrez"), ("resolve_ensembl_symbols", "ensembl")):
        for d in (lookup_dir, os.path.join(lookup_dir, "data")):
            p = os.path.join(d, f"{resolver}-{taxon}-{key}.txt")
            if os.path.exists(p):
                found[kind] = (p, read_id_file(p))
                break
    return found


def derive_idsets(genes_file, items_root="out", lookup_dir=None, taxon="9606"):
    """Return (sets, info): sets maps entrez/ensembl/uniprot/symbol to a set of ids.

    Only genes whose symbol is in the panel count. Sources:
      entrez   ncbigene items Gene.primaryIdentifier, plus the ncbigene resolver cache file;
      ensembl  ensembl items Gene.secondaryIdentifier, ENSG ids in ncbigene/hgnc secondaryIdentifier,
               plus the ensembl resolver cache file;
      uniprot  primaryAccession of the Protein items of the uniprot source linked to a panel gene
               (and of hgnc Protein items, if any);
      symbol   the panel itself."""
    symbols = sorted(set(read_panel(genes_file)))
    panel = set(symbols)
    sets = {"entrez": set(), "ensembl": set(), "uniprot": set(), "symbol": set(symbols)}
    notes, used = [], []
    # cache stores symbols as given, in file order; its key sorts them (see scope.resolve_gene_ids)
    if lookup_dir and os.path.isdir(lookup_dir):
        for kind, (p, got) in _read_lookup(lookup_dir, read_panel(genes_file), taxon).items():
            sets[kind] |= got
            used.append(p)
    elif lookup_dir:
        notes.append(f"lookup dir {lookup_dir} not found")
    for source in ITEM_SOURCES:
        for path in _read_items(items_root, source, notes):
            used.append(path)
            genes = {}      # item id -> symbol, for panel genes
            gene_prots = {}  # panel gene item id -> protein item ids
            prot_acc = {}   # protein item id -> accession
            for it in _iter_items(path):
                cls = it.get("class")
                if cls == "Gene":
                    a = _attrs(it)
                    sym = a.get("symbol")
                    if sym not in panel:
                        continue
                    genes[it.get("id")] = sym
                    gene_prots[it.get("id")] = _refs(it, "proteins")
                    if source == "ncbigene" and a.get("primaryIdentifier"):
                        sets["entrez"].add(a["primaryIdentifier"])
                    if source == "ensembl" and a.get("secondaryIdentifier"):
                        sets["ensembl"].add(a["secondaryIdentifier"])
                    sec = a.get("secondaryIdentifier") or ""
                    if source in ("ncbigene", "hgnc") and sec.startswith("ENSG"):
                        sets["ensembl"].add(sec)
                elif cls == "Protein" and source in ("uniprot", "hgnc"):
                    a = _attrs(it)
                    if a.get("primaryAccession"):
                        prot_acc[it.get("id")] = (a["primaryAccession"], _refs(it, "genes"))
            if source in ("uniprot", "hgnc"):
                wanted = set()
                for g, prots in gene_prots.items():
                    wanted.update(prots)
                for pid, (acc, gene_refs) in prot_acc.items():
                    if pid in wanted or any(g in genes for g in gene_refs):
                        sets["uniprot"].add(acc)
    if not used:
        raise SubsetError(f"no inputs found: nothing under {items_root} and no usable lookup cache")
    return sets, {"inputs": used, "notes": notes}


def run_idsets(a):
    if not os.path.isfile(a.genes):
        raise SubsetError(f"--genes file not found: {a.genes}")
    lookup = a.lookup_dir
    if lookup is None and os.path.isdir("cached_raw_data/gene-id-lookup"):
        lookup = "cached_raw_data/gene-id-lookup"
    sets, info = derive_idsets(a.genes, a.items_root, lookup, a.taxon)
    os.makedirs(a.out, exist_ok=True)
    names = {"entrez": "entrez.txt", "ensembl": "ensembl.txt", "uniprot": "uniprot.txt", "symbol": "symbol.txt"}
    for kind, fname in names.items():
        with open(os.path.join(a.out, fname), "w", encoding="utf-8", newline="\n") as fh:
            for x in sorted(sets[kind]):
                fh.write(x + "\n")
    with open(a.genes, "rb") as fh:
        md5 = hashlib.md5(fh.read()).hexdigest()
    meta = {
        "genes_file": os.path.abspath(a.genes),
        "genes_md5": md5,
        "taxon": a.taxon,
        "counts": {k: len(v) for k, v in sets.items()},
        "uniprot_reviewed": "not written: the items carry no reviewed (Swiss-Prot) flag",
        "items_root": a.items_root,
        "lookup_dir": lookup,
        "inputs": info["inputs"],
        "notes": info["notes"],
    }
    with open(os.path.join(a.out, "idsets.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"counts": meta["counts"], "genes_md5": md5}))


# ---------------------------------------------------------------- CLI

def run_filter(a):
    fmt = a.format
    if fmt not in FORMATS:
        raise SubsetError(f"unknown format {fmt!r}; use one of {', '.join(FORMATS)}")
    if not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    ids = None
    if a.ids:
        if not os.path.isfile(a.ids):
            raise SubsetError(f"--ids file not found: {a.ids}")
        ids = read_id_file(a.ids)
    elif fmt in NEEDS_IDS:
        raise SubsetError(f"format {fmt} needs --ids FILE")
    if fmt == "tab" and not a.column:
        raise SubsetError("format tab needs --column N[,N...]")
    if os.path.abspath(a.infile) == os.path.abspath(a.outfile):
        raise SubsetError("--in and --out are the same file")
    out_dir = os.path.dirname(os.path.abspath(a.outfile))
    os.makedirs(out_dir, exist_ok=True)
    tmp = a.outfile + ".part"
    if a.outfile.endswith(".gz"):
        tmp = a.outfile[:-3] + ".part.gz"
    try:
        if fmt == "gaf":
            res = filter_gaf(a.infile, tmp, ids)
        elif fmt == "gff3":
            res = filter_gff3(a.infile, tmp, ids)
        elif fmt == "uniprot-xml":
            res = filter_uniprot_xml(a.infile, tmp, ids)
        elif fmt == "fasta":
            res = filter_fasta(a.infile, tmp, ids)
        elif fmt == "tab":
            res = filter_tab(a.infile, tmp, ids, parse_columns(a.column), a.keep_comments)
        else:
            res = filter_gene_info(a.infile, tmp, ids, a.taxon)
        os.replace(tmp, a.outfile)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(json.dumps(res))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("idsets", help="derive the panel id sets")
    s.add_argument("--genes", required=True, help="gene panel file (HGNC symbols, whitespace separated, # comments)")
    s.add_argument("--out", required=True, help="output directory")
    s.add_argument("--items-root", default="out", help="reads <root>/<source>/items/*.xml (default ./out)")
    s.add_argument("--lookup-dir", default=None,
                   help="gene-id lookup cache (default cached_raw_data/gene-id-lookup if present)")
    s.add_argument("--taxon", default="9606", help="taxon of the lookup cache files (default 9606)")
    f = sub.add_parser("filter", help="filter one raw file")
    f.add_argument("--format", required=True, help="|".join(FORMATS))
    f.add_argument("--in", dest="infile", required=True)
    f.add_argument("--out", dest="outfile", required=True)
    f.add_argument("--ids", help="file of ids, one per line")
    f.add_argument("--column", help="tab: 1-based column number(s), comma separated")
    f.add_argument("--taxon", help="gene_info: keep this tax_id")
    f.add_argument("--keep-comments", action="store_true", help="tab: also keep the first line (a header without '#')")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "idsets":
            run_idsets(a)
        else:
            run_filter(a)
    except SubsetError as e:
        print(f"subset_raw: {e}", file=sys.stderr)
        return 2
    except (OSError, ET.ParseError, EOFError, UnicodeDecodeError) as e:
        print(f"subset_raw: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
