"""subset_raw.py: pre-filtering raw upstream files to the demo gene panel.

Each format has a small hand-made input under tests/fixtures/subset_raw/ and a committed expected
output compared byte for byte. The fixtures are built to catch the usual mistakes: a GFF3 child
that comes before its parent (and a gene outside the set), a UniProt entry matched on its second
accession, an isoform FASTA header, a tab row matched only in the second column, gene_info with two
taxa. tests/fixtures/subset_raw/real/ holds the same kind of check on a few records cut from real
upstream files (see its README).
"""
import gzip
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import subset_raw  # noqa: E402

FX = os.path.join(HERE, "fixtures", "subset_raw")
TOOL = os.path.join(os.path.dirname(HERE), "tools", "subset_raw.py")


def fx(name):
    return os.path.join(FX, name)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def run_cli(*args):
    return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True)


def filt(tmp_path, fmt, infile, ids=None, out="out.dat", *extra):
    out = str(tmp_path / out)
    args = ["filter", "--format", fmt, "--in", infile, "--out", out]
    if ids:
        args += ["--ids", ids]
    p = run_cli(*args, *extra)
    assert p.returncode == 0, p.stderr
    return out, json.loads(p.stdout)


# ------------------------------------------------------------------ GAF

def test_gaf_matches_expected(tmp_path):
    out, res = filt(tmp_path, "gaf", fx("gaf_in.gaf"), fx("gaf_ids.txt"))
    assert read(out) == read(fx("gaf_expected.gaf"))
    assert res == {"format": "gaf", "records_in": 5, "records_out": 3, "ids_given": 3, "ids_matched": 2}


def test_gaf_isoform_object_id_matches_base_accession(tmp_path):
    src = tmp_path / "in.gaf"
    src.write_text("!gaf-version: 2.2\nUniProtKB\tP10635-2\tX\t\tGO:1\n")
    ids = tmp_path / "ids.txt"
    ids.write_text("P10635\n")
    out, res = filt(tmp_path, "gaf", str(src), str(ids))
    assert res["records_out"] == 1


# ------------------------------------------------------------------ GFF3

def test_gff3_parent_closure_with_child_before_parent(tmp_path):
    out, res = filt(tmp_path, "gff3", fx("gff3_in.gff3"), fx("gff3_ids.txt"))
    assert read(out) == read(fx("gff3_expected.gff3"))
    assert res == {"format": "gff3", "records_in": 12, "records_out": 8, "ids_given": 3, "ids_matched": 2}


def test_gff3_keeps_every_sequence_region_and_drops_outside_gene(tmp_path):
    out, _ = filt(tmp_path, "gff3", fx("gff3_in.gff3"), fx("gff3_ids.txt"))
    text = read(out).decode()
    assert text.count("##sequence-region") == 2
    assert "geneB" not in text and "rnaB" not in text and "exonB1" not in text
    assert "ID=exonA1" in text and "product=no%20id" in text      # child and ID-less grandchild
    assert "##FASTA" not in text


def test_gff3_shared_exon_kept_once_for_two_parents(tmp_path):
    out, _ = filt(tmp_path, "gff3", fx("gff3_in.gff3"), fx("gff3_ids.txt"))
    assert read(out).decode().count("ID=exonC1;") == 1


# ------------------------------------------------------------------ UniProt XML

def test_uniprot_xml_matches_expected_on_second_accession(tmp_path):
    out, res = filt(tmp_path, "uniprot-xml", fx("uniprot_in.xml"), fx("uniprot_ids.txt"))
    assert read(out) == read(fx("uniprot_expected.xml"))
    # Q9UDA1 is the second <accession> of the first entry; P99999 is in the ids but in no entry
    assert res == {"format": "uniprot-xml", "records_in": 4, "records_out": 2, "ids_given": 3, "ids_matched": 2}


def test_uniprot_xml_output_is_well_formed_and_keeps_root_and_copyright(tmp_path):
    out, _ = filt(tmp_path, "uniprot-xml", fx("uniprot_in.xml"), fx("uniprot_ids.txt"))
    root = ET.parse(out).getroot()
    ns = "{http://uniprot.org/uniprot}"
    assert root.tag == ns + "uniprot"
    assert root.attrib["{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"].startswith("http://uniprot.org/uniprot ")
    assert len(root.findall(ns + "entry")) == 2
    assert root.find(ns + "copyright") is not None
    assert "&amp;" in read(out).decode()          # entities are copied, not re-encoded


def test_uniprot_xml_no_match_still_well_formed(tmp_path):
    ids = tmp_path / "ids.txt"
    ids.write_text("Z00000\n")
    out, res = filt(tmp_path, "uniprot-xml", fx("uniprot_in.xml"), str(ids))
    assert res["records_out"] == 0
    assert read(out) == read(fx("uniprot_none_expected.xml"))
    ET.parse(out)


def test_uniprot_xml_entries_split_across_read_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(subset_raw, "_CHUNK", 37)
    out = str(tmp_path / "o.xml")
    subset_raw.filter_uniprot_xml(fx("uniprot_in.xml"), out, {"Q9UDA1", "P04637"})
    assert read(out) == read(fx("uniprot_expected.xml"))


# ------------------------------------------------------------------ FASTA

def test_fasta_matches_expected_with_isoform_and_plain_header(tmp_path):
    out, res = filt(tmp_path, "fasta", fx("fasta_in.fasta"), fx("fasta_ids.txt"))
    assert read(out) == read(fx("fasta_expected.fasta"))
    assert res == {"format": "fasta", "records_in": 5, "records_out": 3, "ids_given": 2, "ids_matched": 2}


def test_fasta_isoform_id_matches_only_that_isoform(tmp_path):
    out, _ = filt(tmp_path, "fasta", fx("fasta_in.fasta"), fx("fasta_isoform_ids.txt"))
    assert read(out) == read(fx("fasta_isoform_expected.fasta"))


def test_fasta_accession_parsing():
    assert subset_raw.fasta_accession("sp|P10635-2|CP2D6_HUMAN Isoform 2") == "P10635-2"
    assert subset_raw.fasta_accession("P04637 plain") == "P04637"
    assert subset_raw.fasta_accession("tr|A0A024R8Z4|A0A024R8Z4_HUMAN x") == "A0A024R8Z4"


