#!/usr/bin/env python3
"""subset_raw.py: cut raw upstream files down to a gene panel before a stock InterMine loader reads them.

The stock loaders (UniProt XML, GO annotation GAF, NCBI GFF3, FASTA, interaction and orthologue
tab files) have no gene filter, so for a demo build the raw files are pre-filtered here. Python 3
standard library only; every filter streams (input files can be 400 MB) and `.gz` is read and
written transparently by file suffix.

  subset_raw.py idsets --genes FILE --out DIR [--items-root DIR] [--lookup-dir DIR] [--taxon ID]
      Derive the panel id sets (entrez.txt, ensembl.txt, uniprot.txt, symbol.txt, idsets.json).

  subset_raw.py filter --format gaf|gff3|uniprot-xml|fasta|tab|gene_info|psi-xml|interpro-xml --in PATH|URL --out PATH
                       [--ids FILE] [--column N[,N...]] [--taxon ID] [--keep-comments]
      Filter one raw file; prints one JSON line with the record counts. gff3 also takes
      --keep-types gene (rows of that type kept for every id, without descendants). psi-xml
      (PSI-MI 2.5 XML) takes --xref-db DB[,DB...] (which xrefs carry the panel ids) and, for a zip
      input, --member GLOB; --out is then a directory, one filtered file per member.

  subset_raw.py ipr-ids --in FILTERED_PROTEIN2IPR --out DIR
      ipr.txt: the InterPro entries of the panel's domain matches (interpro.xml is then cut to them).

  subset_raw.py partner-ids --in PANTHER_FILE --ids UNIPROT_IDS --out DIR
      mgi.txt and rgd.txt: the MGI and RGD ids of every gene on a PANTHER row with a panel gene.

  subset_raw.py chromosome-lengths --in GFF --out ITEMS.xml [--taxon ID] [--data-set NAME]
      Chromosome lengths from the ##sequence-region lines, as Items XML (see chromosome_lengths).

  subset_raw.py panel-items --genes FILE --in ITEMS.xml --out ITEMS.xml [--lookup-dir DIR]
      The panel genes' part of an items file fetched for every gene (see panel_items).

  subset_raw.py cited-pmids --in ITEMS.xml [ITEMS.xml ...] --out FILE
      The pubMedId of every linked Publication item: the pubmed source's PMID list (see cited_pmids).

Per-format rules are in each filter function's docstring and in USAGE.md.
"""
import argparse
import glob
import gzip
import hashlib
import http.client
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

FORMATS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "gene_info", "psi-xml", "interpro-xml")
NEEDS_IDS = ("gaf", "gff3", "uniprot-xml", "fasta", "tab", "psi-xml", "interpro-xml")


class SubsetError(Exception):
    """A usage or input problem (reported on stderr, exit status 2)."""


# ---------------------------------------------------------------- file helpers

def is_url(path):
    return str(path).startswith(("http://", "https://"))


class HttpStream(io.RawIOBase):
    """A read-only byte stream over an http(s) URL that reconnects with a Range request when the connection
    drops, so a one-hour download of a multi-gigabyte file (protein2ipr.dat.gz, 13.8 GB) survives a broken
    connection without starting again [im-9n4.27]. Nothing is written to disk."""

    def __init__(self, url, retries=30, timeout=120, opener=None):
        import urllib.request
        self.url, self.retries, self.timeout = url, retries, timeout
        self._urlopen = opener or urllib.request.urlopen
        self._Request = urllib.request.Request
        self.pos = 0
        self.size = None
        self._resp = None

    def readable(self):
        return True

    def _connect(self):
        headers = {"User-Agent": "rdfc2im-subset-raw"}
        if self.pos:
            headers["Range"] = f"bytes={self.pos}-"
        resp = self._urlopen(self._Request(self.url, headers=headers), timeout=self.timeout)
        if self.pos and getattr(resp, "status", 200) != 206:
            resp.close()
            raise SubsetError(f"{self.url}: the server ignored a Range request at byte {self.pos}; "
                              f"the download cannot be resumed (a repeat of the start would corrupt the cut)")
        if self.size is None:
            n = resp.headers.get("Content-Length")
            self.size = int(n) if n and not self.pos else None
        self._resp = resp

    def readinto(self, b):
        import time
        failures = 0
        while True:
            try:
                if self._resp is None:
                    self._connect()
                data = self._resp.read(len(b))
                if not data and self.size is not None and self.pos < self.size:
                    raise OSError("connection closed early")
                b[:len(data)] = data
                self.pos += len(data)
                return len(data)
            except (OSError, ValueError, http.client.HTTPException) as e:   # URLError and timeouts are OSError
                failures += 1
                if failures > self.retries:
                    raise OSError(f"{self.url}: gave up at byte {self.pos} after {failures} tries: {e}")
                print(f"subset_raw: {self.url}: {e}; reconnecting at byte {self.pos} (try {failures})", file=sys.stderr)
                self._resp = None
                time.sleep(min(30, 2 * failures))

    def close(self):
        if self._resp is not None:
            self._resp.close()
        super().close()


def open_text(path, mode="r"):
    """Open a text file for reading ('r') or writing ('w'); `.gz` suffix means gzip. A URL is streamed (read only;
    gzip when it ends in .gz), nothing stored. Newlines are not translated, so output is byte-faithful to the
    input lines. gzip output has a zero mtime and no stored file name, so the same input always gives the same bytes."""
    if is_url(path):
        if mode != "r":
            raise SubsetError(f"{path}: a URL can only be read")
        raw = io.BufferedReader(HttpStream(path), buffer_size=1 << 20)
        if path.split("?", 1)[0].endswith(".gz"):
            raw = gzip.GzipFile(fileobj=raw, mode="rb")
        return io.TextIOWrapper(raw, encoding="utf-8", newline="")
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


def _gff_type(line):
    """The type (column 3) of a feature line, or None."""
    cols = line.split("\t", 3)
    return cols[2] if len(cols) > 3 else None


