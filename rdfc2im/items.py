"""Emit InterMine Items XML from a source's cleaned tables (out/<src>/tsv/*.tsv + columns.tsv).

Every row of every table is split into objects by (class, via): the root object (via empty)
plus one object per linked class.  Objects are keyed by the class's key attribute (or by all
their values when the class has none), so the same Gene met in ten tables is one <item>.
Links follow the mapping's `via` (Gene.synonyms -> Synonym); reverse references are set too
(Synonym.subject -> Gene).  Same-class links (OntologyTerm.parents) work because the target is
simply another item of the root class.

Output: out/<src>/items/<src>.xml, loadable by the stock `intermine-items-xml-file` source
(here registered as `humanmine-items` so keys/additions can travel with it).
"""
from __future__ import annotations
import csv
import os
import unicodedata
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import quoteattr

from .mapping import read_tsv
from .model import InterMineModel

# InterMine's have.large.file.xml.tgt loader (FullXmlConverterTask -> the postgres COPY BINARY
# writer) cannot handle non-ASCII bytes: confirmed on a minimal repro that a single "alpha"
# (Greek letter, U+03B1) in one attribute value is enough to fail the whole retrieve with
# "PSQLException: invalid byte sequence for encoding UTF8: 0x00" - the writer appears to
# mis-handle multi-byte UTF-8 rather than reject it cleanly. have.file.xml.tgt (XmlDataLoaderTask)
# does not have this bug, but at real data volumes it opens far more concurrent connections than
# Postgres's default allows and is markedly slower - not a viable swap for every source. Rather
# than block every source with any non-ASCII text (HGNC's alt_label synonyms legitimately carry
# Greek letters, e.g. "ERalpha"), transliterate attribute values to their closest ASCII on the
# way into the items file. This only affects what InterMine loads, not rdfc2im's own tables,
# filters or dedup, which still see the real Unicode text.
_GREEK_TO_ASCII = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega", "ɣ": "gamma",
}
_PUNCT_TO_ASCII = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', "−": "-",
}


def to_ascii(s: str) -> str:
    """Closest-ASCII transliteration for InterMine's items-loading path; see the module note.
    Known Greek letters spell out by name; known "smart" punctuation maps to its ASCII form;
    anything else goes through NFKD (handles ligatures and accented Latin - e.g. "fi" from the
    fi-ligature, "e" from "e-acute") and drops what still isn't ASCII, so no attribute value can
    ever carry a byte this loader chokes on. A character with no ASCII form at all becomes "?"
    rather than vanishing silently."""
    if s.isascii():
        return s
    out = []
    for ch in s:
        if ch in _GREEK_TO_ASCII:
            out.append(_GREEK_TO_ASCII[ch])
        elif ch in _PUNCT_TO_ASCII:
            out.append(_PUNCT_TO_ASCII[ch])
        elif ch.isascii():
            out.append(ch)
        else:
            decomposed = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append(decomposed if decomposed.isascii() and decomposed else "?")
    return "".join(out)


# Organism items name themselves.  RDF Portal's own data carries a taxon id and, in most tables,
# nothing else, so an Organism came out of the load with a null name, shortName, genus and
# species: the organism filter, every list-widget title (they print organism.name / shortName) and
# BlueGenes' organism facet were blank, and InterMine's widget service had to learn to take a null
# filter.  Every source's Organism items get the four fields from this table (identical values from
# every source, so no priority fight), or, for a taxon not in it, from a "Genus species" name the
# source itself wrote.  im-ore.16.
ORGANISM_FIELDS = ("name", "shortName", "genus", "species")
KNOWN_ORGANISMS = {   # taxon id -> (genus, species)
    "9606": ("Homo", "sapiens"),
    "10090": ("Mus", "musculus"),
    "10116": ("Rattus", "norvegicus"),
    "7955": ("Danio", "rerio"),
    "7227": ("Drosophila", "melanogaster"),
    "6239": ("Caenorhabditis", "elegans"),
    "559292": ("Saccharomyces", "cerevisiae"),
}


def organism_names(taxon_id: str, name: str = "") -> Optional[Dict[str, str]]:
    """name/shortName/genus/species for a taxon, or None if neither the table nor `name` knows it."""
    if taxon_id in KNOWN_ORGANISMS:
        genus, species = KNOWN_ORGANISMS[taxon_id]
    else:
        bits = name.split()
        if len(bits) != 2:
            return None
        genus, species = bits
    return {"name": f"{genus} {species}", "shortName": f"{genus[0]}. {species}",
            "genus": genus, "species": species}