# ------------------------------------------------------------------ tab

def test_tab_any_of_two_columns(tmp_path):
    out, res = filt(tmp_path, "tab", fx("tab_in.tsv"), fx("tab_ids.txt"), "o.tsv", "--column", "1,2")
    assert read(out) == read(fx("tab_expected_cols12.tsv"))
    assert res == {"format": "tab", "records_in": 6, "records_out": 3, "ids_given": 2, "ids_matched": 2}


def test_tab_single_column_misses_second_column_hit(tmp_path):
    out, _ = filt(tmp_path, "tab", fx("tab_in.tsv"), fx("tab_ids.txt"), "o.tsv", "--column", "1")
    assert read(out) == read(fx("tab_expected_col1.tsv"))


def test_tab_keep_comments_keeps_first_line(tmp_path):
    out, res = filt(tmp_path, "tab", fx("tab_in.tsv"), fx("tab_ids.txt"), "o.tsv", "--column", "1,2", "--keep-comments")
    assert read(out) == read(fx("tab_expected_cols12_header.tsv"))
    assert res["records_in"] == 5          # the header line is not a record


def test_tab_cell_forms():
    ids = {"P10635", "1017"}
    assert subset_raw._cell_hit("uniprotkb:P10635", ids) == "P10635"
    assert subset_raw._cell_hit("uniprotkb:P10635-2|uniprotkb:Q1", ids) == "P10635"
    assert subset_raw._cell_hit("entrez gene/locuslink:1017", ids) == "1017"
    assert subset_raw._cell_hit("10170", ids) is None


# ------------------------------------------------------------------ gene_info

def test_gene_info_taxon_only_is_all_human_genes(tmp_path):
    out, res = filt(tmp_path, "gene_info", fx("gene_info_in.tsv"), None, "o.tsv", "--taxon", "9606")
    assert read(out) == read(fx("gene_info_human_expected.tsv"))
    assert res == {"format": "gene_info", "records_in": 5, "records_out": 3, "ids_given": 0, "ids_matched": 0}


def test_gene_info_taxon_and_ids(tmp_path):
    out, res = filt(tmp_path, "gene_info", fx("gene_info_in.tsv"), fx("gene_info_ids.txt"), "o.tsv", "--taxon", "9606")
    assert read(out) == read(fx("gene_info_human_ids_expected.tsv"))
    assert res["ids_matched"] == 2


def test_gene_info_ids_without_taxon(tmp_path):
    out, _ = filt(tmp_path, "gene_info", fx("gene_info_in.tsv"), fx("gene_info_ids.txt"), "o.tsv")
    assert read(out) == read(fx("gene_info_ids_only_expected.tsv"))


# ------------------------------------------------------------------ gzip

def test_gzip_input_and_output_by_suffix(tmp_path):
    gz_in = tmp_path / "in.gaf.gz"
    with gzip.open(gz_in, "wb") as fh:
        fh.write(read(fx("gaf_in.gaf")))
    out, res = filt(tmp_path, "gaf", str(gz_in), fx("gaf_ids.txt"), "out.gaf.gz")
    assert read(out)[:2] == b"\x1f\x8b"
    with gzip.open(out, "rb") as fh:
        assert fh.read() == read(fx("gaf_expected.gaf"))
    assert res["records_out"] == 3
    assert not [p for p in os.listdir(tmp_path) if ".part" in p]


def test_gzip_output_is_deterministic(tmp_path):
    a, _ = filt(tmp_path, "gaf", fx("gaf_in.gaf"), fx("gaf_ids.txt"), "a.gz")
    b, _ = filt(tmp_path, "gaf", fx("gaf_in.gaf"), fx("gaf_ids.txt"), "b.gz")
    assert read(a) == read(b)


def test_gzip_uniprot_xml_round_trip(tmp_path):
    gz_in = tmp_path / "in.xml.gz"
    with gzip.open(gz_in, "wb") as fh:
        fh.write(read(fx("uniprot_in.xml")))
    out, _ = filt(tmp_path, "uniprot-xml", str(gz_in), fx("uniprot_ids.txt"), "out.xml.gz")
    with gzip.open(out, "rb") as fh:
        assert fh.read() == read(fx("uniprot_expected.xml"))


# ------------------------------------------------------------------ CLI errors

def test_missing_input_exits_nonzero(tmp_path):
    p = run_cli("filter", "--format", "gaf", "--in", str(tmp_path / "nope.gaf"), "--out", str(tmp_path / "o"),
                "--ids", fx("gaf_ids.txt"))
    assert p.returncode != 0 and "not found" in p.stderr and p.stdout == ""


def test_unknown_format_exits_nonzero(tmp_path):
    p = run_cli("filter", "--format", "bam", "--in", fx("gaf_in.gaf"), "--out", str(tmp_path / "o"))
    assert p.returncode != 0 and "unknown format" in p.stderr


@pytest.mark.parametrize("fmt", ["gaf", "gff3", "uniprot-xml", "fasta", "tab", "psi-xml"])
def test_format_needing_ids_without_ids_exits_nonzero(tmp_path, fmt):
    p = run_cli("filter", "--format", fmt, "--in", fx("gaf_in.gaf"), "--out", str(tmp_path / "o"), "--column", "1")
    assert p.returncode != 0 and "--ids" in p.stderr
    assert not (tmp_path / "o").exists()


def test_tab_without_column_exits_nonzero(tmp_path):
    p = run_cli("filter", "--format", "tab", "--in", fx("tab_in.tsv"), "--out", str(tmp_path / "o"),
                "--ids", fx("tab_ids.txt"))
    assert p.returncode != 0 and "--column" in p.stderr


def test_stdout_is_exactly_one_json_line(tmp_path):
    p = run_cli("filter", "--format", "gaf", "--in", fx("gaf_in.gaf"), "--out", str(tmp_path / "o"),
                "--ids", fx("gaf_ids.txt"))
    assert p.stdout.count("\n") == 1 and set(json.loads(p.stdout)) == {
        "format", "records_in", "records_out", "ids_given", "ids_matched"}


# ------------------------------------------------------------------ idsets

