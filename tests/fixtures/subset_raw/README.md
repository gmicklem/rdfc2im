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
- `intact_human_sample.xml.gz`: one `<entry>` of `human_10.xml` in
  https://ftp.ebi.ac.uk/pub/databases/intact/current/psi25/species/human.zip (IntAct, release dated
  2026-10-24, taken on 18 November 2026; CC BY 4.0, EMBL-EBI), cut to two interactions with PAX6
  (P26367) and two without it, with exactly the interactors and experiments they reference, copied
  verbatim; gzipped because each interactor carries a long xref list. `intact_ids.txt` picks P26367;
  `intact_expected.xml` is the tool's output, checked by eye (the two PAX6 interactions, with DYNLL1
  mouse and HOMER3, their three interactors and one experiment; the Ensembl ids without version).
- `biogrid_human_sample.psi25.xml`: from `BIOGRID-ORGANISM-Homo_sapiens-5.0.263.psi25.xml` in
  https://downloads.thebiogrid.org/Download/BioGRID/Latest-Release/BIOGRID-ORGANISM-LATEST.psi25.zip
  (BioGRID 5.0.263, 29 October 2026, taken on 18 November 2026; MIT licence), cut the same way: three
  interactions with PAX6 (Entrez 5080) and three without. `biogrid_ids.txt` picks 5080;
  `biogrid_expected.psi25.xml` is the tool's output, checked by eye (the three PAX6-IPO13 interactions,
  their two interactors and three experiments).
