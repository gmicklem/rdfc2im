# Licences of the data in the hybrid HumanMine demo [im-9n4.45]

What each data source of the demo build states about its own licence, read from the source on **2026-11-18 (UTC)**
and not from memory or from what this repository recorded before. This file is the summary; the records themselves
are in YAML and are what the code reads:

| What | Where |
|---|---|
| the 20 stock sources | `rdfc2im/data/stock_sources.yaml` (`licence`, `licence_status`, `licence_url`, `licence_checked`, `licence_quote`, `licence_conditions`, `redistributable`, `redistributable_reason`) |
| the ten RDF sources | `rdfc2im/data/sources.yaml` (the same keys for the upstream; `rdfportal_licence`, `rdfportal_licence_url`, `rdfportal_licence_note` for what RDF Portal's own data set page says) |
| stock reactome, the resolver's NCBI `gene_info`, the BlueGenes tool packages, imjs | `rdfc2im/data/other_licences.yaml` |
| the data-source pages (`humanmine/docs/data-sources/`) | `tools/source_pages.py` shows name, status, link, date read, wording, conditions and redistributable for every source |

`licence_status` says how far the record can be trusted: **verified** (stated on the source's own page or in its
file), **partial** (a related statement was read, not the full one), **not-verified** (the source points to a page
that could not be read), **not-stated** (nothing findable; the record lists what was looked at), **not-checked**.
The earlier table was written from general knowledge on 17 Nov; where it differed, the source won (see "What changed").

`redistributable: true` means the stated terms allow a filtered copy in a public GitHub release asset. For a source
that is not **verified** it means only that no stated term forbids it: the flag stays true so that
`check_prereqs` and `cache check-release` keep working, and the source is on the hold list below.
`python -m rdfc2im cache check-release` reads the flag recorded in each cache group's META, so it cannot tell a
verified licence from an unverified one; this file and `licence_status` do.

## The licence of each source

| Source | Licence | Status | Stated at | Read | Redistributable | Conditions |
|---|---|---|---|---|---|---|
| stock `uniprot` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-18 | yes | attribution; say the data were changed |
| stock `uniprot-fasta` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-18 | yes | attribution; say the data were changed |
| stock `uniprot-keywords` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-18 | yes | attribution |
| stock `ncbi-gff` | NCBI FTP notice: unrestricted public data (no licence named) | partial | <https://ftp.ncbi.nlm.nih.gov/README.ftp> | 2026-11-18 | yes (flag only) | none named; NCBI policy page unread |
| stock `go-annotation` | GOA copyright notice (free redistribution with the notice) | partial | <https://ftp.ebi.ac.uk/pub/databases/GO/goa/HUMAN/README> | 2026-11-18 | yes (flag only) | reproduce the GOA copyright notice with each copy |
| stock `interpro-go` | not verified | not stated | <https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/interpro2go> | 2026-11-18 | yes (flag only) | unknown (statement not readable) |
| stock `panther` | not verified | not stated | <https://data.pantherdb.org/ftp/ortholog/current_release/README> | 2026-11-18 | yes (flag only) | unknown (terms not found) |
| stock `mgi-identifiers` | CC-BY-4.0 | verified | <https://www.informatics.jax.org/mgihome/other/copyright.shtml> | 2026-11-18 | yes | attribution (CC BY) |
| stock `rgd-identifiers` | not verified | not stated | <https://download.rgd.mcw.edu/data_release/README.txt> | 2026-11-18 | yes (flag only) | unknown (terms not found) |
| stock `psi-mi-ontology` | CC-BY-4.0 | verified | <https://raw.githubusercontent.com/HUPO-PSI/psi-mi-CV/master/LICENSE> | 2026-11-18 | yes | attribution (CC BY) |
| stock `psi-intact` | not verified (EMBL-EBI terms of use apply) | not stated | <https://www.ebi.ac.uk/about/terms-of-use/> | 2026-11-18 | yes (flag only) | unknown (statement not readable) |
| stock `biogrid` | MIT | verified | <https://downloads.thebiogrid.org/BioGRID/Latest-Release/> | 2026-11-18 | yes | MIT notice; citation of Stark et al. 2006 requested |
| stock `protein-atlas` | CC-BY-4.0 | verified | <https://www.proteinatlas.org/about/licence> | 2026-11-18 | yes | attribution: primary publication AND "Human Protein Atlas proteinatlas.org"; cite the data and URL; third-party data caveat |
| stock `protein-atlas-rna` | CC-BY-4.0 | verified | <https://www.proteinatlas.org/about/licence> | 2026-11-18 | yes | as protein-atlas |
| stock `gtex` | not verified | not stated | <https://storage.googleapis.com/adult-gtex/> | 2026-11-18 | yes (flag only) | unknown (terms not found) |
| stock `atlas-express` | CC-BY-4.0 | verified | <https://www.ebi.ac.uk/gxa/licence.html> | 2026-11-18 | yes | attribution: cite Expression Atlas 2026 (NAR) |
| stock `hpo-annotation` | not verified (points to https://hpo.jax.org/app/license) | not verified | <https://raw.githubusercontent.com/obophenotype/human-phenotype-ontology/master/README.md> | 2026-11-18 | yes (flag only) | unknown (terms on a blocked page) |
| stock `orphanet` | CC-BY-4.0 | verified | <https://www.orphadata.com/legal-notice/> | 2026-11-18 | yes | attribution: Orphadata Science citation; say if changed; no endorsement; AI-use statement if used in an AI service |
| stock `ncbi-fasta` | NCBI FTP notice: unrestricted public data (no licence named) | partial | <https://ftp.ncbi.nlm.nih.gov/README.ftp> | 2026-11-18 | yes (flag only) | none named; NCBI policy page unread |
| stock `omim` | OMIM licensed download (personal or institutional use only) | not checked | none found | 2026-11-18 | no | licensed copy only (not read today) |
| stock `reactome` | CC0-1.0 | verified | <https://reactome.org/license> | 2026-11-18 | yes | attribution encouraged, not required |
| ID resolver `gene_info` | NCBI FTP notice: unrestricted | partial | <https://ftp.ncbi.nlm.nih.gov/README.ftp> | 2026-11-18 | yes | none named; NCBI policy page unread |
| RDF `go` | CC-BY-4.0 | partial | <https://current.geneontology.org/ontology/go-basic.obo> | 2026-11-18 | yes (flag only) | attribution to the GO Consortium |
| RDF `ncbigene` | NCBI FTP notice: unrestricted public data (no licence named) | partial | <https://ftp.ncbi.nlm.nih.gov/README.ftp> | 2026-11-18 | yes (flag only) | none named; NCBI policy page unread |
| RDF `reactome` | CC0-1.0 | verified | <https://reactome.org/license> | 2026-11-18 | yes | attribution encouraged, not required |
| RDF `hgnc` | not verified | not verified | <https://rdfportal.org/dataset/hgnc/> | 2026-11-18 | yes (flag only) | unknown (page blocked) |
| RDF `ensembl` | not verified | not verified | <https://rdfportal.org/dataset/ensembl/> | 2026-11-18 | yes (flag only) | unknown (page blocked) |
| RDF `uniprot` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-18 | yes | attribution; say the data were changed |
| RDF `clinvar` | NCBI FTP notice: unrestricted public data (no licence named) | partial | <https://ftp.ncbi.nlm.nih.gov/README.ftp> | 2026-11-18 | yes (flag only) | none named; ClinVar page unread |
| RDF `gwascatalog` | EMBL-EBI terms of use (summary statistics CC0) | partial | <https://www.ebi.ac.uk/gwas/docs/about> | 2026-11-18 | yes (flag only) | EMBL-EBI terms; TogoVar terms unread |
| RDF `pubmed` | NLM terms and conditions (free; acknowledge NLM) | verified | <https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/README.txt> | 2026-11-18 | yes | acknowledge NLM; no PubMed logo; state the data may not be current; abstracts may be copyrighted |
| RDF `hpo` | not verified (points to https://hpo.jax.org/app/license) | not verified | <http://purl.obolibrary.org/obo/hp.obo> | 2026-11-18 | yes (flag only) | unknown (page blocked) |
| BlueGenes tools (18 npm packages) | MIT x16, LGPL-3.0 x1, LGPL-2.1 x1 | verified | package.json and LICENSE inside each cached tarball | 2026-11-18 | yes | keep the notices; LGPL text beside the two LGPL tools (protvista has no LICENSE file) |
| `imjs` 4.0.0 | LGPL-3.0 | verified | <https://registry.npmjs.org/imjs/-/imjs-4.0.0.tgz> (LICENCE) | 2026-11-18 | yes | LGPL notice and a pointer to the source |

## What the converters stamp, and what the mine shows

"Converter stamps" is the value hard-coded in the loader (or its project.xml property); "Mine shows" is
`DataSet.licence` in the demo mine on port 18090, read 2026-11-18 through `service/query/results`. RDF sources
load through `humanmine-items`, and rdfc2im's items carry no `DataSet.licence`, so all ten RDF data sets show empty.

| Source | Table said before | Converter stamps (file:line) | Mine shows (DataSet.licence) |
|---|---|---|---|
| stock `uniprot` | CC BY 4.0 (UniProt) | http://creativecommons.org/licenses/by/4.0/ (intermine UniprotConverter.java:82) | Swiss-Prot data set, UniProt data set: same URL |
| stock `uniprot-fasta` | CC BY 4.0 (UniProt) | none: FastaLoaderTask.java:385 sets it only when the project.xml `licence` property is given, and it is not | uniprot-fasta: empty |
| stock `uniprot-keywords` | CC BY 4.0 (UniProt) | http://creativecommons.org/licenses/by/4.0/ (UniprotKeywordConverter.java:45) | UniProt data set: same URL (shared with uniprot) |
| stock `ncbi-gff` | public domain (NCBI RefSeq) | none (the GFF3 loader's DataSet has no licence property set) | ncbi-gff: empty |
| stock `go-annotation` | CC BY 4.0 (GO Consortium, GOA) | none: GoConverter.java:113 takes a `licence` property that project.xml does not set | GO Annotation data set: empty |
| stock `interpro-go` | CC0 (InterPro) | none, passes null (InterproGoConverter.java:48) | InterPro domain GO annotations: empty |
| stock `panther` | PANTHER terms of use, free with citation (unverified) | http://www.gnu.org/licenses/gpl.txt (PantherConverter.java:69-70) | Panther orthologue and paralogue predictions: the GPL URL |
| stock `mgi-identifiers` | MGI data are free to use with citation | none (MgiIdentifiersConverter.java:43) | Mouse gene identifiers: empty |
| stock `rgd-identifiers` | RGD data are free to use with citation (unverified) | none, passes null (RgdIdentifiersConverter.java:50) | Rat gene identifiers: empty |
| stock `psi-mi-ontology` | CC BY 4.0 (HUPO-PSI; unverified) | https://creativecommons.org/licenses/by/4.0/ (psi-mi-ontology.properties:10) | PSI Molecular Interactions: same URL |
| stock `psi-intact` | CC BY 4.0 (IntAct, EMBL-EBI) | https://www.apache.org/licenses/LICENSE-2.0 (PsiConverter.java:81; being fixed in the intermine checkout) | IntAct molecular interactions: the Apache URL |
| stock `biogrid` | MIT (BioGRID; unverified) | https://opensource.org/licenses/MIT (BioGridConverter.java:97) | BioGRID interaction data set: same URL |
| stock `protein-atlas` | CC BY-SA 4.0, share-alike | https://creativecommons.org/licenses/by-sa/3.0/ (humanmine-bio-sources ProteinAtlasConverter.java:53) | The Human Protein Atlas expression profiles: the by-sa/3.0 URL |
| stock `protein-atlas-rna` | CC BY-SA 4.0, share-alike | https://creativecommons.org/licenses/by-sa/3.0/ (ProteinAtlasRNAConverter.java:40; also protein-atlas-rna-tgt.xml:50) | Protein Atlas RNA Gene data: the by-sa/3.0 URL |
| stock `gtex` | GTEx open-access summary data | none (GtexConverter.java:55 passes null names; no licence) | RNA-Seq Data, Single-Tissue cis-eQTL Data: empty |
| stock `atlas-express` | CC BY 4.0 (Expression Atlas, EMBL-EBI) | none (AtlasExpressConverter.java:53) | atlas-express: empty |
| stock `hpo-annotation` | HPO licence (reuse with attribution, terms not to be altered; unverified) | https://hpo.jax.org/app/license (HpoConverter.java:80) | hpo-annotation: same URL |
| stock `orphanet` | CC BY 4.0 (Orphanet) | https://creativecommons.org/licenses/by/4.0/ (OrphanetConverter.java:41) | orphanet: same URL |
| stock `reactome` | CC0 (Reactome), written in tools/source_manifest.py | https://creativecommons.org/publicdomain/zero/1.0/ (intermine ReactomeConverter.java:54) | Reactome pathways data set: same URL |
| ID resolver `gene_info` | not recorded | n/a (not a data set) | n/a |
| RDF `go` | not recorded | none: the rdfc2im items carry no DataSet.licence | GO (RDF Portal): empty |
| RDF `ncbigene` | not recorded | none: the rdfc2im items carry no DataSet.licence | NCBI Gene (RDF Portal): empty |
| RDF `reactome` | not recorded | none: the rdfc2im items carry no DataSet.licence | shares "Reactome pathways data set" with stock reactome: empty |
| RDF `hgnc` | not recorded | none: the rdfc2im items carry no DataSet.licence | HGNC identifiers (RDF Portal): empty |
| RDF `ensembl` | not recorded | none: the rdfc2im items carry no DataSet.licence | Ensembl genes (RDF Portal): empty |
| RDF `uniprot` | not recorded | none: the rdfc2im items carry no DataSet.licence | UniProtKB, Swiss-Prot and TrEMBL (RDF Portal): empty |
| RDF `clinvar` | not recorded | none: the rdfc2im items carry no DataSet.licence | ClinVar (RDF Portal): empty |
| RDF `gwascatalog` | not recorded | none: the rdfc2im items carry no DataSet.licence | GWAS Catalog (TogoVar): empty |
| RDF `pubmed` | not recorded | none: the rdfc2im items carry no DataSet.licence | PubMed (RDF Portal): empty |
| RDF `hpo` | not recorded | none: the rdfc2im items carry no DataSet.licence | Human Phenotype Ontology (RDF Portal): empty |

## What changed from the earlier record

| Source | Was | Is | Why |
|---|---|---|---|
| protein-atlas, protein-atlas-rna | CC BY-SA 4.0, share-alike | **CC BY 4.0**, not share-alike | proteinatlas.org/about/licence: "licensed under the Creative Commons Attribution 4.0 International License". The share-alike duty the old notice described does not exist. |
| biogrid | MIT (unverified) | MIT, verified | downloads.thebiogrid.org: "under the MIT License" |
| mgi-identifiers | free to use with citation | CC BY 4.0 | informatics.jax.org copyright page: "licensed under a Creative Commons Attribution 4.0 International License (CC-BY)" |
| psi-mi-ontology | CC BY 4.0 (unverified) | CC BY 4.0, verified | the HUPO-PSI/psi-mi-CV repository (where mi.obo comes from) has a CC BY 4.0 LICENSE |
| go-annotation | CC BY 4.0 (GOA) | GOA copyright notice, partial | the GAF states nothing; the EBI GOA README allows free redistribution if its notice is kept; geneontology.org is blocked |
| ncbi-gff, ID resolver, RDF ncbigene and clinvar | public domain | "unrestricted public data", partial | the NCBI FTP notice does not say "public domain" or name a licence; the policy pages are on a blocked host |
| panther | free with citation (unverified) | not verified (nothing stated) | no statement found; the converter's GPL URL is unsupported too |
| rgd-identifiers | free to use with citation (unverified) | not verified (nothing stated) | no statement found at the allowed host |
| psi-intact | CC BY 4.0 | not verified (statement not readable) | IntAct's licence page is a JavaScript page; the converter's Apache-2.0 is a software licence |
| gtex | open-access summary data | not verified (nothing stated) | no statement at the allowed host |
| hpo-annotation, RDF hpo | reuse with attribution, terms not to be altered | not verified | the sources point to hpo.jax.org/app/license, which is blocked; the old wording is not confirmed |
| interpro-go | CC0 | not verified (nothing stated) | no statement in the file or the FTP tree; the web page is JavaScript |
| atlas-express, orphanet, uniprot* | CC BY 4.0 | CC BY 4.0, verified | stated on the sources' pages and files |
| stock reactome | CC0 (hard-coded in the manifest tool) | CC0, now read from other_licences.yaml | reactome.org/license: "All data ... are licensed under the Creative Commons Public Domain Dedication (CC0)" |

No `redistributable` flag was changed: nothing read forbids a copy. The conflicts are the unverified sources below.

## Converter mismatches (for a follow-up in the intermine and humanmine-bio-sources checkouts)

Files are under `bio/sources/` of the intermine checkout (im-ore.14-testbed-src) and at the top of
`humanmine-bio-sources`. Nothing there was edited.

| Converter | Line | Stamps | What the source states | Suggested value |
|---|---|---|---|---|
| humanmine-bio-sources `protein-atlas` ProteinAtlasConverter.java | 53 | `by-sa/3.0` | CC BY 4.0 | `https://creativecommons.org/licenses/by/4.0/`; the test resource ProteinAtlasConverterTest.xml expects the old value |
| `protein-atlas-rna` ProteinAtlasRNAConverter.java | 40 | `by-sa/3.0` | CC BY 4.0 | as above; also `protein-atlas-rna-tgt.xml` line 50 and ProteinAtlasRNAConverterTest-tgt.xml |
| intermine `psi` PsiConverter.java | 81 | Apache-2.0 URL | not verified; Apache is a software licence | another worker is fixing it; until IntAct's statement is read, none |
| intermine `panther` PantherConverter.java | 69-70 | `http://www.gnu.org/licenses/gpl.txt` | not found; GPL is a software licence | none, until pantherdb.org is read; PantherConverterTest and PantherConverterTest_tgt.xml expect the GPL URL |
| intermine `go-annotation` GoConverter.java | 113, 146, 160 | none (needs a `licence` property project.xml does not set) | GOA notice; CC BY 4.0 for the ontology | set the property in HumanMine's project.xml |
| intermine `mgi-identifiers` MgiIdentifiersConverter.java | 43 | none | CC BY 4.0 | pass `https://creativecommons.org/licenses/by/4.0/` |
| intermine `rgd-identifiers` RgdIdentifiersConverter.java | 50 | null | not verified | none yet |
| humanmine-bio-sources `gtex` GtexConverter.java | 55 | none | not verified | none yet |
| humanmine-bio-sources `atlas-express` AtlasExpressConverter.java | 53 | none | CC BY 4.0 | `https://creativecommons.org/licenses/by/4.0/` |
| intermine `interpro-go` InterproGoConverter.java | 48 | null | not verified | none yet |
| intermine `fasta` FastaLoaderTask.java (uniprot-fasta) | 385 | none unless project.xml sets `licence` | CC BY 4.0 | set the property |
| ncbi-gff (GFF3 loader properties) | n/a | none | unrestricted notice | set once the NCBI policy page is read |

They agree with the source (cosmetic differences only): UniprotConverter.java:82 and UniprotKeywordConverter.java:45
(http instead of https), BioGridConverter.java:97 (MIT), OrphanetConverter.java:41 (CC BY 4.0), ReactomeConverter.java:54
(CC0), psi-mi-ontology.properties:10 (CC BY 4.0), HpoConverter.java:80 and hpo.properties:17 (the pointer to HPO's page,
which is what HPO itself gives). `uberon.properties:17` says CC BY 3.0 and `go.properties:6`,
`mammalian-phenotype-ontology.properties:17` CC BY 4.0; they are not in the demo and were not checked. The ten RDF
data sets show an empty licence because rdfc2im's items never set `DataSet.licence`; the follow-up is to write the
upstream's licence URL there (the YAML holds the page where it is stated, not yet a separate licence-text URL).

## Sources not verified, and the hosts that would settle them

Each one was tried once on the host named; the proxy answered HTTP 403 "Approval required for <host>".

| Host | Needed for |
|---|---|
| www.pantherdb.org | PANTHER terms of use (stock panther) |
| rgd.mcw.edu | RGD licence and citation page (stock rgd-identifiers) |
| www.gtexportal.org | GTEx licence page (stock gtex) |
| hpo.jax.org | HPO licence page (stock hpo-annotation, RDF hpo) |
| www.genenames.org | HGNC licence (RDF hgnc) |
| www.ensembl.org | Ensembl disclaimer (RDF ensembl) |
| www.ncbi.nlm.nih.gov | NCBI data-use policy and ClinVar's data-use page (ncbi-gff, resolver gene_info, RDF ncbigene and clinvar) |
| togovar.org | TogoVar terms (RDF gwascatalog is read through TogoVar) |
| geneontology.org | GO Consortium licence and citation page (stock go-annotation, RDF go) |

Optional (a statement was already found elsewhere): www.nlm.nih.gov (NLM copyright page; the FTP README gives the
terms), www.uniprot.org (the README and XML give CC BY 4.0), wiki.thebiogrid.org (the download page gives MIT),
interpro-documentation.readthedocs.io (InterPro's FAQ). Two statements are on JavaScript pages of a host that
answers (www.ebi.ac.uk/intact and www.ebi.ac.uk/interpro): they need a browser, not an allow rule.

## Attribution a public mine must show

Words the sources ask for. A "Data sources" page of the mine should carry them; the data-source pages already name each
source, licence and link.

* UniProt (stock uniprot, uniprot-fasta, uniprot-keywords, RDF uniprot): CC BY 4.0, "(c) UniProt Consortium"; say that
  the data were filtered (human Swiss-Prot entries for the gene panel).
* Human Protein Atlas (protein-atlas, protein-atlas-rna): include a reference to a primary publication (for example
  Uhlen M et al., Tissue-based map of the human proteome. Science 2015, PubMed 25613900) AND "Human Protein Atlas
  proteinatlas.org"; for data taken from the site also cite the data and its URL ("data available from
  v##.proteinatlas.org"). CC BY 4.0, not share-alike.
* Expression Atlas (atlas-express): CC BY 4.0; cite "Expression Atlas in 2026: enabling FAIR and open expression data
  through community collaboration and integration (Nucleic Acids Research, 10 December 2025)".
* Orphanet (orphanet): CC BY 4.0; "Orphadata Science: Free access data from Orphanet. (c) INSERM 1999. Available on
  http://sciences.orphadata.com/. Data version [date]."; say if the data were changed; do not imply endorsement; no logos
  without approval. If an AI or LLM service offered to third parties uses the data, it must carry the statement that
  results may not reflect the Orphanet data.
* MGI (mgi-identifiers): CC BY 4.0, credit Mouse Genome Informatics.
* BioGRID (biogrid): MIT; keep the notice. Requested: cite Stark C et al., BioGRID: a general repository for interaction
  datasets, Nucleic Acids Res 2006;34:D535-9.
* PSI-MI controlled vocabulary (psi-mi-ontology): CC BY 4.0, credit HUPO-PSI.
* GOA (go-annotation): reproduce "GOA - GO Annotation. Copyright 2018 (C) The European Bioinformatics Institute."
  with the data; credit the GO Consortium.
* PubMed (RDF pubmed): acknowledge NLM as the source "in a clear and conspicuous manner"; do not use the PubMed
  wordmark or logo or imply NLM, NIH or HHS endorsement; the data are a snapshot, so say that they may not reflect the
  most current data from NLM; some abstracts may be copyrighted.
* Reactome: CC0, no attribution required (given as courtesy). NCBI: no attribution asked on the FTP notice. GWAS
  Catalog: cite the GWAS Catalog; EMBL-EBI terms apply.
* Software shown to users: imjs (LGPL-3.0) and the two LGPL BlueGenes tools (cytoscape-interaction-network-viewer
  LGPL-3.0, protvista LGPL-2.1) need their licence text and a pointer to the source available.

## Release assets (prepared 18 Nov)

* `cached_raw_data-2026-11-18b` (published as release demo-data-2026-11-18): RDF extracts and tool packages. Nothing
  read forbids redistribution, so nothing has to be withdrawn on this evidence. It has no notice file: add one with the
  attribution above (UniProt, GO, Reactome CC0, PubMed acknowledgement and currency statement, the LGPL texts and the
  protvista licence). hgnc, ensembl and hpo are inside it with unverified licences: re-check them once the hosts above
  are read, and withdraw the group if the terms turn out to forbid a copy.
* `stock_filtered-2026-11-18` (not published): do not publish as it stands. Its `LICENCES-stock-filtered.txt` is wrong
  for the Human Protein Atlas (it says CC BY-SA 4.0 share-alike) and for several others. A corrected file is
  `docs/LICENCES-stock-filtered.txt`. Hold back `stock-panther`, `stock-psi-intact`, `stock-gtex` and
  `stock-hpo-annotation` (no readable terms) until their terms are read; `stock-go-annotation` and `stock-ncbi-gff` are
  partial but a notice file covers them. The other seven groups (uniprot, uniprot-fasta, mgi-identifiers, biogrid,
  protein-atlas, protein-atlas-rna, atlas-express) rest on verified statements.
* `cached_raw_data_allgenes-2026-11-18` (not published): `ncbigene` is partial and acceptable with the NCBI notice;
  hold `hgnc` (unverified) until www.genenames.org is read.

## Refreshing this record

Read the source's own statement, then change the YAML (not this file): set `licence_checked`, `licence_url`,
`licence_quote`, `licence_status`. `tests/test_stock.py::test_every_source_has_a_complete_licence_record` checks that
every source has a complete record, and the tests of `tools/source_pages.py` show it on the pages. The pages for a
build come from `tools/source_manifest.py` and `tools/source_pages.py` (USAGE.md, "Data-source status pages"). The
tables above are a snapshot of the YAML at 2026-11-18.
