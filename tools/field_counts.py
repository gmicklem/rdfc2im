#!/usr/bin/env python3
"""field_counts.py: how many records of a raw data file carry each field, counted by streaming [im-9n4.42].

The data-source status pages (tools/source_pages.py) give, for every field of a source file, the number
of records that carry a value for it, loaded or not, so that a reader can judge whether a field not yet
loaded is worth loading (and see why a voluminous one was left out). This module makes those counts.
Python 3 standard library only. Every counter streams: memory holds the counts and one record, never the
file (the Swiss-Prot XML is 175 MB gzipped, IntAct 1 GB zipped).

  field_counts.py count --format tab|gff3|xml|obo|fasta --in PATH [--unpack zip|tar.gz] [--member GLOB]
                        [--comment C] [--skip-lines N] [--header-line N|first] [--record-key PATH]
                        [--max-seconds S] [--cache-dir DIR]
      Prints one JSON object (see count_file). PATH may be a plain or .gz file, a zip or tar.gz archive
      (members picked by --member, a glob on the full name or the base name), or a directory (its files,
      in name order, picked by --member).

Keys (what a field is called, by format):
  tab    col:N (1-based column). --header-line N names the columns from line N, `first` from the
         first line that is neither skipped nor a comment, `match:TEXT` from a line starting with TEXT
         (which is then never a record, wherever it is)
  gff3   col:N for columns 1-8 (a '.' is no value), col:3=TYPE (rows of each feature type), attr:NAME
         (each column-9 attribute), attr:Dbxref:PREFIX (each Dbxref prefix)
  xml    the element path from the root, namespace stripped, '/'-joined (uniprot/entry/accession); an
         attribute is <path>/@name
  obo    STANZA/TAG (Term/is_a, Typedef/id, header/format-version); STANZA alone counts the stanzas
  fasta  header:db, header:accession, header:entry_name, header:description, header:OS, header:OX,
         header:GN, header:PE, header:SV, sequence

What is counted: `records` is the number of records (a tab or GFF3 row, an OBO [Term] stanza, a FASTA
record, an XML element at --record-key); for each key, `with` is the number of records that carry it at
least once and `values` the number of times it occurs (they differ for repeated XML elements, OBO tags and
Dbxref prefixes). An XML key outside any record has values only. The record definitions are those of
tools/subset_raw.py filter (a GAF row is a line not starting with '!', a tab row a line not starting with
'#' after the kept leading lines, an IntAct or BioGRID record one <interaction>), so a raw file's `records`
is that filter's records_in.

Results are cached in --cache-dir under the file's sha256 and the counting options, so a rebuild with
unchanged data does not count again. A count that runs past --max-seconds stops and says so
(complete: false, with the bytes read): the page then states the share of the file counted.
"""
import argparse
import fnmatch
import gzip
import hashlib
import io
import json
import os
import re
import resource
import sys
import tarfile
import time
import zipfile
from xml.parsers import expat

COUNTER_VERSION = 1
FORMATS = ("tab", "gff3", "xml", "obo", "fasta")
MAX_KEYS = 20000          # an XML file with more distinct paths than this is not one the pages can show
_CHUNK = 1 << 20


class CountError(Exception):
    """A usage or input problem."""


# ---------------------------------------------------------------- inputs

def _match(name, member):
    return member is None or fnmatch.fnmatch(name, member) or fnmatch.fnmatch(os.path.basename(name), member)


def iter_inputs(path, unpack=None, member=None):
    """(name, binary stream) for each input: the file itself, the matching members of a zip or tar.gz
    (in archive order for tar, name order for zip), or the matching files of a directory (name order).
    A .gz file (not an archive) is decompressed."""
    if os.path.isdir(path):
        for n in sorted(os.listdir(path)):
            p = os.path.join(path, n)
            if os.path.isfile(p) and _match(n, member):
                yield from iter_inputs(p)
        return
    if unpack == "zip" or (unpack is None and path.endswith(".zip")):
        with zipfile.ZipFile(path) as z:
            names = sorted(i.filename for i in z.infolist() if not i.is_dir())
            for n in names:
                if _match(n, member):
                    with z.open(n) as fh:
                        yield n, fh
        return
    if unpack == "tar.gz" or (unpack is None and path.endswith((".tar.gz", ".tgz"))):
        with tarfile.open(path, "r|gz") as tf:
            for ti in tf:
                if ti.isfile() and _match(ti.name, member):
                    fh = tf.extractfile(ti)
                    yield ti.name, fh
        return
    if member:
        raise CountError(f"{path}: --member is for an archive or a directory")
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            yield os.path.basename(path), fh
        return
    with open(path, "rb") as fh:
        yield os.path.basename(path), fh