def filter_gff3(src, dst, ids, keep_types=()):
    """Keep every directive/comment line ('#...', so each ##sequence-region), features whose Dbxref
    has GeneID:<id> with <id> in ids, and the Parent closure of those: all descendants (exons, CDS,
    transcripts, grandchildren) and, so that no kept feature has a dangling Parent, its ancestors.
    Children may appear before their parents, so this makes two passes over the input: the first
    finds the matching features and the ID/Parent links, the second writes. A '##FASTA' section
    (embedded sequence) ends the features and is not copied.

    keep_types: feature types (column 3, e.g. 'gene') kept for every id, without their descendants -
    the genes outside the panel, so a genome browser shows the panel gene's neighbours (D-1). A
    kept feature of such a type that has a Parent outside the kept set would dangle, so only types
    of top-level features make sense here; a row of a kept type that has a Parent is kept only when
    the parent is kept anyway.

    Memory: the first pass keeps one dict entry (two strings) per feature that has both ID and
    Parent: about 4.6 million for the RefSeq GRCh38 file (measured: about 0.9 GB, 40 s)."""
    keep_types = set(keep_types or ())
    parents = {}      # child ID -> its Parent attribute value (comma-separated IDs)
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
                old = parents.get(fid)
                parents[fid] = m_par.group(1) if old is None else old + "," + m_par.group(1)
            hits = [g for g in _gff_geneids(attrs) if g in ids]
            if hits:
                matched.update(hits)
                if fid:
                    seeds.add(fid)
    def has_seed_ancestor(fid):
        # walks up the Parent links (no children map: that would double the memory)
        todo, seen = parents[fid].split(","), set()
        while todo:
            p = todo.pop()
            if p in seeds:
                return True
            if p not in seen:
                seen.add(p)
                if p in parents:
                    todo.extend(parents[p].split(","))
        return False

    keep = set(seeds)
    for fid in parents:                       # descendants
        if fid not in keep and has_seed_ancestor(fid):
            keep.add(fid)
    stack = list(seeds)
    while stack:                              # ancestors (of the matching features only)
        fid = stack.pop()
        for p in (parents[fid].split(",") if fid in parents else ()):
            if p not in keep:
                keep.add(p)
                stack.append(p)
    del parents
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
            par_kept = bool(m_par) and any(p in keep for p in m_par.group(1).split(","))
            ok = bool(m_id and m_id.group(1) in keep)
            if not ok and not m_id and par_kept:
                ok = True                     # child without an ID of its own
            if not ok and any(g in ids for g in _gff_geneids(attrs)):
                ok = True
            if not ok and keep_types and _gff_type(line) in keep_types and (not m_par or par_kept):
                ok = True                     # a neighbour: the row only, no descendants
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
    separated token, each also without a 'db:' or 'db=' prefix (PSI-MITAB 'uniprotkb:P10635', PANTHER
    'HUMAN|HGNC=8620|UniProtKB=P26367') and, for an isoform, on its base accession."""
    cell = cell.strip()
    if not cell:
        return None
    if cell in ids:
        return cell
    # a versioned Ensembl id (GTEx v8: ENSG00000007372.22) is matched on the id without the version
    v = _ENSEMBL_VERSION_RE.match(cell)
    if v and v.group(1) in ids:
        return v.group(1)
    for tok in _TOKEN_SPLIT_RE.split(cell):
        tok = tok.strip()
        # 'db:id' (PSI-MITAB 'uniprotkb:P10635') and 'db=id' (PANTHER 'UniProtKB=P26367', 'MGI=MGI=97490')
        for cand in (tok, tok.rsplit(":", 1)[-1], tok.rsplit("=", 1)[-1]):
            if cand in ids:
                return cand
            base = _base_accession(cand)
            if base in ids:
                return base
    return None


def parse_types(spec):
    """'gene,pseudogene' -> {'gene', 'pseudogene'}; None or '' -> empty set."""
    return {t.strip() for t in (spec or "").split(",") if t.strip()}


def parse_require(specs):
    """['4=^(PF|SM)'] -> [(3, regex)]: --require COLUMN=REGEX, 1-based column."""
    out = []
    for spec in specs or ():
        col, sep, rx = spec.partition("=")
        if not sep or not col.isdigit() or int(col) < 1 or not rx:
            raise SubsetError(f"--require wants COLUMN=REGEX with a 1-based column, got {spec!r}")
        out.append((int(col) - 1, re.compile(rx)))
    return out


def parse_columns(spec):
    cols = []
    for part in spec.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) < 1:
            raise SubsetError(f"--column wants 1-based column numbers, got {spec!r}")
        cols.append(int(part) - 1)
    return cols


def filter_tab(src, dst, ids, columns, keep_comments=False, drop=(), require=()):
    """Keep a row when ANY listed column holds an id from ids ('at least one panel gene'); with ids None every
    row is kept (only `drop` applies). Lines starting with '#' are always kept; with keep_comments the first
    line is kept too (a header row that has no '#'), and an integer keeps that many leading lines (GTEx's GCT:
    `#1.2`, a dimensions line, then the header). None of them counts as a record.

    drop: 0-based columns taken out of every kept record (not of the kept header lines), for a file whose
    column layout moved since the loader was written: MGI_PhenotypicAllele.rpt gained 'Marker Ensembl ID' as
    column 10, which MgiAllelesConverter reads as the Mammalian Phenotype ids [im-9n4.27].

    require: (0-based column, compiled regex) pairs; a row must match every one to be kept. For a file with
    values the loader throws on: Protein2iprConverter stops on a member-database id it has no name for (NCBIFAM
    'NF00...' is new since its 2022 table) [im-9n4.27]."""
    n_in = n_out = 0
    matched = set()
    keep_lines = int(keep_comments) if keep_comments else 0   # True is 1
    lineno = 0
    drop = sorted(set(drop))
    with open_text(src) as fin, open_text(dst, "w") as fout:
        for line in fin:
            lineno += 1
            if line.startswith("#") or lineno <= keep_lines:
                fout.write(line)
                continue
            if not line.strip():
                continue
            n_in += 1
            cells = line.rstrip("\r\n").split("\t")
            if any(c >= len(cells) or not rx.search(cells[c]) for c, rx in require):
                continue
            hit = ids is None
            if ids is not None:
                for c in columns:
                    if c < len(cells):
                        h = _cell_hit(cells[c], ids)
                        if h is not None:
                            matched.add(h)
                            hit = True
            if hit:
                n_out += 1
                if drop:
                    eol = line[len(line.rstrip("\r\n")):]
                    cells = [x for i, x in enumerate(cells) if i not in drop]
                    line = "\t".join(cells) + eol
                fout.write(line)
    return _summary("tab", n_in, n_out, ids or (), matched)


# ---------------------------------------------------------------- PSI-MI 2.5 XML (IntAct, BioGRID)

# The three element kinds the filter keeps or drops whole, an <entry> start tag and its end tag.
# '(?=[\s>/])' keeps <interactor from matching <interactorRef>/<interactorList>/<interactorType>, and
# <interaction from matching <interactionList>/<interactionType>/<interactionDetectionMethod>.
_PSI_TOKEN_RE = re.compile(r"<(experimentDescription|interactor|interaction)(?=[\s>/])|<entry(?=[\s>/])|</entry>")
_PSI_NESTED_RE = re.compile(r"<(?:interactor|experimentDescription)(?=[\s>/])")
_PSI_XREF_RE = re.compile(r"<(?:primaryRef|secondaryRef)\b[^>]*>")
_PSI_ATTR_RE = re.compile(r'([\w:]+)="([^"]*)"')
_PSI_IREF_RE = re.compile(r"<interactorRef>\s*([^<\s]+)\s*</interactorRef>")
_PSI_EREF_RE = re.compile(r"<experimentRef>\s*([^<\s]+)\s*</experimentRef>")
_ENSEMBL_VERSION_RE = re.compile(r'^(ENS[A-Z]*\d{6,})\.\d+$')
_PSI_NEGATIVE_RE = re.compile(r"<negative>\s*true\s*</negative>")
# one <participant> of an interaction, with the whitespace before it ('<participant(?=...)' is not
# <participantList> or <participantIdentificationMethod>)
_PSI_PARTICIPANT_RE = re.compile(r"(\s*)(<participant(?=[\s>/])[^>]*>.*?</participant>)", re.S)
_PSI_ROLE_RE = re.compile(r"<experimentalRole\b.*?<names>\s*<shortLabel>([^<]*)</shortLabel>", re.S)
_SPOKE_ROLE = "prey"    # both converters' SPOKE_MODEL: no pair is made between two preys
_PSI_TAIL = 64          # longer than any token the scanner looks for


def _psi_start_tag_attrs(text):
    """Attributes of the first (start) tag of a block."""
    end = text.find(">")
    return dict(_PSI_ATTR_RE.findall(text[:end if end >= 0 else len(text)]))


def _psi_scan(fh, where):
    """Tokens of a PSI-MI XML text stream, in order, covering every character once:
    ('text', s), ('entry', start_tag), ('end_entry', s) and ('block', kind, id, s) for each
    <experimentDescription>, <interactor> and <interaction> element (kind is the tag). Streams in
    1 MB chunks; a block is held whole (the largest are a few hundred kB)."""
    buf, pos, eof = "", 0, False

    def fill():
        nonlocal buf, pos, eof
        chunk = fh.read(_CHUNK)
        buf = buf[pos:] + chunk
        pos = 0
        if not chunk:
            eof = True

    while True:
        m = _PSI_TOKEN_RE.search(buf, pos)
        if m is None:
            if eof:
                if pos < len(buf):
                    yield ("text", buf[pos:])
                return
            keep = max(pos, len(buf) - _PSI_TAIL)
            if keep > pos:
                yield ("text", buf[pos:keep])
                pos = keep
            fill()
            continue
        tok = m.group(0)
        if tok == "</entry>":
            if m.start() > pos:
                yield ("text", buf[pos:m.start()])
            yield ("end_entry", tok)
            pos = m.end()
            continue
        gt = buf.find(">", m.end())
        if gt < 0:
            if eof:
                raise SubsetError(f"{where}: unterminated tag {tok}")
            fill()
            continue
        if m.group(1) is None:                        # <entry ...>
            if m.start() > pos:
                yield ("text", buf[pos:m.start()])
            yield ("entry", buf[m.start():gt + 1])
            pos = gt + 1
            continue
        kind = m.group(1)
        if buf[gt - 1] == "/":
            end = gt + 1                              # an empty element
        else:
            close = buf.find(f"</{kind}>", gt)
            if close < 0:
                if eof:
                    raise SubsetError(f"{where}: unterminated <{kind}>")
                fill()
                continue
            end = close + len(kind) + 3
        if m.start() > pos:
            yield ("text", buf[pos:m.start()])
        block = buf[m.start():end]
        yield ("block", kind, _psi_start_tag_attrs(block).get("id"), block)
        pos = end


def _psi_xrefs(block):
    """(db lower-cased, id) of every primaryRef/secondaryRef in a block."""
    out = []
    for tag in _PSI_XREF_RE.findall(block):
        a = dict(_PSI_ATTR_RE.findall(tag))
        if a.get("db") and a.get("id"):
            out.append((a["db"].lower(), a["id"]))
    return out


def _psi_hit(block, ids, xref_dbs):
    """The panel id an <interactor> block matches through an xref of one of xref_dbs, or None. An isoform
    or chain accession (P26367-2, P26367-PRO_0000050180) also matches on its base accession."""
    for db, ident in _psi_xrefs(block):
        if xref_dbs and db not in xref_dbs:
            continue
        if ident in ids:
            return ident
        base = ident.split("-", 1)[0]
        if base in ids:
            return base
    return None


def _unversion_ensembl(block):
    """Drop the version of every Ensembl xref id in a block ('ENSG00000185022.14' -> 'ENSG00000185022').
    Returns (block, number changed). PsiConverter resolves a human interactor by its `ensembl` xrefs
    (psi-intact_config.properties 9606.datasource = ensembl) against NCBI gene_info, whose Ensembl
    cross-references carry no version; IntAct writes versioned ids since HumanMine's 2022 load, so
    without this no human interactor would resolve."""
    n = 0

    def fix(m):
        nonlocal n
        tag = m.group(0)
        a = dict(_PSI_ATTR_RE.findall(tag))
        if (a.get("db") or "").lower() != "ensembl":
            return tag
        v = _ENSEMBL_VERSION_RE.match(a.get("id") or "")
        if not v:
            return tag
        n += 1
        return tag.replace(f'id="{a["id"]}"', f'id="{v.group(1)}"', 1)

    return _PSI_XREF_RE.sub(fix, block), n


def _psi_participants(text):
    """(participant id, interactorRef, experimental role lower-cased) of each participant of an interaction."""
    out = []
    for _, part in _PSI_PARTICIPANT_RE.findall(text):
        ref = _PSI_IREF_RE.findall(part)
        roles = _PSI_ROLE_RE.findall(part)
        out.append((_psi_start_tag_attrs(part).get("id"), ref[0] if ref else None,
                    roles[-1].strip().lower() if roles else ""))
    return out


def _psi_pair_partners(parts, panel):
    """The participants an n-ary interaction must keep so that the converters still make every pair that has
    a panel interactor: the panel participants and every participant the converter pairs with one of them
    (any two distinct interactors, except two preys). The others would only make pairs between two
    non-panel genes."""
    keep = []
    for pid, ref, role in parts:
        if ref in panel or any(r in panel and r != ref and not (ro == _SPOKE_ROLE and role == _SPOKE_ROLE)
                               for _, r, ro in parts):
            keep.append((pid, ref))
    return keep


def _psi_plan(open_stream, where, ids, xref_dbs):
    """Pass 1 over one PSI-MI file: per <entry> (by position), the ids of the interactions to keep (those
    with at least one participant whose interactor matches the panel), and of the interactors and
    experiments they reference. An interaction with more than two participants (a complex, or one bait
    with many preys) keeps only its panel participants and those the converter pairs with them
    (_psi_pair_partners): both converters turn a record into every pair of its participants but two
    preys, so a 583-member complex with one panel gene would load 56,814 pairs of which 204 involve it
    (IntAct human, Oct 2026). `trim` maps such an interaction to the participant ids it keeps. Raises
    SubsetError on the expanded form (interactors or experiments written inside each interaction):
    PsiConverter and BioGridConverter read the compact form only."""
    plan, counts, matched = [], {"interactions": 0, "interactors": 0, "experiments": 0, "negative": 0,
                                 "trimmed": 0, "participants_dropped": 0}, set()
    panel, cur = set(), None
    with open_stream() as fh:
        for tok in _psi_scan(fh, where):
            if tok[0] == "entry":
                panel, cur = set(), {"interaction": set(), "interactor": set(), "experimentDescription": set(),
                                     "trim": {}}
                plan.append(cur)
            elif tok[0] == "block":
                _, kind, bid, text = tok
                if cur is None:
                    raise SubsetError(f"{where}: <{kind}> outside an <entry>")
                if kind == "interactor":
                    counts["interactors"] += 1
                    hit = _psi_hit(text, ids, xref_dbs)
                    if hit:
                        matched.add(hit)
                        panel.add(bid)
                elif kind == "experimentDescription":
                    counts["experiments"] += 1
                else:
                    counts["interactions"] += 1
                    if _PSI_NESTED_RE.search(text, 1):
                        raise SubsetError(f"{where}: interaction {bid} holds its interactors or experiments "
                                          "inline (expanded PSI-MI form); the loaders read the compact form only")
                    if _PSI_NEGATIVE_RE.search(text):
                        counts["negative"] += 1       # "these do NOT interact": the converters cannot tell
                        continue
                    refs = _PSI_IREF_RE.findall(text)
                    if any(r in panel for r in refs):
                        cur["interaction"].add(bid)
                        cur["experimentDescription"].update(_PSI_EREF_RE.findall(text))
                        parts = _psi_participants(text)
                        if len(parts) > 2:
                            keep = _psi_pair_partners(parts, panel)
                            if len(keep) < len(parts):
                                cur["trim"][bid] = {pid for pid, _ in keep}
                                counts["trimmed"] += 1
                                counts["participants_dropped"] += len(parts) - len(keep)
                                refs = [r for _, r in keep]
                        cur["interactor"].update(refs)
    return plan, counts, matched


def _psi_trim(text, keep_ids):
    """An interaction's text without the participants whose id is not in keep_ids."""
    return _PSI_PARTICIPANT_RE.sub(
        lambda m: m.group(0) if _psi_start_tag_attrs(m.group(2)).get("id") in keep_ids else "", text)


