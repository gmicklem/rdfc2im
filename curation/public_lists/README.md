# HumanMine's 13 other public lists

The public lists of www.humanmine.org that are not Genomics England PanelApp panels: 10 Gene lists, 2 Protein lists and
1 SNP list (`PL_BHF_UCL_cardiovascGenes`, `PL_Pax6_Targets`, `PL_DiabesityGWAS_pval-4`, ...). `tools/apply_public_lists.py
--legacy curation/public_lists` makes them public lists of a hybrid mine again, each with its own name, description and
tags.

These are HumanMine's own curated lists, contributed by other groups; each list's description (in `lists.json`) names its
source. They are copied here from the archive of HumanMine's public lists made on 17 November 2026 (HumanMine release of
12 February 2022, InterMine 5.0.8) through the public web service, read-only: `historic_artefacts`,
`humanmine-public-lists/2026-11-17/`, exported by `scripts/export_humanmine_public_lists.py`. The archive's README states
no licence for them and neither does this directory; the PanelApp lists are a separate matter (BUILD.md, "Genomics England
gene lists").

Layout, the same as an archive directory:

- `lists.json`: those 13 entries of the web service's `/service/lists` answer (name, type, size, description, tags, ...).
- `members/INDEX.tsv`: file name, list name, rows. `members/<file>.tsv`: the members, a header row then one per line
  (Gene: `Gene.primaryIdentifier` (the Entrez id), `Gene.symbol`, ...; Protein: `Protein.primaryAccession`, ...;
  SNP: `SNP.primaryIdentifier`, ...). The tool uploads the first column.

The tool uploads the members the mine holds (a match on a key field) and appends a note to the description of a list
that only partly resolves; a list with no member in the mine is skipped and reported.