def test_idsets_from_items_fixture(tmp_path):
    out = tmp_path / "ids"
    p = run_cli("idsets", "--genes", fx("panel.txt"), "--out", str(out), "--items-root", fx("items"),
                "--lookup-dir", str(tmp_path / "no-cache"))
    assert p.returncode == 0, p.stderr
    lines = lambda n: (out / n).read_text().split()
    assert lines("symbol.txt") == ["CDK2", "TP53"]
    assert lines("entrez.txt") == ["1017", "7157"]           # NOTPANEL (9999) is not in the panel
    assert lines("ensembl.txt") == ["ENSG00000123374", "ENSG00000141510"]
    # P04637's Protein item comes before... its gene (TP53) in the file; Q00000 belongs to NOTPANEL
    assert lines("uniprot.txt") == ["P04637", "P24941"]
    meta = json.loads((out / "idsets.json").read_text())
    import hashlib
    assert meta["genes_md5"] == hashlib.md5(read(fx("panel.txt"))).hexdigest()
    assert meta["counts"] == {"entrez": 2, "ensembl": 2, "uniprot": 2, "symbol": 2}
    assert len(meta["inputs"]) == 4
    assert not (out / "uniprot_reviewed.txt").exists()
    # not a panel set: the RefSeq accessions that cut the genome FASTA (ids: chromosomes) [im-9n4.9]
    assert lines("chromosomes.txt") == list(subset_raw.REFSEQ_GRCH38_CHROMOSOMES)


def test_idsets_merges_lookup_cache(tmp_path):
    import hashlib
    syms = subset_raw.read_panel(fx("panel.txt"))
    key = hashlib.md5("\n".join(sorted(syms)).encode()).hexdigest()
    cache = tmp_path / "cache" / "data"
    cache.mkdir(parents=True)
    (cache / f"resolve_ncbigene_symbols-9606-{key}.txt").write_text("1017\n5555\n")
    sets, info = subset_raw.derive_idsets(fx("panel.txt"), fx("items"), str(tmp_path / "cache"))
    assert sets["entrez"] == {"1017", "5555", "7157"}
    assert any("resolve_ncbigene" in p for p in info["inputs"])


def _all_genes_items(tmp_path):
    """The idsets fixture as a `--gene-identifiers all` build sees it: ncbigene and hgnc fetched for
    every human gene, so their items hold non-panel genes too, with Ensembl ids, HGNC protein
    links, a symbol-less gene and a publication; ensembl and uniprot stay panel-scoped."""
    import shutil
    root = tmp_path / "items"
    shutil.copytree(fx("items"), root)
    (root / "ncbigene" / "items" / "ncbigene.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<items>\n'
        + "".join(f'  <item id="0_{i}" class="Gene" implements=""><attribute name="primaryIdentifier" value="{e}"/>'
                  + (f'<attribute name="symbol" value="{s}"/>' if s else "")
                  + f'<attribute name="secondaryIdentifier" value="{g}"/></item>\n'
                  for i, (e, s, g) in enumerate([("1017", "CDK2", "ENSG00000123374"), ("7157", "TP53", "ENSG00000141510"),
                                                 ("9999", "NOTPANEL", "ENSG00000000009"), ("1018", "CDK3", "ENSG00000250506"),
                                                 ("124905847", "", "ENSG00000000010")], 1))
        + '  <item id="0_9" class="Organism" implements=""><attribute name="taxonId" value="9606"/></item>\n</items>\n')
    (root / "hgnc" / "items" / "hgnc.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<items>\n'
        '  <item id="0_1" class="Gene" implements=""><attribute name="primaryIdentifier" value="1017"/><attribute name="symbol" value="CDK2"/>'
        '<attribute name="secondaryIdentifier" value="ENSG00000123374"/><collection name="proteins"><reference ref_id="0_3"/></collection>'
        '<collection name="publications"><reference ref_id="0_5"/></collection></item>\n'
        '  <item id="0_2" class="Gene" implements=""><attribute name="primaryIdentifier" value="1018"/><attribute name="symbol" value="CDK3"/>'
        '<attribute name="secondaryIdentifier" value="ENSG00000250506"/><collection name="proteins"><reference ref_id="0_4"/></collection>'
        '<collection name="publications"><reference ref_id="0_6"/></collection></item>\n'
        '  <item id="0_3" class="Protein" implements=""><attribute name="primaryAccession" value="P24941"/><collection name="genes"><reference ref_id="0_1"/></collection></item>\n'
        '  <item id="0_4" class="Protein" implements=""><attribute name="primaryAccession" value="Q00526"/><collection name="genes"><reference ref_id="0_2"/></collection></item>\n'
        '  <item id="0_5" class="Publication" implements=""><attribute name="pubMedId" value="1639063"/></item>\n'
        '  <item id="0_6" class="Publication" implements=""><attribute name="pubMedId" value="8195233"/></item>\n'
        '</items>\n')
    return root


def test_idsets_stay_the_panel_when_ncbigene_and_hgnc_hold_every_gene(tmp_path):
    """im-9n4.40, the main trap of --gene-identifiers all: the stock raw files are cut to the id
    sets derived from out/<source>/items.  With ncbigene and hgnc fetched for all human genes those
    items hold some 64,000 genes, and the id sets must still be the panel's, or every stock filter
    (UniProt XML, GAF, GFF, PSI-MI, expression files) stops filtering."""
    panel, _ = subset_raw.derive_idsets(fx("panel.txt"), fx("items"), str(tmp_path / "no-cache"))
    full, _ = subset_raw.derive_idsets(fx("panel.txt"), str(_all_genes_items(tmp_path)), str(tmp_path / "no-cache"))
    assert full == panel
    assert full["entrez"] == {"1017", "7157"} and "Q00526" not in full["uniprot"]