class _Budget:
    """Wall-clock budget shared by every input of one count, and the bytes read so far."""

    def __init__(self, max_seconds):
        self.t0 = time.time()
        self.max_seconds = max_seconds
        self.bytes = 0
        self.stopped = False

    def over(self):
        if self.max_seconds and time.time() - self.t0 > self.max_seconds:
            self.stopped = True
        return self.stopped


class _CountingReader(io.RawIOBase):
    """Binary stream wrapper that counts the bytes read (for the share of a file a stopped count saw)."""

    def __init__(self, fh, budget):
        self.fh, self.budget = fh, budget

    def readable(self):
        return True

    def readinto(self, b):
        data = self.fh.read(len(b))
        n = len(data)
        b[:n] = data
        self.budget.bytes += n
        return n


def _lines(fh, budget):
    text = io.TextIOWrapper(io.BufferedReader(_CountingReader(fh, budget), _CHUNK), encoding="utf-8",
                            errors="replace", newline="")
    n = 0
    for line in text:
        n += 1
        if n % 50000 == 0 and budget.over():
            return
        yield line


# ---------------------------------------------------------------- the counts

class Counts:
    def __init__(self):
        self.records = 0
        self.with_ = {}
        self.values = {}
        self.names = {}

    def add(self, key, n=1):
        self.values[key] = self.values.get(key, 0) + n

    def mark(self, keys):
        for k in keys:
            self.with_[k] = self.with_.get(k, 0) + 1

    def as_dict(self):
        keys = sorted(set(self.values) | set(self.with_), key=_key_order)
        return {"records": self.records,
                "keys": {k: {"with": self.with_.get(k, 0), "values": self.values.get(k, self.with_.get(k, 0))}
                         for k in keys},
                "names": dict(sorted(self.names.items(), key=lambda kv: _key_order(kv[0])))}


def _key_order(k):
    m = re.match(r"^col:(\d+)$", k)
    return (0, int(m.group(1)), "") if m else (1, 0, k)


def _count_tab(fh, c, budget, comment="#", skip_lines=0, header_line=None, first_input=True):
    lineno = 0
    want_header = header_line if first_input else None
    for line in _lines(fh, budget):
        lineno += 1
        if isinstance(header_line, str) and header_line.startswith("match:"):
            # a header line known by how it starts, wherever it is (phenotype.hpoa: after the '#' lines
            # upstream, absent from a filtered copy); never a record, in any input
            if line.startswith(header_line[len("match:"):]):
                if want_header:
                    for i, n in enumerate(line.rstrip("\r\n").split("\t")):
                        c.names[f"col:{i + 1}"] = n.strip()
                    want_header = None
                continue
        elif want_header == "first":
            if (lineno > skip_lines and not (comment and line.startswith(comment)) and line.strip()):
                for i, n in enumerate(line.rstrip("\r\n").split("\t")):
                    c.names[f"col:{i + 1}"] = n.strip()
                want_header = None
                continue
        elif want_header and lineno == want_header:
            for i, n in enumerate(line.rstrip("\r\n").lstrip("#").split("\t")):
                c.names[f"col:{i + 1}"] = n.strip()
            if lineno > skip_lines:
                continue
        if lineno <= skip_lines or (comment and line.startswith(comment)) or not line.strip():
            continue
        c.records += 1
        keys = [f"col:{i + 1}" for i, cell in enumerate(line.rstrip("\r\n").split("\t")) if cell.strip()]
        c.mark(keys)


def _count_gff3(fh, c, budget):
    for line in _lines(fh, budget):
        if line.startswith("##FASTA"):
            break
        if line.startswith("#") or not line.strip():
            continue
        cols = line.rstrip("\r\n").split("\t")
        if len(cols) < 9:
            continue
        c.records += 1
        seen = [f"col:{i + 1}" for i in range(8) if cols[i] and cols[i] != "."]
        seen.append(f"col:3={cols[2]}")
        prefixes = {}
        for part in cols[8].split(";"):
            k, _, v = part.partition("=")
            k = k.strip()
            if not k:
                continue
            seen.append(f"attr:{k}")
            if k == "Dbxref":
                for x in v.split(","):
                    p = x.split(":", 1)[0].strip()
                    if p:
                        prefixes[p] = prefixes.get(p, 0) + 1
        for p, n in prefixes.items():
            c.add(f"attr:Dbxref:{p}", n)
            seen.append(f"attr:Dbxref:{p}")
        for k in seen:
            if not k.startswith("attr:Dbxref:"):
                c.add(k)
        c.mark(set(seen))