def _psi_write(open_stream, where, plan, fout):
    """Pass 2: copy one PSI-MI file, keeping only the planned blocks of each entry. Everything else (the
    entrySet and entry tags, <source>, the list tags, attributes) is copied as it is; the whitespace before
    a dropped block is dropped with it. An interactor already written earlier in the same file (same id) is
    not written again: both converters key interactors by id per file and PsiConverter throws on a repeat."""
    stats = {"interactions": 0, "interactors": 0, "experiments": 0, "ensembl_unversioned": 0,
             "repeated_interactors_dropped": 0}
    written_interactors = set()
    entry = -1
    pending = ""
    with open_stream() as fh:
        for tok in _psi_scan(fh, where):
            if tok[0] in ("text", "entry", "end_entry"):
                if tok[0] == "entry":
                    entry += 1
                fout.write(pending)
                pending = tok[-1]
                continue
            _, kind, bid, text = tok
            keep = bid in plan[entry][kind]
            if keep and kind == "interaction" and bid in plan[entry]["trim"]:
                text = _psi_trim(text, plan[entry]["trim"][bid])
            if keep and kind == "interactor":
                if bid in written_interactors:
                    keep = False
                    stats["repeated_interactors_dropped"] += 1
                else:
                    written_interactors.add(bid)
                    text, n = _unversion_ensembl(text)
                    stats["ensembl_unversioned"] += n
            if keep:
                fout.write(pending + text)
                stats[{"interaction": "interactions", "interactor": "interactors",
                       "experimentDescription": "experiments"}[kind]] += 1
            else:
                fout.write(pending.rstrip(" \t\r\n"))
            pending = ""
        fout.write(pending)
    return stats