def test_panel_items_keeps_the_panel_genes_and_what_they_reach(tmp_path):
    """panel_items cuts an every-gene items file back to what a panel fetch would have held, so the
    pubmed source's cited-PMID scope (a grep of the hgnc items) stays the panel's [im-9n4.40]."""
    root = _all_genes_items(tmp_path)
    out = tmp_path / "hgnc-panel.xml"
    res = subset_raw.panel_items(str(root / "hgnc" / "items" / "hgnc.xml"), str(out), entrez={"1017", "7157"})
    assert res == {"items_in": 6, "genes_in": 2, "panel_genes": 1, "items_out": 3}
    text = out.read_text()
    assert "1639063" in text and "P24941" in text
    assert "8195233" not in text and "Q00526" not in text and "1018" not in text
    ET.parse(str(out))   # well-formed
    # by symbol when no Entrez ids are given
    res2 = subset_raw.panel_items(str(root / "hgnc" / "items" / "hgnc.xml"), str(out), symbols={"CDK3"})
    assert res2["panel_genes"] == 1 and "8195233" in out.read_text()


def test_idsets_without_any_input_fails(tmp_path):
    p = run_cli("idsets", "--genes", fx("panel.txt"), "--out", str(tmp_path / "o"),
                "--items-root", str(tmp_path / "empty"), "--lookup-dir", str(tmp_path / "none"))
    assert p.returncode != 0 and "no inputs" in p.stderr


def test_idsets_missing_genes_file(tmp_path):
    p = run_cli("idsets", "--genes", str(tmp_path / "nope.txt"), "--out", str(tmp_path / "o"))
    assert p.returncode != 0 and "not found" in p.stderr


# ------------------------------------------------------------------ real upstream samples

REAL = os.path.join(FX, "real")


def test_real_goa_sample(tmp_path):
    out, res = filt(tmp_path, "gaf", os.path.join(REAL, "goa_human_sample.gaf"), os.path.join(REAL, "goa_ids.txt"))
    assert read(out) == read(os.path.join(REAL, "goa_expected.gaf"))
    assert res["records_out"] == 8


SIBLINGS = """##gff-version 3
##sequence-region NC_000011.10 1 135086622
##sequence-region NC_012920.1 1 16569
##sequence-region NT_187633.1 1 300000
NC_000011.10\tR\tgene\t100\t900\t.\t+\t.\tID=gene-P;Dbxref=GeneID:5080;Name=PAX6
NC_000011.10\tR\tmRNA\t100\t900\t.\t+\t.\tID=rna-1;Parent=gene-P;Dbxref=GeneID:5080
NC_000011.10\tR\texon\t100\t200\t.\t+\t.\tID=exon-1-1;Parent=rna-1;Dbxref=GeneID:5080
NC_000011.10\tR\tgene\t1000\t2000\t.\t-\t.\tID=gene-N;Dbxref=GeneID:999;Name=NEIGH
NC_000011.10\tR\tmRNA\t1000\t2000\t.\t-\t.\tID=rna-N;Parent=gene-N;Dbxref=GeneID:999
NC_000011.10\tR\texon\t1000\t1100\t.\t-\t.\tID=exon-N-1;Parent=rna-N;Dbxref=GeneID:999
NC_000011.10\tR\tenhancer\t3000\t3100\t.\t.\t.\tID=id-E;Dbxref=GeneID:888
NC_000011.10\tR\tmRNA\t5000\t6000\t.\t+\t.\tID=rna-S;Parent=gene-T
NC_000011.10\tR\tgene\t5000\t6000\t.\t+\t.\tID=gene-T;Dbxref=GeneID:777;Name=TOP
NC_000011.10\tR\texon\t5000\t5100\t.\t+\t.\tID=exon-S-1;Parent=rna-S
"""


def test_gff3_keep_types_keeps_neighbour_gene_rows_only(tmp_path):
    """[im-9n4.9] --keep-types gene keeps the other genes' own rows (a genome browser's neighbours)
    but none of their transcripts or exons, nor other feature types."""
    src = tmp_path / "in.gff3"
    src.write_text(SIBLINGS)
    ids = tmp_path / "ids.txt"
    ids.write_text("5080\n")
    out, res = filt(tmp_path, "gff3", str(src), str(ids), "out.gff3", "--keep-types", "gene")
    kept = [l.split("\t")[8].split(";")[0] for l in open(out) if not l.startswith("#")]
    assert kept == ["ID=gene-P", "ID=rna-1", "ID=exon-1-1", "ID=gene-N", "ID=gene-T"]
    assert res["records_out"] == 5 and res["ids_matched"] == 1
    out2, res2 = filt(tmp_path, "gff3", str(src), str(ids), "out2.gff3")
    assert res2["records_out"] == 3


def test_gff3_sibling_of_a_seed_is_not_kept_without_its_children(tmp_path):
    """A seed mRNA's gene is kept as its ancestor; the gene's other mRNA (an ID of its own, not in
    the closure) used to be kept through the 'child without an ID' rule while its exons were not."""
    src = tmp_path / "in.gff3"
    src.write_text("##gff-version 3\n"
                   "c\tR\tgene\t1\t900\t.\t+\t.\tID=g\n"
                   "c\tR\tmRNA\t1\t900\t.\t+\t.\tID=r1;Parent=g;Dbxref=GeneID:1\n"
                   "c\tR\texon\t1\t90\t.\t+\t.\tID=e1;Parent=r1\n"
                   "c\tR\tmRNA\t1\t800\t.\t+\t.\tID=r2;Parent=g\n"
                   "c\tR\texon\t1\t80\t.\t+\t.\tID=e2;Parent=r2\n"
                   "c\tR\tCDS\t1\t80\t.\t+\t0\tParent=r1\n")
    ids = tmp_path / "ids.txt"
    ids.write_text("1\n")
    out, _ = filt(tmp_path, "gff3", str(src), str(ids), "out.gff3")
    kept = [l.split("\t")[2] + ":" + l.split("\t")[8].strip() for l in open(out) if not l.startswith("#")]
    assert kept == ["gene:ID=g", "mRNA:ID=r1;Parent=g;Dbxref=GeneID:1", "exon:ID=e1;Parent=r1", "CDS:Parent=r1"]


def test_keep_types_is_for_gff3_only(tmp_path):
    p = run_cli("filter", "--format", "gaf", "--in", fx("gaf_in.gaf"), "--out", str(tmp_path / "o"),
                "--ids", fx("gaf_ids.txt"), "--keep-types", "gene")
    assert p.returncode == 2 and "--keep-types is for format gff3 only" in p.stderr