class Item:
    __slots__ = ("cls", "attrs", "refs", "colls")

    def __init__(self, cls: str):
        self.cls = cls
        self.attrs: Dict[str, str] = {}
        self.refs: Dict[str, tuple] = {}
        self.colls: Dict[str, List[tuple]] = {}


_INTEGER_TYPES = {"int", "java.lang.Integer", "long", "java.lang.Long", "short", "java.lang.Short"}
_FLOAT_TYPES = {"double", "java.lang.Double", "float", "java.lang.Float"}


def _parses_as_declared_type(typ: str, v: str) -> bool:
    """True unless `typ` is a numeric Java type and `v` does not parse as one - GWAS Catalog
    uses the literal string "NR" ("Not Reported") for a numeric field (riskAlleleFreqInControls)
    on the majority of its rows; found only by an actual load, where InterMine's own loader fails
    the whole retrieve with a bare `NumberFormatException: For input string: "NR"` and no
    indication of which item or field caused it."""
    try:
        if typ in _INTEGER_TYPES:
            int(v)
        elif typ in _FLOAT_TYPES:
            float(v)
        return True
    except ValueError:
        return False


class ItemStore:
    def __init__(self, model: InterMineModel):
        self.model = model
        self.items: Dict[tuple, Item] = {}
        self.conflicts: List[str] = []
        self.dropped: List[str] = []

    def key_for(self, cls: str, values: Dict[str, str]) -> Optional[tuple]:
        # Try every single-field key this class has, not just the model-wide preferred one -
        # different sources populate different keys for the same class (Gene.primaryIdentifier
        # for ncbigene/hgnc, Gene.secondaryIdentifier only for ensembl), and committing to one
        # choice regardless leaves a source that never populates it with no real key at all -
        # see InterMineModel.key_attributes' docstring for what that silently breaks.
        #
        # The key is the value as InterMine will see it, i.e. after to_ascii (write() folds every
        # attribute).  Keyed on the raw Unicode, HPO's three related synonyms of HP:0011002
        # "Albers-Schoenberg", "Albers-Schonberg" and "Albers-Schönberg disease" were three items,
        # two of them identical once written; InterMine keys OntologyTermSynonym on name, so the
        # equivalent-object prefetch of their batch failed ("Duplicate objects found for pk") and
        # the retry of the batch stopped humanmine-hpo with "Given a ProxyReference, but id not in
        # ID Map" on an unrelated term's crossReferences [im-9n4.41].
        for ka in self.model.key_attributes(cls):
            if values.get(ka):
                return (cls, ka, to_ascii(values[ka]))
        vals = "|".join(f"{k}={to_ascii(v)}" for k, v in sorted(values.items()) if v)
        return (cls, "*", vals) if vals else None

    def get(self, cls: str, values: Dict[str, str]) -> Optional[tuple]:
        k = self.key_for(cls, values)
        if k is None:
            return None
        it = self.items.get(k)
        if it is None:
            it = Item(cls)
            self.items[k] = it
        for f, v in values.items():
            if not v:
                continue
            fd = self.model.field(cls, f)
            if fd is not None and fd.kind == "attribute" and not _parses_as_declared_type(fd.type, v):
                if len(self.dropped) < 50:
                    self.dropped.append(f"{cls} {k[2]}: {f} = {v!r} does not parse as {fd.type} - dropped")
                continue
            if f in it.attrs and to_ascii(it.attrs[f]) == to_ascii(v):
                continue          # the same value once written (see key_for): not a conflict
            if f in it.attrs:
                if len(self.conflicts) < 50:
                    self.conflicts.append(f"{cls} {k[2]}: {f} = {it.attrs[f]!r} vs {v!r} (first kept)")
                continue
            it.attrs[f] = v
        return k

    def link(self, src_key: tuple, field: str, dst_key: tuple):
        it = self.items[src_key]
        fd = self.model.field(it.cls, field)
        if fd is None:
            return
        if fd.kind == "collection":
            lst = it.colls.setdefault(field, [])
            if dst_key not in lst:
                lst.append(dst_key)
        else:
            it.refs[field] = dst_key
        # reverse side
        if fd.reverse:
            dst = self.items[dst_key]
            rfd = self.model.field(dst.cls, fd.reverse)
            if rfd is not None:
                if rfd.kind == "collection":
                    lst = dst.colls.setdefault(fd.reverse, [])
                    if src_key not in lst:
                        lst.append(src_key)
                else:
                    dst.refs[fd.reverse] = src_key

    def complete_organisms(self) -> int:
        """Give every Organism item its name, shortName, genus and species (see KNOWN_ORGANISMS).
        A value the source wrote itself stands.  Returns the number of items completed."""
        n = 0
        for it in self.items.values():
            if it.cls != "Organism" or not it.attrs.get("taxonId"):
                continue
            full = organism_names(it.attrs["taxonId"], it.attrs.get("name", ""))
            if not full:
                continue
            before = len(it.attrs)
            for f in ORGANISM_FIELDS:
                if f in self.model.all_fields("Organism"):
                    it.attrs.setdefault(f, full[f])
            n += len(it.attrs) > before
        return n

    def complete_sequences(self) -> Tuple[int, List[str]]:
        """Give each Sequence item its length (the number of residues) and each item that
        references one (Protein.sequence) the same length, as UniprotConverter and FastaLoaderTask
        do.  UniProt's RDF states the residues and their md5 but no length [im-9n4.32].  A value the
        source wrote itself stands.  Returns (items completed, notes): a note for each Sequence whose
        stated md5checksum is not the md5 of its residues (at most 20)."""
        import hashlib
        n, notes = 0, []
        if "length" not in self.model.all_fields("Sequence"):
            return 0, notes
        for k, it in self.items.items():
            res = it.attrs.get("residues") if it.cls == "Sequence" else None
            if not res:
                continue
            if "length" not in it.attrs:
                it.attrs["length"] = str(len(res))
                n += 1
            md5 = it.attrs.get("md5checksum")
            if md5 and md5 != hashlib.md5(res.encode("ascii", "replace")).hexdigest() and len(notes) < 20:
                notes.append(f"Sequence {k[2][:60]}: md5checksum {md5} is not the md5 of its residues")
        for it in self.items.values():
            sk = it.refs.get("sequence")
            seq = self.items.get(sk) if sk else None
            if seq is None or seq.cls != "Sequence" or not seq.attrs.get("length"):
                continue
            fd = self.model.field(it.cls, "length")
            if fd is not None and fd.kind == "attribute" and "length" not in it.attrs:
                it.attrs["length"] = seq.attrs["length"]
                n += 1
        return n, notes

    def organisms_from_genes(self, classes) -> int:
        """Give each item of `classes` (sources.yaml `organism_from_genes`) that has no organism the
        organism of the genes in its `genes` collection, when they agree.  hgnc's Protein items are
        an accession and a gene link only: in a panel build they merge into stock UniProt's
        proteins, which carry the organism, but with every human gene loaded (--gene-identifiers
        all) some 20,000 of them are proteins of their own and would have none [im-9n4.40].
        Returns the number of items linked."""
        n = 0
        for it in self.items.values():
            if it.cls not in classes or "organism" in it.refs or "organism" not in self.model.all_fields(it.cls):
                continue
            found = {self.items[g].refs.get("organism") for g in it.colls.get("genes", []) if g in self.items}
            found.discard(None)
            if len(found) == 1:
                it.refs["organism"] = next(iter(found))
                n += 1
        return n

    def organise_chromosomes(self) -> int:
        """Give each Chromosome the organism of the genes on it.  The sources name a chromosome
        by its number alone ("1"), but InterMine keys one on (primaryIdentifier, organism): with no
        organism two sources' chromosome 1 never merged, so the mine held every chromosome twice,
        both unlinked to any organism.  A chromosome whose genes disagree on the organism is left
        alone.  Returns the number of chromosomes linked."""
        orgs: Dict[tuple, set] = {}
        for it in self.items.values():
            ch, org = it.refs.get("chromosome"), it.refs.get("organism")
            if ch is not None and org is not None and it.cls == "Gene":
                orgs.setdefault(ch, set()).add(org)
        n = 0
        for ck, found in orgs.items():
            ch = self.items.get(ck)
            if ch is not None and ch.cls == "Chromosome" and "organism" not in ch.refs and len(found) == 1 \
                    and "organism" in self.model.all_fields("Chromosome"):
                ch.refs["organism"] = next(iter(found))
                n += 1
        return n

    def write(self, path: str) -> int:
        ids = {k: f"0_{i + 1}" for i, k in enumerate(self.items)}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<items>\n')
            for k, it in self.items.items():
                fh.write(f'  <item id="{ids[k]}" class="{it.cls}" implements="">\n')
                for f, v in it.attrs.items():
                    fh.write(f'    <attribute name="{f}" value={quoteattr(to_ascii(v))}/>\n')
                for f, dk in it.refs.items():
                    if dk in ids:
                        fh.write(f'    <reference name="{f}" ref_id="{ids[dk]}"/>\n')
                for f, lst in it.colls.items():
                    refs = [dk for dk in lst if dk in ids]
                    if refs:
                        fh.write(f'    <collection name="{f}">' + "".join(f'<reference ref_id="{ids[dk]}"/>' for dk in refs) + "</collection>\n")
                fh.write("  </item>\n")
            fh.write("</items>\n")
        return len(ids)