def _psi_members(src, member):
    """Sorted member names of zip `src` matching the glob `member` (on the full name or its basename)."""
    import fnmatch
    import zipfile
    with zipfile.ZipFile(src) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    pat = member or "*"
    return sorted(n for n in names if fnmatch.fnmatch(n, pat) or fnmatch.fnmatch(os.path.basename(n), pat))


def filter_psi_xml(src, dst, ids, xref_dbs=(), member=None):
    """PSI-MI 2.5 XML (compact form: <entry> holding <experimentList>, <interactorList> and
    <interactionList>, the participants pointing at interactors by <interactorRef>), as IntAct's species
    files and BioGRID's ORGANISM files are. Keeps every interaction with AT LEAST ONE participant whose
    interactor has an xref (primaryRef or secondaryRef, db one of xref_dbs; any db when empty) holding a
    panel id, trimmed to the participants that pair with a panel one (_psi_plan), and exactly the
    interactors and experiments those interactions reference; whether the
    partner then loads is the converter's (and the ID resolver's) decision. Ensembl xref ids lose their
    version (_unversion_ensembl). A negative interaction (<negative>true</negative>: shown NOT to
    interact; IntAct's human_NN_negative.xml files) is dropped, since neither converter reads the flag and
    it would load as an interaction. Two streaming passes per file (plan, then copy), so memory holds
    only the kept ids.

    src is one XML file (dst the output file) or a zip (dst a directory, `member` a glob picking the
    files): each member with a kept interaction is written to dst under its own base name, which the
    loaders need (BioGridConverter reads the organism out of the file name); a member with none is not
    written."""
    import zipfile
    xref_dbs = {d.strip().lower() for d in (xref_dbs or ()) if d.strip()}
    totals = {"files_in": 0, "files_out": 0, "records_in": 0, "records_out": 0, "negative_dropped": 0,
              "trimmed": 0, "participants_dropped": 0, "interactors_in": 0,
              "interactors_out": 0, "experiments_in": 0, "experiments_out": 0, "ensembl_unversioned": 0,
              "repeated_interactors_dropped": 0}
    matched = set()
    if src.endswith(".zip"):
        members = _psi_members(src, member)
        if not members:
            raise SubsetError(f"{src}: no member matches {member!r}")
        z = zipfile.ZipFile(src)
        os.makedirs(dst, exist_ok=True)
        jobs = [(f"{src}:{m}", (lambda m=m: io.TextIOWrapper(z.open(m), encoding="utf-8", newline="")),
                 os.path.join(dst, os.path.basename(m))) for m in members]
    else:
        if member:
            raise SubsetError("--member is for a zip input")
        z = None
        jobs = [(src, lambda: open_text(src), dst)]
    out_files = []
    try:
        for where, opener, out in jobs:
            plan, counts, hit = _psi_plan(opener, where, ids, xref_dbs)
            matched |= hit
            totals["files_in"] += 1
            totals["records_in"] += counts["interactions"]
            totals["interactors_in"] += counts["interactors"]
            totals["experiments_in"] += counts["experiments"]
            totals["negative_dropped"] += counts["negative"]
            totals["trimmed"] += counts["trimmed"]
            totals["participants_dropped"] += counts["participants_dropped"]
            if z is not None and not any(e["interaction"] for e in plan):
                continue
            tmp = out + ".part"
            with open_text(tmp, "w") as fout:
                st = _psi_write(opener, where, plan, fout)
            os.replace(tmp, out)
            out_files.append(os.path.basename(out))
            totals["files_out"] += 1
            totals["records_out"] += st["interactions"]
            totals["interactors_out"] += st["interactors"]
            totals["experiments_out"] += st["experiments"]
            totals["ensembl_unversioned"] += st["ensembl_unversioned"]
            totals["repeated_interactors_dropped"] += st["repeated_interactors_dropped"]
    finally:
        if z is not None:
            z.close()
    res = _summary("psi-xml", totals["records_in"], totals["records_out"], ids, matched)
    res.update({k: v for k, v in totals.items() if k not in ("records_in", "records_out")})
    if z is not None:
        res["files"] = out_files
    return res