def _local(name):
    return name.rsplit(" ", 1)[-1].rsplit(":", 1)[-1]


def _count_xml(fh, c, budget, record_key=None):
    stack = []
    seen = None
    values = c.values

    def start(name, attrs):
        nonlocal seen
        path = (stack[-1] + "/" + _local(name)) if stack else _local(name)
        stack.append(path)
        values[path] = values.get(path, 0) + 1
        if path == record_key:
            c.records += 1
            seen = set()
        if seen is not None:
            seen.add(path)
        for a in attrs:
            ap = path + "/@" + _local(a)
            values[ap] = values.get(ap, 0) + 1
            if seen is not None:
                seen.add(ap)

    def end(name):
        nonlocal seen
        path = stack.pop()
        if path == record_key and seen is not None:
            c.mark(seen)
            seen = None

    p = expat.ParserCreate(namespace_separator=" ")
    p.StartElementHandler = start
    p.EndElementHandler = end
    while True:
        chunk = fh.read(_CHUNK)
        if not chunk:
            break
        budget.bytes += len(chunk)
        p.Parse(chunk, False)
        if len(values) > MAX_KEYS:
            raise CountError(f"more than {MAX_KEYS} distinct XML paths")
        if budget.over():
            return
    p.Parse(b"", True)


def _count_obo(fh, c, budget):
    stanza, seen = "header", set()

    def flush():
        c.mark(seen)

    for line in _lines(fh, budget):
        s = line.strip()
        if not s or s.startswith("!"):
            continue
        if s.startswith("[") and s.endswith("]"):
            flush()
            stanza, seen = s[1:-1], set()
            c.add(stanza)
            if stanza == "Term":
                c.records += 1
            continue
        tag = s.split(":", 1)[0].strip()
        k = f"{stanza}/{tag}"
        c.add(k)
        seen.add(k)
    flush()


_FASTA_TAG_RE = re.compile(r"\s(OS|OX|GN|PE|SV)=")


def fasta_header_fields(header):
    """{key: value} of a FASTA header (without '>'): UniProt's 'db|accession|entry_name description OS=..
    OX=.. GN=.. PE=.. SV=..' form; a plain '>id description' gives accession and description."""
    out = {}
    first, _, rest = header.strip().partition(" ")
    parts = first.split("|")
    if len(parts) >= 3:
        out.update({"header:db": parts[0], "header:accession": parts[1], "header:entry_name": parts[2]})
    elif first:
        out["header:accession"] = first
    pieces = _FASTA_TAG_RE.split(" " + rest)
    if pieces and pieces[0].strip():
        out["header:description"] = pieces[0].strip()
    for tag, val in zip(pieces[1::2], pieces[2::2]):
        if val.strip():
            out[f"header:{tag}"] = val.strip()
    return {k: v for k, v in out.items() if v}


def _count_fasta(fh, c, budget):
    has_seq = None
    for line in _lines(fh, budget):
        if line.startswith(">"):
            if has_seq:
                c.mark(["sequence"])
            c.records += 1
            keys = list(fasta_header_fields(line[1:]))
            c.mark(keys)
            has_seq = False
        elif has_seq is not None and line.strip():
            has_seq = True
    if has_seq:
        c.mark(["sequence"])