def table_root(cols: List[dict]) -> str:
    """The class a table's rows are about: the root its query was designed around.

    Root choice is a design decision - a table may be built around Protein or around Organism -
    and `rdfc2im translate` records the one it used in columns.tsv's `root` column.  Linking must
    follow that choice.  It used to be inferred from column order instead (first required column,
    else first column), which picks whatever happens to come first: every UniProt table came out
    rooted at Organism, because the taxon constraint precedes the accession, and GWAS Catalog at
    Gene; links were then sought from a class the rows are not about, and Protein, Synonym,
    Publication, GWASResult and GWAS items were created unlinked.  The inference remains only as a
    fallback for columns.tsv files written before the column existed.
    """
    for c in cols:
        if c.get("root"):
            return c["root"]
    return next((c["im_class"] for c in cols if c.get("required") == "yes"), cols[0]["im_class"])


def group_key(model: InterMineModel, root_cls: str, cls: str, via: str) -> Tuple[str, str]:
    """The object a column writes to, as (class, via) - exactly how emit_items groups columns.

    Columns sharing a key and a field write one attribute of one object, so only one value can
    survive.  translate uses this same function to keep that from happening, and check to report
    it, so the three can never disagree about what collides.
    """
    via = via or ""
    if cls != root_cls and not via:
        via = _via_from(model, root_cls, cls)
    # same-class link through an ancestor-typed reference: the target is the root class
    if via and cls != root_cls and model.is_a(root_cls, cls):
        cls = root_cls
    return cls, via