# ---------------------------------------------------------------- PANTHER partner ids

def _panther_cell_ids(cell):
    """('MGI', 'MGI:97490') or ('RGD', '3258') ... for a PANTHER gene cell 'MOUSE|MGI=MGI=97490|UniProtKB=P63015';
    None when the cell has no gene id part. The id is the text after the last '=', with 'MGI:' put back as the
    converter does (PantherConverter prependDBName=MGI,RGD,HGNC), but not for RGD: rgd-identifiers' file lists
    the bare number."""
    parts = cell.strip().split("|")
    if len(parts) < 2 or "=" not in parts[1]:
        return None
    db, ident = parts[1].split("=", 1)[0], parts[1].rsplit("=", 1)[-1]
    return db, (f"MGI:{ident}" if db == "MGI" else ident)


def partner_ids(src, ids, dbs=("MGI", "RGD")):
    """db -> sorted ids of the genes that share a PANTHER row with a panel gene (any gene cell of a row whose
    columns 1 or 2 hit `ids`): the genes PantherConverter will create, which mgi-identifiers and
    rgd-identifiers are then cut down to [im-9n4.11]."""
    out = {d: set() for d in dbs}
    with open_text(src) as fin:
        for line in fin:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\r\n").split("\t")
            if len(cells) < 2 or not any(_cell_hit(c, ids) for c in cells[:2]):
                continue
            for c in cells[:2]:
                got = _panther_cell_ids(c)
                if got and got[0] in out:
                    out[got[0]].add(got[1])
    return {d: sorted(v) for d, v in out.items()}


def run_partner_ids(a):
    if not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    if not os.path.isfile(a.ids):
        raise SubsetError(f"--ids file not found: {a.ids}")
    found = partner_ids(a.infile, read_id_file(a.ids))
    os.makedirs(a.out, exist_ok=True)
    for db, ids in found.items():
        with open(os.path.join(a.out, db.lower() + ".txt"), "w", encoding="utf-8") as fh:
            fh.write("".join(i + "\n" for i in ids))
    print(json.dumps({db.lower(): len(v) for db, v in found.items()}))


# ---------------------------------------------------------------- InterPro

_IPR_START_RE = re.compile(r'^<interpro\s[^>]*?\bid="(IPR\d+)"')
_IPR_REF_RE = re.compile(r'\bipr_ref="(IPR\d+)"')
# the relation lists InterProConverter reads: parent_list, child_list, found_in, contains
_IPR_REL_RE = re.compile(r"<(parent_list|child_list|found_in|contains)>(.*?)</\1>", re.S)


def _interpro_entries(src):
    """(id, text) of each <interpro id="IPR..."> entry of interpro.xml, as it is written: one entry starts on a
    line that begins `<interpro ` and ends on the line `</interpro>`; everything before the first entry is the
    header (kept whole: DOCTYPE, the release dbinfo lines) and what follows the last is the trailer
    (<deleted_entries>). Yields ('', text) for header and trailer lines."""
    entry, ident = [], None
    with open_text(src) as fin:
        for line in fin:
            if ident is None:
                m = _IPR_START_RE.match(line)
                if m:
                    ident, entry = m.group(1), [line]
                else:
                    yield "", line
                continue
            entry.append(line)
            if line.startswith("</interpro>"):
                yield ident, "".join(entry)
                ident, entry = None, []


def filter_interpro_xml(src, dst, ids):
    """interpro.xml cut to the InterPro entries of the panel's protein domain matches (ids: IPR numbers, from the
    filtered protein2ipr) and, one step out, the entries those name in their parent, child, found-in and
    contains lists, so the converter has real names for the relatives instead of bare stubs. The file is read
    twice (the second time with the relatives known). Its <pub_list> publications go with each entry, so the
    mine gets only the PubMed ids the kept entries cite."""
    related = set()
    n_in = 0
    for ident, text in _interpro_entries(src):
        if ident:
            n_in += 1
            if ident in ids:
                for _tag, body in _IPR_REL_RE.findall(text):
                    related.update(_IPR_REF_RE.findall(body))
    keep = set(ids) | related
    n_out = 0
    matched = set()
    with open_text(dst, "w") as fout:
        for ident, text in _interpro_entries(src):
            if not ident:
                fout.write(text)
            elif ident in keep:
                n_out += 1
                if ident in ids:
                    matched.add(ident)
                fout.write(text)
    return _summary("interpro-xml", n_in, n_out, ids, matched)