def test_chromosome_lengths_from_sequence_region_lines(tmp_path):
    """[im-9n4.9] Items XML for the humanmine-items loader: the mapped chromosomes only (MT and
    scaffolds are not mapped by the ncbi-gff loader), length = end - start + 1."""
    src = tmp_path / "in.gff3"
    src.write_text(SIBLINGS)
    out = tmp_path / "lengths.xml"
    p = run_cli("chromosome-lengths", "--in", str(src), "--out", str(out))
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout)
    assert res["records_in"] == 3 and res["chromosomes"] == {"11": 135086622}
    root = ET.parse(out).getroot()
    items = {i.get("id"): i for i in root.iter("item")}
    assert [i.get("class") for i in root.iter("item")] == ["Organism", "DataSource", "DataSet", "Chromosome"]
    chrom = items["0_4"]
    attrs = {a.get("name"): a.get("value") for a in chrom.iter("attribute")}
    assert attrs == {"primaryIdentifier": "11", "length": "135086622"}
    assert chrom.find("reference").get("ref_id") == "0_1"
    assert {a.get("value") for a in items["0_1"].iter("attribute")} == {"9606"}
    assert {a.get("value") for a in items["0_3"].iter("attribute")} == {"ncbi-gff"}
    # every ref_id points at an item
    assert all(r.get("ref_id") in items for r in root.iter("reference"))


def test_chromosome_lengths_map_is_the_loaders_and_refuses_bad_input(tmp_path):
    m = subset_raw.REFSEQ_GRCH38_CHROMOSOMES
    assert len(m) == 24 and m["NC_000023.11"] == "X" and m["NC_000024.10"] == "Y"
    assert "NC_012920.1" not in m
    src = tmp_path / "in.gff3"
    src.write_text("##sequence-region NC_000001.11 1 10\n##sequence-region NC_000001.11 1 20\n")
    p = run_cli("chromosome-lengths", "--in", str(src), "--out", str(tmp_path / "o.xml"))
    assert p.returncode == 2 and "two sequence-region lengths" in p.stderr
    src.write_text("##sequence-region NW_1 1 10\n")
    p = run_cli("chromosome-lengths", "--in", str(src), "--out", str(tmp_path / "o.xml"))
    assert p.returncode == 2 and "no ##sequence-region line names a known chromosome" in p.stderr
    assert not (tmp_path / "o.xml").exists()


def test_real_refseq_gff3_sample(tmp_path):
    out, res = filt(tmp_path, "gff3", os.path.join(REAL, "refseq_grch38_sample.gff3"), os.path.join(REAL, "gff3_ids.txt"))
    assert read(out) == read(os.path.join(REAL, "refseq_expected.gff3"))
    assert res["ids_matched"] == 2


# ---- PANTHER rows [im-9n4.11]

PANTHER = ("HUMAN|HGNC=8620|UniProtKB=P26367\tMOUSE|MGI=MGI=97490|UniProtKB=P63015\tLDO\tEuarchontoglires\tPTHR45636\n"
           "HUMAN|HGNC=8620|UniProtKB=P26367\tRAT|RGD=3258|UniProtKB=P63016\tLDO\tEuarchontoglires\tPTHR45636\n"
           "HUMAN|HGNC=8620|UniProtKB=P26367\tDANRE|ZFIN=ZDB-GENE-041210-244|UniProtKB=G2ZGB0\tO\tEuteleostomi\tPTHR45636\n"
           "MOUSE|MGI=MGI=1|UniProtKB=Q1\tRAT|RGD=2|UniProtKB=Q2\tLDO\tMuridae\tPTHR0\n"
           "HUMAN|HGNC=1|UniProtKB=P00001\tMOUSE|MGI=MGI=5|UniProtKB=Q5\tLDO\tEuarchontoglires\tPTHR1\n")


def test_panther_cells_match_on_their_db_equals_id_tokens():
    ids = {"P26367"}
    assert subset_raw._cell_hit("HUMAN|HGNC=8620|UniProtKB=P26367", ids) == "P26367"
    assert subset_raw._cell_hit("MOUSE|MGI=MGI=97490|UniProtKB=P63015", ids) is None
    assert subset_raw._cell_hit("HUMAN|HGNC=8620|UniProtKB=P26367-2", ids) == "P26367"


def test_tab_filter_keeps_panther_rows_with_a_panel_gene_in_either_cell(tmp_path):
    src, dst = tmp_path / "RefGenomeOrthologs", tmp_path / "out"
    src.write_text(PANTHER)
    res = subset_raw.filter_tab(str(src), str(dst), {"P26367", "Q2"}, [0, 1])
    lines = dst.read_text().splitlines()
    assert res["records_in"] == 5 and res["records_out"] == 4 and len(lines) == 4, lines   # the Q2 row too
    assert not any("P00001" in l for l in lines)


def test_partner_ids_are_the_mgi_and_rgd_ids_of_rows_with_a_panel_gene(tmp_path, capsys):
    src, ids, out = tmp_path / "RefGenomeOrthologs", tmp_path / "uniprot.txt", tmp_path / "idsets"
    src.write_text(PANTHER)
    ids.write_text("P26367\n")
    assert subset_raw.main(["partner-ids", "--in", str(src), "--ids", str(ids), "--out", str(out)]) == 0
    assert (out / "mgi.txt").read_text() == "MGI:97490\n"          # col 1 of MRK_List2.rpt
    assert (out / "rgd.txt").read_text() == "3258\n"               # the bare number of GENES_RAT.txt
    assert '"mgi": 1' in capsys.readouterr().out


# ------------------------------------------------------------------ PSI-MI 2.5 XML (IntAct, BioGRID) [im-9n4.13]

def _psi_interactor(iid, xrefs, label):
    refs = "".join(f'<{"primaryRef" if i == 0 else "secondaryRef"} db="{db}" id="{ident}"/>'
                   for i, (db, ident) in enumerate(xrefs))
    return (f'      <interactor id="{iid}">\n        <names><shortLabel>{label}</shortLabel></names>\n'
            f'        <xref>{refs}</xref>\n        <organism ncbiTaxId="9606"/>\n      </interactor>\n')


