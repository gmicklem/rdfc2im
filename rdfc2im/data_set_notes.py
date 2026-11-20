"""The notes shown with a data set [im-9n4.59].

Gos Micklem, 20 Nov 2026: the data-source listing should say that Ensembl genes are loaded only where
an NCBI gene corresponds ("maybe a new column Notes").  No model change: the sentences are written
into DataSet.description after the status-page sentence (tools/source_pages.py data-set-links) and
shown as the Notes row of the source's status page (tools/source_pages.py pages, from the manifest).

A source's notes, in this order:
  * `data_set_note`: plain sentence(s) from its record (sources.yaml for an RDF source, its stock
    mapping file for a stock one);
  * `data_set_note_counts`: one more sentence with {not_joined} and {total} filled from this
    build's cross-reference join report (out/<source>/items/<source>_xref_join.tsv), left out when
    the build wrote none (the numbers are the build's, never the file's);
  * the gene-panel cut, when the build had a gene panel and applied it to this source: an RDF
    source whose cached extract was fetched for the panel (its cache group's meta scope=panel), a
    stock source with a file cut by panel ids (stock_sources.yaml `filter.ids`).
Deterministic: the same records, report and panel give the same sentences."""
from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

# what the stock filter's id set cuts a file to, in words; an id kind not here (chromosomes) is no panel cut
_GENE_CUT = ("This build loads only the records of this data set that involve one of the {n} genes of its gene "
             "panel or their proteins; the rest of the file is cut before loading.")
_PARTNER_CUT = ("This build loads only the records of the genes that share a PANTHER orthology row with one of the "
                "{n} genes of its gene panel.")
_IPR_CUT = ("This build loads only the InterPro entries that the proteins of the {n} genes of its gene panel match, "
            "and the entries related to them.")
STOCK_PANEL_CUTS = {"entrez": _GENE_CUT, "ensembl": _GENE_CUT, "uniprot": _GENE_CUT, "hpo-diseases": _GENE_CUT,
                    "mgi": _PARTNER_CUT, "rgd": _PARTNER_CUT, "ipr": _IPR_CUT}
_ORDER = ("entrez", "ensembl", "uniprot", "hpo-diseases", "mgi", "rgd", "ipr")
RDF_PANEL_CUT = "This build loads this data set only for the {n} genes of its gene panel."


def xref_join_counts(path: str) -> Optional[Dict[str, int]]:
    """{total, not_joined} of a cross-reference join report (items.XREF_REPORT_COLUMNS): one row per
    Ensembl gene in scope; not joined = unmatched or ambiguous (a `kept` gene is loaded).  None when
    the file does not exist."""
    if not os.path.exists(path):
        return None
    total = not_joined = 0
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            total += 1
            if row.get("status") in ("unmatched", "ambiguous"):
                not_joined += 1
    return {"total": total, "not_joined": not_joined}


def _own(rec: dict, counts: Optional[dict]) -> List[str]:
    out = []
    if (rec.get("data_set_note") or "").strip():
        out.append(" ".join(rec["data_set_note"].split()))
    if counts is not None and (rec.get("data_set_note_counts") or "").strip():
        out.append(" ".join(rec["data_set_note_counts"].format(**counts).split()))
    return out


def rdf_notes(name: str, rec: dict, out_root: Optional[str] = None, cache_meta: Optional[dict] = None,
              panel_genes: Optional[int] = None) -> List[str]:
    """The notes of RDF source `name` (its sources.yaml record `rec`)."""
    counts = None
    if out_root and rec.get("data_set_note_counts"):
        counts = xref_join_counts(os.path.join(out_root, name, "items", f"{name}_xref_join.tsv"))
    out = _own(rec, counts)
    if panel_genes and (cache_meta or {}).get("scope") == "panel":
        out.append(RDF_PANEL_CUT.format(n=panel_genes))
    return out


def stock_notes(mp: dict, entry: Optional[dict] = None, panel_genes: Optional[int] = None) -> List[str]:
    """The notes of a stock source: its mapping file's (`mp`) note, then, when the build has a panel,
    the cut its stock table entry's (`entry`) file filters make."""
    out = _own(mp or {}, None)
    if panel_genes and entry:
        kinds = {(f.get("filter") or {}).get("ids") for f in entry.get("files") or []
                 if isinstance(f.get("filter"), dict)}
        kind = next((k for k in _ORDER if k in kinds), None)
        if kind:
            out.append(STOCK_PANEL_CUTS[kind].format(n=panel_genes))
    return out


def panel_size(genes_file: Optional[str]) -> Optional[int]:
    """The number of distinct symbols in a gene panel file (whitespace separated, # comments), or None."""
    if not genes_file:
        return None
    syms = set()
    with open(genes_file, encoding="utf-8") as fh:
        for line in fh:
            syms.update(line.split("#", 1)[0].split())
    return len(syms) or None