def ipr_ids(src):
    """Sorted InterPro entry ids (column 2) of a filtered protein2ipr.dat: the entries interpro.xml is cut to."""
    out = set()
    with open_text(src) as fin:
        for line in fin:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.split("\t", 2)
            if len(cells) >= 2 and cells[1].startswith("IPR"):
                out.add(cells[1])
    return sorted(out)


def run_ipr_ids(a):
    if not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    found = ipr_ids(a.infile)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "ipr.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(i + "\n" for i in found))
    print(json.dumps({"ipr": len(found)}))


# ---------------------------------------------------------------- HPO diseases

def disease_ids(src):
    """Sorted disease ids (last column) of a filtered genes_to_phenotype.txt: the diseases hpo-annotation
    will link to panel genes, which phenotype.hpoa (disease-keyed) is then cut down to [im-9n4.15]."""
    out = set()
    with open_text(src) as fin:
        for line in fin:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\r\n").split("\t")
            if len(cells) < 2 or cells[0] == "ncbi_gene_id":
                continue
            if cells[-1].strip():
                out.add(cells[-1].strip())
    return sorted(out)


def run_disease_ids(a):
    if not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    found = disease_ids(a.infile)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "hpo-diseases.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(i + "\n" for i in found))
    by_db = {}
    for d in found:
        by_db[d.split(":", 1)[0]] = by_db.get(d.split(":", 1)[0], 0) + 1
    print(json.dumps({"hpo-diseases": len(found), "by_db": by_db}))


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


# ---------------------------------------------------------------- chromosome lengths

# The GRCh38 RefSeq chromosome accessions and the Chromosome names InterMine's ncbi-gff loader gives
# them: a copy of NcbiGffGFF3SeqHandler.CHROMOSOMES (bio/sources/ncbi-gff). That map has no
# NC_012920.1, so the loader stores no mitochondrial locations and no MT Chromosome; this one leaves
# it out too, or the mine would list an MT chromosome with nothing on it.
REFSEQ_GRCH38_CHROMOSOMES = {
    "NC_000001.11": "1", "NC_000002.12": "2", "NC_000003.12": "3", "NC_000004.12": "4",
    "NC_000005.10": "5", "NC_000006.12": "6", "NC_000007.14": "7", "NC_000008.11": "8",
    "NC_000009.12": "9", "NC_000010.11": "10", "NC_000011.10": "11", "NC_000012.12": "12",
    "NC_000013.11": "13", "NC_000014.9": "14", "NC_000015.10": "15", "NC_000016.10": "16",
    "NC_000017.11": "17", "NC_000018.10": "18", "NC_000019.10": "19", "NC_000020.11": "20",
    "NC_000021.9": "21", "NC_000022.11": "22", "NC_000023.11": "X", "NC_000024.10": "Y",
}