def _via_from(model: InterMineModel, from_cls: str, to_cls: str) -> str:
    for fname, fd in model.all_fields(from_cls).items():
        if fd.kind != "attribute" and (fd.type == to_cls or model.is_a(to_cls, fd.type)):
            return f"{from_cls}.{fname}"
    return ""


def resolve_key_ambiguity(store: ItemStore, cls: str, field: str,
                           prefer_field: Optional[str] = None, prefer_value: Optional[str] = None) -> int:
    """A field this source did not use as ITS OWN merge key (see ItemStore.key_for) can still be
    one InterMine uses in a cross-source integration key - Gene.secondaryIdentifier is not
    ncbigene's key (primaryIdentifier is), but `key_secondaryidentifier_org` merges on it against
    other sources.  If the *upstream data itself* gives two distinct objects in this source's own
    output the same value (real: 255 Ensembl gene ids in NCBI Gene's own cross-reference data are
    each shared by two or more different NCBI Entrez records, an overlapping-transcript/antisense
    annotation ambiguity, not an rdfc2im mapping error - see STATUS.md D14), loading it past that
    key either fails or merges the wrong two objects.

    Grouped by (field value, organism ref) since the key it stands in for is organism-scoped too.
    If prefer_field/prefer_value picks out exactly one holder of a duplicated value, the field is
    kept only there; otherwise the ambiguity has no principled answer and it is dropped from every
    holder - the same "can't resolve cleanly, so don't corrupt" rule `clean_table` already applies
    to a filter-failing required column. Returns the number of items the field was blanked on."""
    groups: Dict[tuple, List[Item]] = {}
    for it in store.items.values():
        if it.cls != cls:
            continue
        v = it.attrs.get(field)
        if v:
            groups.setdefault((v, it.refs.get("organism")), []).append(it)
    blanked = 0
    for (_, items) in ((k, v) for k, v in groups.items() if len(v) > 1):
        keep = None
        if prefer_field and prefer_value:
            matches = [it for it in items if it.attrs.get(prefer_field) == prefer_value]
            if len(matches) == 1:
                keep = matches[0]
        for it in items:
            if it is keep:
                continue
            del it.attrs[field]
            blanked += 1
    return blanked


def defer_to_source(store: ItemStore, other_items: str, cls: str, key: str, fields: List[str]) -> Dict[str, int]:
    """Blank, on this source's `cls` items, each of `fields` whose value the other source's items
    (`other_items`, already written) give to a DIFFERENT object, told apart by `key`.

    [im-9n4.40] With every human gene loaded, the RDF hgnc and ncbigene snapshots disagree on a few
    hundred genes: HGNC still gives RNR1 to Entrez 6052 (NCBI type "other", so not in ncbigene),
    while NCBI's Symbol column gives RNR1 to 4549 (MT-RNR1), and 101 Ensembl ids sit on one Entrez
    gene in ncbigene and on another in hgnc.  Both are keyed on Entrez alone (sources.yaml
    own_keys), so nothing merges wrongly, but the two genes would show the same symbol or Ensembl id.
    ncbigene ranks first for both fields (genomic_priorities), so hgnc yields where they disagree.
    Returns {field: number blanked}; a missing other file is no deferral (a panel-only build)."""
    owners: Dict[str, Dict[str, set]] = {f: {} for f in fields}
    if not os.path.exists(other_items):
        return {}
    import xml.etree.ElementTree as ET
    for _, el in ET.iterparse(other_items):
        if el.tag == "item":
            if el.get("class") == cls:
                a = {x.get("name"): x.get("value") for x in el.findall("attribute")}
                for f in fields:
                    if a.get(f) and a.get(key):
                        owners[f].setdefault(a[f], set()).add(a[key])
            el.clear()
    n = {f: 0 for f in fields}
    for it in store.items.values():
        if it.cls != cls or not it.attrs.get(key):
            continue
        for f in fields:
            v = it.attrs.get(f)
            if v and to_ascii(v) in owners[f] and it.attrs[key] not in owners[f][to_ascii(v)]:
                del it.attrs[f]
                n[f] += 1
    return n


