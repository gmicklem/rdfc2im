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


@pytest.mark.parametrize("fmt", ["gaf", "gff3", "uniprot-xml", "fasta", "tab"])
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


def test_real_refseq_gff3_sample(tmp_path):
    out, res = filt(tmp_path, "gff3", os.path.join(REAL, "refseq_grch38_sample.gff3"), os.path.join(REAL, "gff3_ids.txt"))
    assert read(out) == read(os.path.join(REAL, "refseq_expected.gff3"))
    assert res["ids_matched"] == 2