def _xml_attr(s):
    return (str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def chromosome_lengths(src, dst, taxon="9606", data_set="ncbi-gff", data_source="NCBI",
                       chromosomes=None):
    """Chromosome lengths from a GFF3 file's '##sequence-region <seqid> <start> <end>' directives,
    written as InterMine Items XML for the intermine-items-xml-file loader (rdfc2im's humanmine-items
    type): one Organism (taxonId), one DataSource and DataSet (by name), and per sequence-region whose
    seqid the map knows a Chromosome with primaryIdentifier (the loader's name for it), length
    (end - start + 1), organism and dataSets. Nothing in InterMine sets Chromosome.length from a GFF:
    the GFF3 parser skips directives, gff_config.properties excludes 9606 `region` features, and
    create-chromosome-locations-and-lengths sets feature locations and lengths only; only the genome
    FASTA (ncbi-fasta) sets it. Directives only are read (they precede the features in a RefSeq file;
    the whole file is still scanned, since GFF3 allows them anywhere). A seqid given twice with
    different lengths is an error."""
    chromosomes = REFSEQ_GRCH38_CHROMOSOMES if chromosomes is None else chromosomes
    lengths = {}
    n_in = 0
    with open_text(src) as fin:
        for line in fin:
            if line.startswith("##FASTA"):
                break
            if not line.startswith("##sequence-region"):
                continue
            n_in += 1
            parts = line.split()
            if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
                raise SubsetError(f"malformed directive: {line.strip()}")
            name = chromosomes.get(parts[1])
            if name is None:
                continue
            n = int(parts[3]) - int(parts[2]) + 1
            if lengths.setdefault(name, n) != n:
                raise SubsetError(f"{parts[1]}: two sequence-region lengths, {lengths[name]} and {n}")
    order = {v: i for i, v in enumerate(chromosomes.values())}
    with open_text(dst, "w") as fout:
        fout.write('<?xml version="1.0" encoding="UTF-8"?>\n<items>\n')
        fout.write(f'  <item id="0_1" class="Organism" implements="">\n'
                   f'    <attribute name="taxonId" value="{_xml_attr(taxon)}"/>\n  </item>\n')
        fout.write(f'  <item id="0_2" class="DataSource" implements="">\n'
                   f'    <attribute name="name" value="{_xml_attr(data_source)}"/>\n  </item>\n')
        fout.write(f'  <item id="0_3" class="DataSet" implements="">\n'
                   f'    <attribute name="name" value="{_xml_attr(data_set)}"/>\n'
                   f'    <reference name="dataSource" ref_id="0_2"/>\n  </item>\n')
        for i, name in enumerate(sorted(lengths, key=lambda c: order.get(c, len(order)))):
            fout.write(f'  <item id="0_{i + 4}" class="Chromosome" implements="">\n'
                       f'    <attribute name="primaryIdentifier" value="{_xml_attr(name)}"/>\n'
                       f'    <attribute name="length" value="{lengths[name]}"/>\n'
                       f'    <reference name="organism" ref_id="0_1"/>\n'
                       f'    <collection name="dataSets"><reference ref_id="0_3"/></collection>\n'
                       f'  </item>\n')
        fout.write("</items>\n")
    return {"format": "chromosome-lengths", "records_in": n_in, "records_out": len(lengths),
            "chromosomes": {c: lengths[c] for c in sorted(lengths, key=lambda c: order.get(c, len(order)))}}


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


def panel_items(src, dst, entrez=(), symbols=()):
    """Write the part of an rdfc2im items XML file that a panel-scoped fetch of the same source
    would have produced: the Gene items of the panel (Gene.primaryIdentifier in `entrez`, or, when
    no Entrez ids are given, Gene.symbol in `symbols`) and every non-Gene item they reach through
    references and collections, transitively.  Other genes are never followed into.

    Used with `--gene-identifiers all` [im-9n4.40]: the pubmed source is scoped to the PMIDs the
    panel's own data cites, gathered from out/{hgnc,uniprot,gwascatalog,reactome}/items; with hgnc
    fetched for every human gene that file names some 23,500 papers (and 44,000 Entrez ids), and
    the PMID set, its md5 and with it the cached pubmed group would no longer be the panel's.
    Returns counts."""
    entrez, symbols = set(entrez), set(symbols)
    info, gene_ids, seeds = {}, set(), []
    for it in _iter_items(src):
        iid, cls = it.get("id"), it.get("class")
        refs = [r.get("ref_id") for r in it.iter("reference")]
        info[iid] = (cls, refs)
        if cls == "Gene":
            gene_ids.add(iid)
            a = _attrs(it)
            if (entrez and a.get("primaryIdentifier") in entrez) or (not entrez and a.get("symbol") in symbols):
                seeds.append(iid)
    keep, todo = set(seeds), list(seeds)
    while todo:
        for r in info.get(todo.pop(), ("", []))[1]:
            if r not in keep and r not in gene_ids and r in info:
                keep.add(r)
                todo.append(r)
    n = 0
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<items>\n')
        for _, el in ET.iterparse(src, events=("end",)):
            if el.tag == "item":
                if el.get("id") in keep:
                    fh.write("  " + ET.tostring(el, encoding="unicode").strip() + "\n")
                    n += 1
                el.clear()
        fh.write("</items>\n")
    return {"items_in": len(info), "genes_in": len(gene_ids), "panel_genes": len(seeds), "items_out": n}


PMID_RE = re.compile(r"^[1-9][0-9]{0,8}$")


def cited_pmids(paths, dst):
    """Write the PubMed ids the citing sources' items cite, one per line, sorted as numbers: the
    pubMedId of every Publication item that another item of the same file refers to, or that itself
    refers to another item (uniprot's Publication.entities, gwascatalog's GWAS.publication, hgnc's
    Gene.publications).  Nothing else counts: masses, Entrez and cross-reference ids, years and page
    numbers are not PMIDs even when they are numbers that some paper has as its PMID, a PMID in a
    description creates no object, and a Publication nothing links to would load uncited [im-9n4.48].

    Missing paths are skipped (reported on stderr); an empty result is an error and writes nothing,
    because an empty --pmids list once made the pubmed fetch take all of PubMed."""
    pmids, n_files, n_pub, n_cited = set(), 0, 0, 0
    for path in paths:
        if not os.path.isfile(path):
            print(f"cited-pmids: {path}: no such file, skipped", file=sys.stderr)
            continue
        n_files += 1
        pubs, linked = {}, set()   # Publication item id -> pubMedId; item ids that are linked
        for it in _iter_items(path):
            iid = it.get("id")
            refs = [r.get("ref_id") for r in it.iter("reference")]
            if refs:
                linked.add(iid)
                linked.update(refs)
            if it.get("class") == "Publication":
                pm = (_attrs(it).get("pubMedId") or "").strip()
                if PMID_RE.match(pm):
                    pubs[iid] = pm
        n_pub += len(pubs)
        cited = {pm for iid, pm in pubs.items() if iid in linked}
        n_cited += sum(1 for iid in pubs if iid in linked)
        pmids |= cited
    if not pmids:
        raise SubsetError(f"no cited PubMed id in {', '.join(paths)}")
    tmp = dst + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for pm in sorted(pmids, key=int):
            fh.write(pm + "\n")
    os.replace(tmp, dst)
    return {"files": n_files, "publications": n_pub, "cited": n_cited, "uncited": n_pub - n_cited, "pmids": len(pmids)}


def run_cited_pmids(a):
    print(json.dumps(cited_pmids(a.inputs, a.out)))


def run_panel_items(a):
    entrez = set()
    if a.lookup_dir:
        found = _read_lookup(a.lookup_dir, read_panel(a.genes), a.taxon)
        entrez = found.get("entrez", ("", set()))[1]
    print(json.dumps(panel_items(a.input, a.out, entrez, read_panel(a.genes))))


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
    # not a panel set: the RefSeq accessions of the GRCh38 chromosomes the ncbi-gff loader maps,
    # which cut the genome FASTA (ncbi-fasta) down to them (ids: chromosomes in stock_sources.yaml)
    with open(os.path.join(a.out, "chromosomes.txt"), "w", encoding="utf-8", newline="\n") as fh:
        for acc in REFSEQ_GRCH38_CHROMOSOMES:
            fh.write(acc + "\n")
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
    if not is_url(a.infile) and not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    ids = None
    if a.ids:
        if not os.path.isfile(a.ids):
            raise SubsetError(f"--ids file not found: {a.ids}")
        ids = read_id_file(a.ids)
    elif fmt in NEEDS_IDS and not (fmt == "tab" and (a.drop_columns or a.require)):
        raise SubsetError(f"format {fmt} needs --ids FILE")
    if (a.drop_columns or a.require) and fmt != "tab":
        raise SubsetError("--drop-columns and --require are for format tab only")
    if fmt == "tab" and not a.column:
        raise SubsetError("format tab needs --column N[,N...]")
    if a.keep_types and fmt != "gff3":
        raise SubsetError("--keep-types is for format gff3 only")
    if os.path.abspath(a.infile) == os.path.abspath(a.outfile):
        raise SubsetError("--in and --out are the same file")
    if (a.member or a.xref_db) and fmt != "psi-xml":
        raise SubsetError("--member and --xref-db are for format psi-xml only")
    if fmt == "psi-xml" and a.infile.endswith(".zip"):
        return run_filter_psi_zip(a, ids)
    out_dir = os.path.dirname(os.path.abspath(a.outfile))
    os.makedirs(out_dir, exist_ok=True)
    tmp = a.outfile + ".part"
    if a.outfile.endswith(".gz"):
        tmp = a.outfile[:-3] + ".part.gz"
    try:
        if fmt == "gaf":
            res = filter_gaf(a.infile, tmp, ids)
        elif fmt == "gff3":
            res = filter_gff3(a.infile, tmp, ids, parse_types(a.keep_types))
        elif fmt == "uniprot-xml":
            res = filter_uniprot_xml(a.infile, tmp, ids)
        elif fmt == "fasta":
            res = filter_fasta(a.infile, tmp, ids)
        elif fmt == "tab":
            res = filter_tab(a.infile, tmp, ids, parse_columns(a.column), max(a.keep_lines, 1 if a.keep_comments else 0),
                             parse_columns(a.drop_columns) if a.drop_columns else (), parse_require(a.require))
        elif fmt == "interpro-xml":
            res = filter_interpro_xml(a.infile, tmp, ids)
        elif fmt == "psi-xml":
            res = filter_psi_xml(a.infile, tmp, ids, parse_types(a.xref_db))
        else:
            res = filter_gene_info(a.infile, tmp, ids, a.taxon)
        os.replace(tmp, a.outfile)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(json.dumps(res))


def run_filter_psi_zip(a, ids):
    """psi-xml from a zip: the filtered members go to the directory --out, written in a sibling .part
    directory first so a failed run leaves no half-filtered set behind."""
    import shutil
    out = os.path.abspath(a.outfile).rstrip("/")
    if os.path.isfile(out):
        raise SubsetError(f"--out {out}: a zip input writes a directory, and this is a file")
    tmp = out + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        res = filter_psi_xml(a.infile, tmp, ids, parse_types(a.xref_db), a.member)
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.rename(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
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
    f.add_argument("--in", dest="infile", required=True, help="a file, or an http(s) URL streamed (gzip when it ends .gz)")
    f.add_argument("--out", dest="outfile", required=True)
    f.add_argument("--ids", help="file of ids, one per line")
    f.add_argument("--column", help="tab: 1-based column number(s), comma separated")
    f.add_argument("--taxon", help="gene_info: keep this tax_id")
    f.add_argument("--keep-comments", action="store_true", help="tab: also keep the first line (a header without '#')")
    f.add_argument("--keep-lines", type=int, default=0, help="tab: keep the first N lines whatever they hold (a GCT file has 3)")
    f.add_argument("--drop-columns", help="tab: 1-based column number(s) taken out of every kept record "
                                          "(with no --ids every row is kept)")
    f.add_argument("--require", action="append", metavar="COLUMN=REGEX",
                   help="tab: keep only rows whose 1-based COLUMN matches REGEX (repeatable, all must match)")
    f.add_argument("--keep-types", help="gff3: feature types kept for every id, without descendants (e.g. gene)")
    f.add_argument("--xref-db", help="psi-xml: xref db names (comma separated, any case) whose ids are matched")
    f.add_argument("--member", help="psi-xml from a zip: glob of the members to filter (default every file)")
    q = sub.add_parser("partner-ids", help="mgi.txt / rgd.txt: the partner genes of the panel's PANTHER rows")
    q.add_argument("--in", dest="infile", required=True, help="the filtered PANTHER file")
    q.add_argument("--ids", required=True, help="the panel's UniProt id set")
    q.add_argument("--out", required=True, help="directory the id sets go to (next to the panel's)")
    d = sub.add_parser("disease-ids", help="hpo-diseases.txt: the diseases of a filtered genes_to_phenotype.txt")
    d.add_argument("--in", dest="infile", required=True, help="the filtered genes_to_phenotype.txt")
    d.add_argument("--out", required=True, help="directory the id set goes to (next to the panel's)")
    r = sub.add_parser("ipr-ids", help="ipr.txt: the InterPro entries of a filtered protein2ipr.dat")
    r.add_argument("--in", dest="infile", required=True, help="the filtered protein2ipr.dat")
    r.add_argument("--out", required=True, help="directory the id set goes to (next to the panel's)")
    c = sub.add_parser("chromosome-lengths",
                       help="Items XML of Chromosome lengths from a GFF3 file's ##sequence-region lines")
    c.add_argument("--in", dest="infile", required=True)
    c.add_argument("--out", dest="outfile", required=True)
    c.add_argument("--taxon", default="9606")
    c.add_argument("--data-set", default="ncbi-gff", help="DataSet name (default ncbi-gff, the loader's own)")
    c.add_argument("--data-source", default="NCBI", help="DataSource name (default NCBI)")
    i = sub.add_parser("panel-items", help="the panel genes' part of an rdfc2im items XML file (see panel_items)")
    i.add_argument("--genes", required=True, help="gene panel file")
    i.add_argument("--in", dest="input", required=True, help="items XML of a source fetched for every gene")
    i.add_argument("--out", required=True, help="items XML to write")
    i.add_argument("--lookup-dir", default=None, help="gene-id lookup cache: panel genes by Entrez id (else by symbol)")
    i.add_argument("--taxon", default="9606")
    m = sub.add_parser("cited-pmids", help="the PubMed ids the Publication items of rdfc2im items XML files are cited for"
                                           " (see cited_pmids): the pubmed source's --pmids list")
    m.add_argument("--in", dest="inputs", nargs="+", required=True, help="items XML files (a missing one is skipped)")
    m.add_argument("--out", required=True, help="PMID list to write, one per line")
    return p


def run_chromosome_lengths(a):
    if not os.path.isfile(a.infile):
        raise SubsetError(f"input not found: {a.infile}")
    if os.path.abspath(a.infile) == os.path.abspath(a.outfile):
        raise SubsetError("--in and --out are the same file")
    os.makedirs(os.path.dirname(os.path.abspath(a.outfile)), exist_ok=True)
    tmp = a.outfile + ".part"
    try:
        res = chromosome_lengths(a.infile, tmp, a.taxon, a.data_set, a.data_source)
        if not res["records_out"]:
            raise SubsetError(f"{a.infile}: no ##sequence-region line names a known chromosome")
        os.replace(tmp, a.outfile)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(json.dumps(res))


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "idsets":
            run_idsets(a)
        elif a.cmd == "chromosome-lengths":
            run_chromosome_lengths(a)
        elif a.cmd == "partner-ids":
            run_partner_ids(a)
        elif a.cmd == "disease-ids":
            run_disease_ids(a)
        elif a.cmd == "ipr-ids":
            run_ipr_ids(a)
        elif a.cmd == "panel-items":
            run_panel_items(a)
        elif a.cmd == "cited-pmids":
            run_cited_pmids(a)
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