def xref_pairs_from_items(path: str, cls: str, key: str, id_field: str) -> Tuple[List[Tuple[str, str]], set]:
    """(id, key) pairs of the `cls` items another source wrote (e.g. hgnc's Gene: Ensembl id,
    Entrez id), and the set of every `key` value there.  Read from the WRITTEN items, after that
    source's key_ambiguity and defer_to, so the pairs are the Ensembl ids the mine will show.  A
    missing file gives ([], set())."""
    pairs, known = [], set()
    if not os.path.exists(path):
        return pairs, known
    import xml.etree.ElementTree as ET
    for _, el in ET.iterparse(path):
        if el.tag == "item":
            if el.get("class") == cls:
                a = {x.get("name"): x.get("value") for x in el.findall("attribute")}
                if a.get(key):
                    known.add(a[key])
                    if a.get(id_field):
                        pairs.append((a[id_field], a[key]))
            el.clear()
    return pairs, known


def xref_pairs_from_raw(path: str, id_var: str, xref_var: str, prefix: str) -> List[Tuple[str, str]]:
    """(id, key) pairs from a source's own raw cross-reference table (the fetched SPARQL TSV:
    ensembl's main_ensg_xref, rdfs:seeAlso <http://identifiers.org/ncbigene/N>).  The cleaned tsv/
    copy keeps only the IRI's local name, which loses which database it names."""
    out: List[Tuple[str, str]] = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = [h.strip().lstrip("?").strip('"') for h in next(rd, [])]
        if id_var not in header or xref_var not in header:
            return out
        i, j = header.index(id_var), header.index(xref_var)
        for row in rd:
            if len(row) <= max(i, j):
                continue
            v, x = row[i].strip().strip('"'), row[j].strip().strip("<>").strip('"')
            if v and x.startswith(prefix) and x[len(prefix):]:
                out.append((v, x[len(prefix):]))
    return sorted(set(out))


def drop_items(store: ItemStore, keys) -> int:
    """Remove the items `keys` and the items that hang only off them: an item with a reference to
    a removed one (a Synonym's subject, a CrossReference's subject) goes too unless some kept item
    still points at it (CrossReference items are keyed on the identifier and shared).  Returns the
    number of dependent items removed."""
    gone = set(k for k in keys if k in store.items)
    for k in gone:
        del store.items[k]
    pointed = set()
    for it in store.items.values():
        pointed.update(it.refs.values())
        for lst in it.colls.values():
            pointed.update(lst)
    deps = [k for k, it in store.items.items()
            if k not in pointed and any(v in gone for v in it.refs.values())]
    for k in deps:
        del store.items[k]
    for it in store.items.values():
        for f in [f for f, v in it.refs.items() if v in gone]:
            del it.refs[f]
        for f, lst in it.colls.items():
            if any(v in gone for v in lst):
                it.colls[f] = [v for v in lst if v not in gone]
    return len(deps)


def xref_pairing(levels: List[Tuple[str, List[Tuple[str, str]]]], known: Optional[set] = None):
    """The rule of join_on_xref, on the pairs alone: (by_level, got_g, got_e).  by_level is
    [(name, id -> keys, key -> ids, ids whose key is not in `known`)], got_g id -> (key, level) and
    got_e key -> id for every id the levels pair, one-to-one at the level that decides.  Sorted, so
    deterministic."""
    by_level = []
    for name, pairs in levels:
        g2e: Dict[str, set] = {}
        e2g: Dict[str, set] = {}
        for g, e in pairs:
            if known is not None and e not in known:
                continue
            g2e.setdefault(g, set()).add(e)
            e2g.setdefault(e, set()).add(g)
        by_level.append((name, g2e, e2g, {g for g, e in pairs if known is not None and e not in known}))
    got_g: Dict[str, Tuple[str, str]] = {}   # id -> (key, level)
    got_e: Dict[str, str] = {}               # key -> id
    for name, g2e, e2g, _ in by_level:
        for g in sorted(g2e):
            es = g2e[g]
            if g in got_g or len(es) != 1:
                continue
            e = next(iter(es))
            if e in got_e or len(e2g[e]) != 1:
                continue
            got_g[g], got_e[e] = (e, name), g
    return by_level, got_g, got_e


