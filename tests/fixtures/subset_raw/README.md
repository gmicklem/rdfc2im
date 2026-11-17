# subset_raw fixtures

The files in this directory are small, hand-made inputs and the exact outputs `tools/subset_raw.py`
should give for them (`*_in.*`, `*_ids.txt`, `*_expected.*`). They are compared byte for byte by
`tests/test_subset_raw.py`. `items/` is a tiny `out/` tree and `panel.txt` a two-gene panel for
the `idsets` command.

`real/` holds a few records cut from real upstream files, taken on 17 November 2026:

- `goa_human_sample.gaf`: the header and first 30 rows of
  https://current.geneontology.org/annotations/goa_human.gaf.gz (GOA human, release dated 2026-04/05).
  `goa_ids.txt` picks one accession; `goa_expected.gaf` is the tool's output, checked by eye
  (only the 8 rows of that accession remain, header kept).
- `refseq_grch38_sample.gff3`: the first 40 lines of
  https://ftp.ncbi.nlm.nih.gov/genomes/refseq/vertebrate_mammalian/Homo_sapiens/annotation_releases/current/GCF_000001405.40-RS_2025_08/GCF_000001405.40_GRCh38.p14_genomic.gff.gz
  (RefSeq GRCh38.p14, annotation release 2025-08), fetched with a byte range. `gff3_ids.txt` picks
  GeneID 100287102 (DDX11L1) and 102466751 (MIR6859-1); `refseq_expected.gff3` is the tool's output,
  checked by eye (gene, transcripts, exons and miRNAs of those two genes only).