def _psi_interaction(iid, exp, refs, label):
    parts = "".join(f'<participant id="p{iid}{r}"><interactorRef>{r}</interactorRef></participant>' for r in refs)
    return (f'      <interaction id="{iid}">\n        <names><shortLabel>{label}</shortLabel></names>\n'
            f'        <experimentList><experimentRef>{exp}</experimentRef></experimentList>\n'
            f'        <participantList>{parts}</participantList>\n      </interaction>\n')


def _psi_entry(exps, interactors, interactions):
    return ('  <entry>\n    <source releaseDate="2026-10-24"><names><shortLabel>test</shortLabel></names></source>\n'
            '    <experimentList>\n'
            + "".join(f'      <experimentDescription id="{e}"><names><shortLabel>exp-{e}</shortLabel></names>'
                      f'</experimentDescription>\n' for e in exps)
            + '    </experimentList>\n    <interactorList>\n' + "".join(interactors)
            + '    </interactorList>\n    <interactionList>\n' + "".join(interactions)
            + '    </interactionList>\n  </entry>\n')


def _psi_doc(*entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<entrySet level="2" version="5" '
            'xmlns="http://psi.hupo.org/mi/mif">\n' + "".join(entries) + '</entrySet>\n')


PSI_ENTRY_1 = _psi_entry(
    ["e1", "e2", "e3"],
    [_psi_interactor("1", [("uniprotkb", "P26367-2"), ("ensembl", "ENSG00000007372.27")], "pax6"),
     _psi_interactor("2", [("uniprotkb", "Q9ULX9"), ("ensembl", "ENSG00000185022.14"),
                           ("ensembl", "ENSP00000384094.1")], "maff"),
     _psi_interactor("3", [("uniprotkb", "P04637")], "p53"),
     _psi_interactor("4", [("uniprotkb", "P38398")], "brca1")],
    [_psi_interaction("10", "e1", ["1", "2"], "pax6-maff"),     # kept: PAX6 (isoform) with a partner
     _psi_interaction("11", "e2", ["3", "4"], "p53-brca1"),     # dropped: no panel participant
     _psi_interaction("12", "e1", ["2", "1", "3"], "three")])  # kept: three participants
PSI_ENTRY_2 = _psi_entry(
    ["e9"],
    [_psi_interactor("2", [("uniprotkb", "Q9ULX9")], "maff"), _psi_interactor("5", [("uniprotkb", "P10635")], "cyp2d6")],
    [_psi_interaction("20", "e9", ["5", "2"], "cyp2d6-maff")])


def _psi_ids(tmp_path, *ids):
    p = tmp_path / "ids.txt"
    p.write_text("".join(i + "\n" for i in ids))
    return str(p)


def test_psi_xml_keeps_interactions_with_a_panel_participant_and_what_they_reference(tmp_path):
    src = tmp_path / "human_01.xml"
    src.write_text(_psi_doc(PSI_ENTRY_1, PSI_ENTRY_2))
    out, res = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "P26367", "P10635", "O00000"),
                    "out.xml", "--xref-db", "uniprotkb")
    root = ET.parse(out).getroot()
    ns = "{http://psi.hupo.org/mi/mif}"
    e1, e2 = root.findall(ns + "entry")
    assert [i.get("id") for i in e1.iter(ns + "interaction")] == ["10", "12"]
    assert [i.get("id") for i in e1.iter(ns + "interactor")] == ["1", "2", "3"]     # 4 is only in the dropped one
    assert [i.get("id") for i in e1.iter(ns + "experimentDescription")] == ["e1"]
    assert [i.get("id") for i in e2.iter(ns + "interaction")] == ["20"]
    # interactor 2 is written once per file: PsiConverter throws on an id seen twice in a file
    assert [i.get("id") for i in e2.iter(ns + "interactor")] == ["5"]
    assert e1.find(ns + "source") is not None
    assert res["records_in"] == 4 and res["records_out"] == 3
    assert res["interactors_in"] == 6 and res["interactors_out"] == 4 and res["repeated_interactors_dropped"] == 1
    assert res["experiments_in"] == 4 and res["experiments_out"] == 2
    assert res["ids_given"] == 3 and res["ids_matched"] == 2


def test_psi_xml_drops_ensembl_versions_so_the_resolver_knows_the_genes(tmp_path):
    src = tmp_path / "h.xml"
    src.write_text(_psi_doc(PSI_ENTRY_1))
    out, res = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "P26367"), "o.xml", "--xref-db", "uniprotkb")
    text = read(out).decode()
    assert 'id="ENSG00000007372"' in text and 'id="ENSG00000185022"' in text and 'id="ENSP00000384094"' in text
    assert ".27\"" not in text and res["ensembl_unversioned"] == 3


def test_psi_xml_xref_db_restricts_which_ids_count(tmp_path):
    src = tmp_path / "h.xml"
    src.write_text(_psi_doc(PSI_ENTRY_1))
    # the panel id as an ensembl xref only: matched with any db, not with --xref-db uniprotkb
    _, any_db = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "ENSG00000185022.14"), "a.xml")
    _, uni = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "ENSG00000185022.14"), "b.xml",
                  "--xref-db", "UniProtKB")
    assert any_db["records_out"] == 2 and uni["records_out"] == 0


def test_psi_xml_is_byte_faithful_and_split_across_read_chunks(tmp_path, monkeypatch):
    src, a, b = tmp_path / "h.xml", str(tmp_path / "a.xml"), str(tmp_path / "b.xml")
    src.write_text(_psi_doc(PSI_ENTRY_1, PSI_ENTRY_2))
    ids = {"P26367", "P10635"}
    subset_raw.filter_psi_xml(str(src), a, ids, ["uniprotkb"])
    monkeypatch.setattr(subset_raw, "_CHUNK", 7)
    subset_raw.filter_psi_xml(str(src), b, ids, ["uniprotkb"])
    assert read(a) == read(b)
    kept = read(a).decode()
    assert kept.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<entrySet level="2"')
    assert '      <interaction id="10">\n        <names><shortLabel>pax6-maff</shortLabel></names>' in kept
    assert "\n\n" not in kept                         # a dropped block takes its indentation with it