def xref_ids_for(levels: List[Tuple[str, List[Tuple[str, str]]]], known: Optional[set], keys) -> List[str]:
    """The ids (Ensembl gene ids) that join_on_xref's rule pairs with one of `keys` (the Entrez ids
    of a gene panel), sorted: what a gene-panel build fetches from Ensembl [im-9n4.59].  The same
    rule as the join, so every gene fetched joins a panel gene and every gene that would join one
    is fetched; never by label."""
    keys = set(keys)
    _, got_g, _ = xref_pairing(levels, known)
    return sorted(g for g, (e, _) in got_g.items() if e in keys)


def join_on_xref(store: ItemStore, levels: List[Tuple[str, List[Tuple[str, str]]]], known: Optional[set] = None,
                 cls: str = "Gene", id_field: str = "secondaryIdentifier", key: str = "primaryIdentifier",
                 unmatched: str = "drop") -> List[dict]:
    """Give this source's `cls` items (named by `id_field`, the Ensembl gene id) the `key` (the
    Entrez id) a stable cross-reference names, instead of letting InterMine merge them on symbol
    [im-9n4.55].  Gos Micklem, 20 Nov 2026: "Match on a stable cross-reference instead".

    `levels` is [(name, [(id, key), ...])] in precedence order: hgnc, ncbigene (their written
    items), then the source's own cross-reference.  The rule, deterministic (sorted, no first-seen):
      * a level pairs an id with a key only when, at that level, the id names one key and the key
        one id (one-to-many and many-to-one inside one source have no principled winner: neither
        side is paired by it), and neither is paired already by a higher level;
      * so where the sources disagree the higher one stands, the same order as
        Gene.secondaryIdentifier in curation/priorities_override.properties: the Entrez gene that
        will SHOW this Ensembl id is the one its Ensembl data joins, and no Gene ends up holding
        the data of one Ensembl gene and the id of another;
      * a key not among `known` (the Entrez ids of the genes in the build) is not a target;
      * an item no level pairs is `unmatched`: "drop" (default) leaves it, and the items that hang
        only off it, out of the build; "keep" loads it as a Gene of its own, `key` = its own id.
    Returns one report row per item, sorted by id: ensembl_id, symbol, status (joined, ambiguous,
    unmatched, kept), entrez, via, reason, disagree (what the lower levels said otherwise)."""
    items = sorted(((it.attrs[id_field], k) for k, it in store.items.items()
                    if it.cls == cls and it.attrs.get(id_field)), key=lambda t: t[0])
    by_level, got_g, got_e = xref_pairing(levels, known)
    rows, drop = [], []
    for g, k in items:
        it = store.items[k]
        row = {"ensembl_id": g, "symbol": it.attrs.get("symbol", ""), "status": "", "entrez": "",
               "via": "", "reason": "", "disagree": ""}
        said = [(name, sorted(g2e[g])) for name, g2e, _, _ in by_level if g in g2e]
        if g in got_g:
            e, via = got_g[g]
            it.attrs[key] = e
            row.update(status="joined", entrez=e, via=via)
            row["disagree"] = "; ".join(f"{n}: {','.join(es)}" for n, es in said if es != [e])
        else:
            multi = next(((n, es) for n, es in said if len(es) > 1), None)
            blocked = [(n, es[0]) for n, es in said if len(es) == 1]
            if multi:
                row.update(status="ambiguous", entrez=",".join(multi[1]), via=multi[0],
                           reason=f"{multi[0]} names {len(multi[1])} NCBI genes")
            elif blocked:
                n, e = blocked[0]
                others = sorted(by_level[[b[0] for b in by_level].index(n)][2][e])
                if e in got_e:
                    row.update(status="unmatched", entrez=e, via=n,
                               reason=f"NCBI gene {e} has {got_e[e]} (from {got_g[got_e[e]][1]})")
                else:
                    row.update(status="ambiguous", entrez=e, via=n,
                               reason=f"{n} names NCBI gene {e} for {len(others)} Ensembl genes: {','.join(others)}")
            else:
                missing = [n for n, _, _, out in by_level if g in out]
                absent = ",".join(sorted({e for n, pairs in levels if n in missing for gg, e in pairs if gg == g}))
                row.update(status="unmatched", entrez=absent,
                           reason=(f"{','.join(missing)} names NCBI gene {absent}, not in the build" if missing
                                   else "no cross-reference to an NCBI gene"))
            if unmatched == "keep":
                it.attrs[key] = g
                row["status"] = "kept"
            else:
                drop.append(k)
        rows.append(row)
    drop_items(store, drop)
    return rows