def count_file(path, fmt, unpack=None, member=None, comment=None, skip_lines=0, header_line=None,
               record_key=None, max_seconds=None):
    """Count one input (see iter_inputs). Returns {format, records, keys: {key: {with, values}}, names,
    inputs: [names], complete, bytes_read, seconds, peak_rss_mb}."""
    if fmt not in FORMATS:
        raise CountError(f"unknown format {fmt!r}; one of {', '.join(FORMATS)}")
    if fmt == "xml" and not record_key:
        raise CountError("xml needs --record-key (the path of the record element)")
    c = Counts()
    budget = _Budget(max_seconds)
    inputs = []
    for i, (name, fh) in enumerate(iter_inputs(path, unpack, member)):
        inputs.append(name)
        if fmt == "tab":
            _count_tab(fh, c, budget, "#" if comment is None else comment, skip_lines, header_line, i == 0)
        elif fmt == "gff3":
            _count_gff3(fh, c, budget)
        elif fmt == "xml":
            _count_xml(fh, c, budget, record_key)
        elif fmt == "obo":
            _count_obo(fh, c, budget)
        else:
            _count_fasta(fh, c, budget)
        if budget.stopped:
            break
    if not inputs:
        raise CountError(f"{path}: no input matches {member!r}")
    res = {"format": fmt, "counter_version": COUNTER_VERSION}
    res.update(c.as_dict())
    res.update({"inputs": inputs, "complete": not budget.stopped, "bytes_read": budget.bytes,
                "seconds": round(time.time() - budget.t0, 1),
                "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)})
    return res


# ---------------------------------------------------------------- sha256 and the cache

def sha256_file(path, cache_dir=None):
    """sha256 of a file (or, for a directory, of its files' names and sha256s in name order). With
    cache_dir, remembered under the file's real path, size and mtime, so an unchanged file is hashed once."""
    if os.path.isdir(path):
        h = hashlib.sha256()
        for n in sorted(os.listdir(path)):
            p = os.path.join(path, n)
            if os.path.isfile(p):
                h.update(f"{n}\t{sha256_file(p, cache_dir)}\n".encode())
        return h.hexdigest()
    st = os.stat(path)
    ident = f"{os.path.realpath(path)}\t{st.st_size}\t{st.st_mtime_ns}"
    idx = os.path.join(cache_dir, "sha256", hashlib.md5(ident.encode()).hexdigest() + ".txt") if cache_dir else None
    if idx and os.path.exists(idx):
        with open(idx, encoding="utf-8") as fh:
            got = fh.read().split("\n")
        if len(got) >= 2 and got[1] == ident:
            return got[0]
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if idx:
        os.makedirs(os.path.dirname(idx), exist_ok=True)
        with open(idx + ".part", "w", encoding="utf-8") as fh:
            fh.write(digest + "\n" + ident + "\n")
        os.replace(idx + ".part", idx)
    return digest


def spec_of(fmt, unpack=None, member=None, comment=None, skip_lines=0, header_line=None, record_key=None):
    return {"format": fmt, "unpack": unpack, "member": member, "comment": comment, "skip_lines": skip_lines or 0,
            "header_line": header_line, "record_key": record_key}


def count_cached(path, spec, cache_dir=None, max_seconds=None, log=None):
    """count_file for `spec` (spec_of), from cache_dir when the same file (sha256) was counted the same way
    before. A stopped (incomplete) count is cached too, under its budget, so a larger budget counts again."""
    digest = sha256_file(path, cache_dir)
    key = hashlib.sha256(json.dumps([COUNTER_VERSION, digest, spec, max_seconds], sort_keys=True).encode()).hexdigest()
    cpath = os.path.join(cache_dir, "counts", key[:32] + ".json") if cache_dir else None
    if cpath and os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as fh:
            res = json.load(fh)
        res["cached"] = True
        return res
    if log:
        log(f"counting {path} ({spec['format']})")
    res = count_file(path, max_seconds=max_seconds, **{k: v for k, v in spec.items() if k != "format"},
                     fmt=spec["format"])
    res["sha256"] = digest
    if cpath:
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        with open(cpath + ".part", "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1, sort_keys=True)
        os.replace(cpath + ".part", cpath)
    res["cached"] = False
    return res


# ---------------------------------------------------------------- CLI

def _header_line(v):
    if v is None or v == "first" or v.startswith("match:"):
        return v
    return int(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count", help="count the fields of one file")
    c.add_argument("--format", required=True, choices=FORMATS)
    c.add_argument("--in", dest="path", required=True)
    c.add_argument("--unpack", choices=("zip", "tar.gz"))
    c.add_argument("--member")
    c.add_argument("--comment")
    c.add_argument("--skip-lines", type=int, default=0)
    c.add_argument("--header-line", type=_header_line)
    c.add_argument("--record-key")
    c.add_argument("--max-seconds", type=float)
    c.add_argument("--cache-dir")
    a = ap.parse_args(argv)
    try:
        spec = spec_of(a.format, a.unpack, a.member, a.comment, a.skip_lines, a.header_line, a.record_key)
        res = count_cached(a.path, spec, a.cache_dir, a.max_seconds)
    except (CountError, OSError, expat.ExpatError) as e:
        print(f"field_counts: {e}", file=sys.stderr)
        return 2
    json.dump(res, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