def test_psi_xml_refuses_the_expanded_form(tmp_path):
    src = tmp_path / "h.xml"
    src.write_text(_psi_doc('  <entry>\n    <interactionList><interaction id="1"><participantList><participant id="2">'
                            '<interactor id="3"><xref><primaryRef db="uniprotkb" id="P26367"/></xref></interactor>'
                            '</participant></participantList></interaction></interactionList>\n  </entry>\n'))
    p = run_cli("filter", "--format", "psi-xml", "--in", str(src), "--out", str(tmp_path / "o.xml"),
                "--ids", _psi_ids(tmp_path, "P26367"))
    assert p.returncode == 2 and "expanded" in p.stderr and not (tmp_path / "o.xml").exists()


def test_psi_xml_from_a_zip_writes_matching_members_under_their_names(tmp_path):
    import zipfile
    z = tmp_path / "human.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("human_01.xml", _psi_doc(PSI_ENTRY_1))
        zf.writestr("human_02.xml", _psi_doc(PSI_ENTRY_2))
        zf.writestr("README.txt", "not xml")
    out = tmp_path / "work"
    out.mkdir()
    (out / "stale.xml").write_text("from an earlier run")
    p = run_cli("filter", "--format", "psi-xml", "--in", str(z), "--member", "*.xml", "--out", str(out),
                "--ids", _psi_ids(tmp_path, "P26367"), "--xref-db", "uniprotkb")
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout)
    assert sorted(os.listdir(out)) == ["human_01.xml"]          # human_02 has no PAX6 interaction
    assert res["files_in"] == 2 and res["files_out"] == 1 and res["files"] == ["human_01.xml"]
    assert res["records_in"] == 4 and res["records_out"] == 2


def test_psi_xml_member_glob_matches_a_biogrid_name_inside_a_folder(tmp_path):
    import zipfile
    z = tmp_path / "BIOGRID-ORGANISM-LATEST.psi25.zip"
    name = "BIOGRID-ORGANISM-Homo_sapiens-4.4.250.psi25.xml"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("BIOGRID-ORGANISM-Mus_musculus-4.4.250.psi25.xml", _psi_doc(PSI_ENTRY_1))
        zf.writestr("sub/" + name, _psi_doc(PSI_ENTRY_1))
    out = tmp_path / "w"
    subset_raw.filter_psi_xml(str(z), str(out), {"P26367"}, ["uniprotkb"], "BIOGRID-ORGANISM-Homo_sapiens-*.psi25.xml")
    assert os.listdir(out) == [name]


def test_psi_xml_member_and_xref_db_are_for_psi_xml_only(tmp_path):
    p = run_cli("filter", "--format", "gaf", "--in", fx("gaf_in.gaf"), "--out", str(tmp_path / "o"),
                "--ids", fx("gaf_ids.txt"), "--member", "*.xml")
    assert p.returncode == 2 and "psi-xml" in p.stderr


def test_psi_xml_drops_negative_interactions(tmp_path):
    """IntAct's human_NN_negative.xml hold interactions shown NOT to happen; the converters ignore the flag."""
    neg = _psi_interaction("13", "e3", ["1", "4"], "pax6-brca1-negative").replace(
        "        <participantList>", "        <negative>true</negative>\n        <participantList>")
    entry = PSI_ENTRY_1.replace("    </interactionList>", neg + "    </interactionList>")
    src = tmp_path / "human_01_negative.xml"
    src.write_text(_psi_doc(entry))
    out, res = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "P26367"), "o.xml", "--xref-db", "uniprotkb")
    assert res["negative_dropped"] == 1 and res["records_in"] == 4 and res["records_out"] == 2
    text = read(out).decode()
    assert "pax6-brca1-negative" not in text and 'id="e3"' not in text and 'interactor id="4"' not in text


def _psi_roled_interaction(iid, parts):
    """An interaction whose participants (interactor id, experimental role) carry roles, as IntAct writes them."""
    ps = "".join(f'\n          <participant id="p{iid}_{r}">\n            <interactorRef>{r}</interactorRef>\n'
                 f'            <experimentalRoleList><experimentalRole><names><shortLabel>{role}</shortLabel>'
                 f'</names></experimentalRole></experimentalRoleList>\n          </participant>' for r, role in parts)
    return (f'      <interaction id="{iid}">\n        <names><shortLabel>i{iid}</shortLabel></names>\n'
            f'        <experimentList><experimentRef>e1</experimentRef></experimentList>\n'
            f'        <participantList>{ps}\n        </participantList>\n      </interaction>\n')


def test_psi_xml_trims_nary_interactions_to_the_participants_that_pair_with_a_panel_gene(tmp_path):
    """Both converters make every pair of an interaction's participants except prey-prey; a bait with many preys
    where the panel gene is one prey would load bait-prey pairs for every other prey too."""
    interactors = [_psi_interactor(i, [("uniprotkb", acc)], i) for i, acc in
                   (("1", "P26367"), ("2", "Q00001"), ("3", "Q00002"), ("4", "Q00003"), ("5", "Q00004"))]
    entry = _psi_entry(["e1"], interactors, [
        _psi_roled_interaction("30", [("2", "bait"), ("1", "prey"), ("3", "prey"), ("4", "prey")]),   # PAX6 a prey
        _psi_roled_interaction("31", [("1", "bait"), ("3", "prey"), ("4", "prey")]),                 # PAX6 the bait
        _psi_roled_interaction("32", [("1", "neutral component"), ("3", "neutral component"),
                                      ("5", "neutral component")]),                                  # a complex
        _psi_roled_interaction("33", [("3", "bait"), ("4", "prey"), ("5", "prey")])])                # no PAX6
    src = tmp_path / "h.xml"
    src.write_text(_psi_doc(entry))
    out, res = filt(tmp_path, "psi-xml", str(src), _psi_ids(tmp_path, "P26367"), "o.xml", "--xref-db", "uniprotkb")
    root = ET.parse(out).getroot()
    ns = "{http://psi.hupo.org/mi/mif}"
    kept = {i.get("id"): [r.text for r in i.iter(ns + "interactorRef")] for i in root.iter(ns + "interaction")}
    assert kept == {"30": ["2", "1"], "31": ["1", "3", "4"], "32": ["1", "3", "5"]}
    assert [i.get("id") for i in root.iter(ns + "interactor")] == ["1", "2", "3", "4", "5"]
    assert res["trimmed"] == 1 and res["participants_dropped"] == 2
    assert "\n          <participant id=\"p30_1\">" in read(out).decode()     # kept ones keep their layout