XREF_REPORT_COLUMNS = ["ensembl_id", "symbol", "status", "entrez", "via", "reason", "disagree"]


def _run_xref_join(store: ItemStore, out_dir: str, src: str, xcfg: dict, stats: dict) -> None:
    """sources.yaml `xref_join` (ensembl): the other sources' written items and this source's own
    raw cross-reference table, joined by join_on_xref; the report goes to items/<src>_xref_join.tsv."""
    cls, id_field, key = xcfg.get("class", "Gene"), xcfg.get("id_field", "secondaryIdentifier"), \
        xcfg.get("key", "primaryIdentifier")
    root = os.path.dirname(os.path.abspath(out_dir))
    levels, known = [], set()
    for other in xcfg.get("sources") or []:
        path = os.path.join(root, other, "items", f"{other}.xml")
        if not os.path.exists(path):
            stats["notes"].append(f"xref_join: no {other} items at {path} - write {other}'s items before {src}'s, "
                                  f"or none of its genes can join through {other}")
        pairs, k = xref_pairs_from_items(path, cls, key, id_field)
        levels.append((other, pairs))
        known |= k
    own = xcfg.get("own")
    if own:
        levels.append((src, xref_pairs_from_raw(os.path.join(out_dir, "raw", f"{own['table']}.tsv"),
                                                own["id"], own["xref"], own["prefix"])))
    rows = join_on_xref(store, levels, known, cls, id_field, key, xcfg.get("unmatched", "drop"))
    os.makedirs(os.path.join(out_dir, "items"), exist_ok=True)
    with open(os.path.join(out_dir, "items", f"{src}_xref_join.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\t".join(XREF_REPORT_COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]).replace("\t", " ") for c in XREF_REPORT_COLUMNS) + "\n")
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    by_via: Dict[str, int] = {}
    for r in rows:
        if r["status"] == "joined":
            by_via[r["via"]] = by_via.get(r["via"], 0) + 1
    stats["xref_join"] = {"counts": counts, "via": by_via}
    left = counts.get("unmatched", 0) + counts.get("ambiguous", 0)
    what = "loaded as Genes of their own (unmatched: keep)" if xcfg.get("unmatched") == "keep" else "left out of the build"
    stats["notes"].append(
        f"{cls}: {left} of {len(rows)} Ensembl genes not joined to an NCBI gene by cross-reference "
        f"({counts.get('unmatched', 0)} unmatched, {counts.get('ambiguous', 0)} ambiguous), {what}; joined "
        + ", ".join(f"{n} by {v}" for v, n in sorted(by_via.items()))
        + f" - items/{src}_xref_join.tsv")