def test_real_intact_sample(tmp_path):
    """One entry of IntAct's human_10.xml (Oct 2026): two PAX6 (P26367) interactions, two without it."""
    out, res = filt(tmp_path, "psi-xml", os.path.join(REAL, "intact_human_sample.xml.gz"),
                    os.path.join(REAL, "intact_ids.txt"), "o.xml", "--xref-db", "uniprotkb")
    assert read(out) == read(os.path.join(REAL, "intact_expected.xml"))
    assert (res["records_in"], res["records_out"], res["interactors_out"], res["experiments_out"]) == (4, 2, 3, 1)
    assert res["ensembl_unversioned"] == 37 and 'id="ENSG00000007372"' in read(out).decode()   # PAX6's gene


def test_real_biogrid_sample(tmp_path):
    """BioGRID 5.0.263 human: three PAX6 (Entrez 5080) - IPO13 interactions, three without PAX6."""
    out, res = filt(tmp_path, "psi-xml", os.path.join(REAL, "biogrid_human_sample.psi25.xml"),
                    os.path.join(REAL, "biogrid_ids.txt"), "o.xml", "--xref-db", "entrez gene/locuslink")
    assert read(out) == read(os.path.join(REAL, "biogrid_expected.psi25.xml"))
    assert (res["records_in"], res["records_out"], res["interactors_out"], res["experiments_out"]) == (6, 3, 2, 3)


# ------------------------------------------------------------------ GTEx GCT, versioned Ensembl ids, HPO [im-9n4.14, im-9n4.15]

GCT = ("#1.2\n56200\t54\n"
       "Name\tDescription\tAdipose - Subcutaneous\tBrain - Cortex\n"
       "ENSG00000007372.22\tPAX6\t1.5\t30.2\n"
       "ENSG00000100197.20\tCYP2D6\t0.1\t2.0\n"
       "ENSG00000999999.1\tOTHER\t5\t6\n")


def test_tab_strips_the_version_of_an_ensembl_id_when_matching():
    ids = {"ENSG00000007372"}
    assert subset_raw._cell_hit("ENSG00000007372.22", ids) == "ENSG00000007372"
    assert subset_raw._cell_hit("ENSG00000007372", ids) == "ENSG00000007372"
    assert subset_raw._cell_hit("ENSG00000007373.1", ids) is None


def test_gct_keeps_its_three_leading_lines_and_matches_versioned_ids(tmp_path):
    src = tmp_path / "g.gct"
    src.write_text(GCT)
    ids = tmp_path / "ids.txt"
    ids.write_text("ENSG00000007372\nENSG00000100197\n")
    out, res = filt(tmp_path, "tab", str(src), str(ids), "o.gct", "--column", "1", "--keep-lines", "3")
    lines = read(out).decode().splitlines()
    assert lines[:3] == ["#1.2", "56200\t54", "Name\tDescription\tAdipose - Subcutaneous\tBrain - Cortex"]
    assert [l.split("\t")[1] for l in lines[3:]] == ["PAX6", "CYP2D6"]
    assert res["records_in"] == 3 and res["records_out"] == 2     # the dimensions line and the header are not records


def test_gct_gzipped_input_is_read_by_suffix(tmp_path):
    src = tmp_path / "g.gct.gz"
    with gzip.open(src, "wt") as fh:
        fh.write(GCT)
    ids = tmp_path / "ids.txt"
    ids.write_text("ENSG00000007372\n")
    out, res = filt(tmp_path, "tab", str(src), str(ids), "o.gct", "--column", "1", "--keep-lines", "3")
    assert b"PAX6" in read(out) and b"CYP2D6" not in read(out)


G2P = ("ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id\n"
       "5080\tPAX6\tHP:0000007\tAutosomal recessive inheritance\t-\tOMIM:607108\n"
       "5080\tPAX6\tHP:0001939\tAbnormality\t-\tORPHA:77\n"
       "1565\tCYP2D6\tHP:0002460\tWeakness\t15/15\tOMIM:608902\n")
HPOA = ('#description: "HPO annotations"\n#version: 2026-09-02\n'
        "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex\tmodifier\taspect\tbiocuration\n"
        "OMIM:607108\tAniridia\t\tHP:0000007\tPMID:1\tPCS\t\t\t\t\tP\tHPO:a[2021-01-01]\n"
        "OMIM:100000\tOther\t\tHP:0000007\tPMID:2\tPCS\t\t\t\t\tP\tHPO:a[2021-01-01]\n"
        "ORPHA:77\tAlexander disease\tNOT\tHP:0001939\tORPHA:77\tTAS\t\t\t\t\tP\tORPHA:orphadata[2021-01-01]\n")


def test_disease_ids_then_hpoa_cut(tmp_path, capsys):
    g2p = tmp_path / "g2p.txt"
    g2p.write_text(G2P)
    ids = tmp_path / "ids.txt"
    ids.write_text("5080\n")
    out, _ = filt(tmp_path, "tab", str(g2p), str(ids), "g2p_f.txt", "--column", "1", "--keep-comments")
    sets = tmp_path / "sets"
    p = run_cli("disease-ids", "--in", out, "--out", str(sets))
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == {"hpo-diseases": 2, "by_db": {"OMIM": 1, "ORPHA": 1}}
    assert (sets / "hpo-diseases.txt").read_text() == "OMIM:607108\nORPHA:77\n"
    hpoa = tmp_path / "phenotype.hpoa"
    hpoa.write_text(HPOA)
    out2, res = filt(tmp_path, "tab", str(hpoa), str(sets / "hpo-diseases.txt"), "hpoa_f", "--column", "1")
    text = read(out2).decode()
    assert "OMIM:607108" in text and "ORPHA:77" in text and "OMIM:100000" not in text
    assert text.startswith("#description")             # comment lines stay
    assert res["records_in"] == 4 and res["records_out"] == 2   # the database_id header line counts as a row