def emit_items(model: InterMineModel, out_dir: str, src: str, source_cfg: dict, log=print) -> dict:
    cols = read_tsv(os.path.join(out_dir, "columns.tsv"))
    tables: Dict[str, List[dict]] = {}
    for c in cols:
        tables.setdefault(c["table"], []).append(c)
    store = ItemStore(model)
    stats = {"tables": 0, "rows": 0, "items": 0, "notes": []}
    classes_seen: List[str] = []
    for table, cl in tables.items():
        tsv = os.path.join(out_dir, "tsv", f"{table}.tsv")
        if not os.path.exists(tsv):
            continue
        cl = sorted(cl, key=lambda c: int(c["position"]))
        root_cls = table_root(cl)
        # object groups in column order: (class, via) -> [column dicts]
        groups: List[Tuple[Tuple[str, str], List[dict]]] = []
        for c in cl:
            key = group_key(model, root_cls, c["im_class"], c.get("via") or "")
            if c["im_class"] != root_cls and not key[1]:
                stats["notes"].append(f"{table}: no link from {root_cls} to {c['im_class']}; "
                                      f"{c['im_class']} items are created but unlinked")
            for g in groups:
                if g[0] == key:
                    g[1].append(c)
                    break
            else:
                groups.append((key, [c]))
        with open(tsv, encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh, delimiter="\t")
            header = next(rd, None)
            if header is None:
                continue
            stats["tables"] += 1
            for row in rd:
                stats["rows"] += 1
                if len(row) < len(header):
                    row = row + [""] * (len(header) - len(row))
                keys: Dict[Tuple[str, str], tuple] = {}
                for (cls, via), gcols in groups:
                    values = {c["im_field"]: row[int(c["position"])] for c in gcols if c["im_field"]}
                    real = [c for c in gcols if c.get("kind") != "const"]
                    if real and not any(row[int(c["position"])] for c in real):
                        continue          # its data columns are all empty: no object in this row
                    k = store.get(cls, values)
                    if k is not None:
                        keys[(cls, via)] = k
                        if cls not in classes_seen:
                            classes_seen.append(cls)
                for (cls, via), k in keys.items():
                    if not via:
                        continue
                    vcls, vf = via.split(".", 1)
                    # the linking object: the group with class vcls (root first)
                    src_key = keys.get((vcls, "")) or next((kk for (c2, v2), kk in keys.items() if c2 == vcls and (c2, v2) != (cls, via)), None)
                    if src_key is None or src_key == k:
                        continue
                    store.link(src_key, vf, k)
    # The cross-reference join first: key_ambiguity and defer_to below then see the Entrez ids it
    # gave, and not the genes it left out [im-9n4.55].
    if source_cfg.get("xref_join"):
        _run_xref_join(store, out_dir, src, source_cfg["xref_join"], stats)
    for cls, kcfgs in (source_cfg.get("key_ambiguity") or {}).items():
        for kcfg in (kcfgs if isinstance(kcfgs, list) else [kcfgs]):   # one field, or a list of them
            n = resolve_key_ambiguity(store, cls, kcfg["field"], kcfg.get("prefer_field"), kcfg.get("prefer_value"))
            if n:
                stats["notes"].append(f"{cls}.{kcfg['field']}: blanked on {n} items - ambiguous in this "
                                       f"source's own data, not an rdfc2im mapping error (STATUS.md D14)")
    for other, dcfg in (source_cfg.get("defer_to") or {}).items():
        other_items = os.path.join(os.path.dirname(os.path.abspath(out_dir)), other, "items", f"{other}.xml")
        for f, n in defer_to_source(store, other_items, dcfg.get("class", "Gene"), dcfg.get("key", "primaryIdentifier"),
                                    dcfg["fields"]).items():
            if n:
                stats["notes"].append(f"{dcfg.get('class', 'Gene')}.{f}: blanked on {n} items - {other} gives the "
                                      f"value to another {dcfg.get('key', 'primaryIdentifier')} (defer_to)")
    stats["organisms_completed"] = store.complete_organisms()
    stats["chromosomes_linked"] = store.organise_chromosomes()
    stats["sequences_completed"], seq_notes = store.complete_sequences()
    stats["notes"] += seq_notes
    if source_cfg.get("organism_from_genes"):
        stats["organisms_from_genes"] = store.organisms_from_genes(set(source_cfg["organism_from_genes"]))
    # DataSet / DataSource
    ds_title = source_cfg.get("data_set_title") or f"{src} (rdf-config)"
    ds_name = source_cfg.get("data_source_name") or src
    ds_url = source_cfg.get("data_source_url")
    if store.items:
        dsrc_values = {"name": ds_name}
        if ds_url:
            dsrc_values["url"] = ds_url
        dsrc = store.get("DataSource", dsrc_values)
        dset = store.get("DataSet", {"name": ds_title})
        if dset and source_cfg.get("data_set_licence"):
            # the licence the upstream states (sources.yaml, im-9n4.45); set after the get so the
            # DataSet's key stays its name
            store.items[dset].attrs.setdefault("licence", source_cfg["data_set_licence"])
        if dsrc and dset:
            store.link(dset, "dataSource", dsrc)
        for k, it in list(store.items.items()):
            if it.cls in ("DataSet", "DataSource"):
                continue
            if "dataSets" in model.all_fields(it.cls) and dset:
                it.colls.setdefault("dataSets", []).append(dset)
            elif "dataSet" in model.all_fields(it.cls) and dset:
                it.refs["dataSet"] = dset
    path = os.path.join(out_dir, "items", f"{src}.xml")
    if store.items:
        stats["items"] = store.write(path)
    stats["classes"] = classes_seen
    stats["conflicts"] = store.conflicts
    stats["dropped"] = store.dropped
    log(f"  {src}: {stats['tables']} tables, {stats['rows']} rows -> {stats['items']} items ({', '.join(classes_seen)})"
        + (f"; {len(store.conflicts)} attribute conflicts" if store.conflicts else "")
        + (f"; {len(store.dropped)} attributes dropped (wrong type)" if store.dropped else ""))
    # These used to be collected and never shown, which is how every UniProt table stayed
    # mis-rooted: the warnings existed, nobody could see them.
    for note in dict.fromkeys(stats["notes"]):
        log(f"    WARNING {note}")
    return stats
