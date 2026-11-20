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
| stock `ncbi-gff` | No restrictions by NCBI (no licence named) | verified | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-18 | yes | none named; submitters may claim rights in single records; NLM acknowledgement requested for NCBI's own pages |
| stock `go-annotation` | CC-BY-4.0 (GO Consortium); GOA copyright notice for the EBI files | verified | <https://geneontology.org/docs/go-citation-policy/> | 2026-11-18 | yes | CC BY attribution (creator, copyright, licence and disclaimer notices, link); state the GO release date; keep the GOA copyright statement |
| stock `interpro-go` | CC0-1.0 | verified | <https://interpro-documentation.readthedocs.io/en/latest/license.html> | 2026-11-18 | yes | none (citation requested) |
| stock `panther` | not verified | not stated | <https://data.pantherdb.org/ftp/ortholog/current_release/README> | 2026-11-18 | yes (flag only) | unknown: pantherdb.org refuses automated readers (Cloudflare), no terms in the FTP tree |
| stock `mgi-identifiers` | CC-BY-4.0 | verified | <https://www.informatics.jax.org/mgihome/other/copyright.shtml> | 2026-11-18 | yes | attribution (CC BY) |
| stock `rgd-identifiers` | CC-BY-4.0 | verified | <https://rgd.mcw.edu/wg/disclaimer/> | 2026-11-18 | yes | attribution (credit, link, say if changed); cite RGD in the form on rgd.mcw.edu/wg/citing-rgd/ |
| stock `psi-mi-ontology` | CC-BY-4.0 | verified | <https://raw.githubusercontent.com/HUPO-PSI/psi-mi-CV/master/LICENSE> | 2026-11-18 | yes | attribution (CC BY) |
| stock `psi-intact` | CC-BY-4.0 | verified | <https://raw.githubusercontent.com/Intact-portal/intact-portal-documentation/master/about/license-privacy.md> | 2026-11-18 | yes | appropriate credit (IntAct publications page); Apache-2.0 is for IntAct's software only |
| stock `biogrid` | MIT | verified | <https://downloads.thebiogrid.org/BioGRID/Latest-Release/> | 2026-11-18 | yes | MIT notice; citation of Stark et al. 2006 requested |
| stock `protein-atlas` | CC-BY-4.0 | verified | <https://www.proteinatlas.org/about/licence> | 2026-11-18 | yes | attribution: primary publication AND "Human Protein Atlas proteinatlas.org"; cite the data and URL; third-party data caveat |
| stock `protein-atlas-rna` | CC-BY-4.0 | verified | <https://www.proteinatlas.org/about/licence> | 2026-11-18 | yes | as protein-atlas |
| stock `gtex` | GTEx Portal Data License | verified | <https://www.gtexportal.org/home/license> | 2026-11-18 | yes | acknowledge the GTEx Portal (prescribed phrase); no endorsement; keep the data current or say clearly that they may not be |
| stock `atlas-express` | CC-BY-4.0 | verified | <https://www.ebi.ac.uk/gxa/licence.html> | 2026-11-18 | yes | attribution: cite Expression Atlas 2026 (NAR) |
| stock `hpo-annotation` | HPO licence | verified | <https://hpo.jax.org/license> | 2026-11-18 | yes | acknowledge and cite; show file dates or versions; content and relationships not to be altered (a row-subset is a reading the owner must accept) |
| stock `orphanet` | CC-BY-4.0 | verified | <https://www.orphadata.com/legal-notice/> | 2026-11-18 | yes | attribution: Orphadata Science citation; say if changed; no endorsement; AI-use statement if used in an AI service |
| stock `protein2ipr` | CC0-1.0 | verified | <https://interpro-documentation.readthedocs.io/en/latest/license.html> | 2026-11-20 | yes | none (citation of InterPro and its member databases requested) |
| stock `interpro` | CC0-1.0 | verified | <https://interpro-documentation.readthedocs.io/en/latest/license.html> | 2026-11-20 | yes | none (citation requested) |
| stock `mgi-alleles` | CC-BY-4.0 | verified | <https://www.informatics.jax.org/mgihome/other/copyright.shtml> | 2026-11-20 | yes | attribution (CC BY); images excluded (none used) |
| stock `pubmed-gene` | No restrictions by NCBI (no licence named) | verified | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-20 | yes | as ncbi-gff; the file holds identifiers only |
| stock `humanmine-static` | not verified | not stated | <https://github.com/intermine/humanmine-datasets> | 2026-11-20 | yes (flag only) | unknown: the repository has no LICENSE (README and datasets.xml only; GitHub's licence field is null) |
| stock `update-data-sources` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-20 | yes | attribution to the UniProt Consortium |
| stock `update-publications` | NLM terms and conditions (acknowledge NLM; no endorsement; currency statement) | partial | <https://www.nlm.nih.gov/databases/download/terms_and_conditions.html> | 2026-11-20 | yes | acknowledge "Courtesy of the U.S. National Library of Medicine"; no endorsement; keep data current or say it may not be; E-utilities policy unread (eutils host blocked) |
| stock `entrez-organism` | No restrictions by NCBI (no licence named) | partial | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-20 | yes | as ncbi-gff; E-utilities policy unread (eutils host blocked) |
| stock `ncbi-fasta` | No restrictions by NCBI (no licence named) | verified | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-18 | yes | as ncbi-gff |
| stock `omim` | OMIM licensed download (personal or institutional use only) | not checked | none found | 2026-11-18 | no | licensed copy only (not read today) |
| stock `reactome` | CC0-1.0 | verified | <https://reactome.org/license> | 2026-11-18 | yes | attribution encouraged, not required |
| ID resolver `gene_info` | No restrictions by NCBI | verified | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-18 | yes | as ncbi-gff |
| RDF `go` | CC-BY-4.0 | verified | <https://geneontology.org/docs/go-citation-policy/> | 2026-11-18 | yes | as stock go-annotation |
| RDF `ncbigene` | No restrictions by NCBI (no licence named) | verified | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-18 | yes | as ncbi-gff |
| RDF `reactome` | CC0-1.0 | verified | <https://reactome.org/license> | 2026-11-18 | yes | attribution encouraged, not required |
| RDF `hgnc` | CC0-1.0 | verified | <https://www.genenames.org/about/license/> | 2026-11-18 | yes | none; attribution recommended (Seal et al., NAR; RRID:SCR_002827) |
| RDF `ensembl` | No restrictions by Ensembl (disclaimer); code Apache-2.0 | verified | <https://jun2026.archive.ensembl.org/info/about/legal/disclaimer.html> (the page RDF Portal names, after redirect) | 2026-11-20 | yes | none stated; third-party data in the distribution may carry their own constraints and the user must check them; no warranty |
| RDF `uniprot` | CC-BY-4.0 | verified | <https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/knowledgebase/complete/README> | 2026-11-18 | yes | attribution; say the data were changed |
| RDF `clinvar` | No restrictions by NCBI (general policy); ClinVar's own page unread | partial | <https://www.ncbi.nlm.nih.gov/home/about/policies/> | 2026-11-18 | yes | as ncbi-gff; ClinVar's data-use page is behind NCBI's bot check (retried 2026-11-20, unchanged) |
| RDF `gwascatalog` | EMBL-EBI terms of use (summary statistics CC0) | partial | <https://www.ebi.ac.uk/gwas/docs/about> | 2026-11-18 | yes (flag only) | EMBL-EBI terms; TogoVar's terms are behind a Cloudflare bot check |
| RDF `pubmed` | NLM terms and conditions (free; acknowledge NLM) | verified | <https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/README.txt> | 2026-11-18 | yes | acknowledge NLM; no PubMed logo; state the data may not be current; abstracts may be copyrighted |
| RDF `hpo` | HPO licence | verified | <https://hpo.jax.org/license> | 2026-11-18 | yes | as stock hpo-annotation; the cached group is the whole ontology as tables, nothing left out |
| BlueGenes tools (18 npm packages) | MIT x16, LGPL-3.0 x1, LGPL-2.1 x1 | verified | package.json and LICENSE inside each cached tarball | 2026-11-18 | yes | keep the notices; LGPL text beside the two LGPL tools (protvista has no LICENSE file) |
| `imjs` 4.0.0 | LGPL-3.0 | verified | <https://registry.npmjs.org/imjs/-/imjs-4.0.0.tgz> (LICENCE) | 2026-11-18 | yes | LGPL notice and a pointer to the source |

## What the converters stamp, and what the mine shows

"Converter stamps" is the value hard-coded in the loader (or its project.xml property); "Mine shows" is
`DataSet.licence` in the demo mine on port 18090 as rebuilt on 20 Nov 2026 (27 of its 67 data sets carry one; 18 of 67 before; 2026-11-18 reading through `service/query/results`). The table
below is the state after the rebuild of 20 Nov 2026 (im-9n4.50): the converters of mgi-identifiers, rgd-identifiers,
interpro-go, protein-atlas, protein-atlas-rna, atlas-express, gtex, hpo-annotation and hpo now stamp the licence read at
source, and the stock table passes the licence of go-annotation, uniprot-fasta, ncbi-fasta and ncbi-gff to their
loaders as a project.xml property (`properties` in `stock_sources.yaml`, applied by `rdfc2im project`, phase rdfc2im_project). RDF sources
load through `humanmine-items` and the items carry `data_set_licence` (see "The ten RDF data sets" below). Four stock
converters still stamp nothing and read no property: interpro, protein2ipr, mgi-alleles and pubmed-gene (see the list
after the table).

| Source | Table said before | Converter stamps (file:line) | Mine shows (DataSet.licence) |
|---|---|---|---|
| stock `uniprot` | CC BY 4.0 (UniProt) | http://creativecommons.org/licenses/by/4.0/ (intermine UniprotConverter.java:82) | Swiss-Prot data set, UniProt data set: same URL |
| stock `uniprot-fasta` | CC BY 4.0 (UniProt) | the project.xml property `fasta.licence` (FastaLoaderTask.java:385), now set by the stock table to https://creativecommons.org/licenses/by/4.0/ | uniprot-fasta: https://creativecommons.org/licenses/by/4.0/ |
| stock `uniprot-keywords` | CC BY 4.0 (UniProt) | http://creativecommons.org/licenses/by/4.0/ (UniprotKeywordConverter.java:45) | UniProt data set: same URL (shared with uniprot) |
| stock `ncbi-gff` | public domain (NCBI RefSeq) | the project.xml property `gff3.licence` (GFF3ConverterTask.setLicence), now set by the stock table to https://www.ncbi.nlm.nih.gov/home/about/policies/ | ncbi-gff: the NCBI policy URL |
| stock `go-annotation` | CC BY 4.0 (GO Consortium, GOA) | none: GoConverter.java:113 takes a `licence` property, but the converter makes its DataSet in the constructor (GoConverter.java:104, 146), before the setter runs, and getDataSet then returns that unstamped DataSet; with the property set in project.xml the mine still showed no licence on 20 Nov 2026, so the table sets none. Needs a converter change (build the DataSet when the licence is known, e.g. in `process`) | GO Annotation data set: empty |
| stock `interpro-go` | CC0 (InterPro) | https://creativecommons.org/publicdomain/zero/1.0/ (InterproGoConverter.java:39) | InterPro domain GO annotations: same URL |
| stock `panther` | PANTHER terms of use, free with citation (unverified) | http://www.gnu.org/licenses/gpl.txt (PantherConverter.java:69-70) | Panther orthologue and paralogue predictions: the GPL URL |
| stock `mgi-identifiers` | MGI data are free to use with citation | https://creativecommons.org/licenses/by/4.0/ (MgiIdentifiersConverter.java:37) | Mouse gene identifiers: same URL |
| stock `protein2ipr` | (new 20 Nov) | none (Protein2iprConverter, `super(writer, model, source, dataset)` with no licence; no property read) | InterPro data set: empty. Needs a converter change: CC0 1.0 `https://creativecommons.org/publicdomain/zero/1.0/` |
| stock `interpro` | (new 20 Nov) | none, passes null (InterProConverter `super(..., null, false)`; no property read) | InterPro data set: empty (shared with protein2ipr). Needs a converter change: CC0 1.0 |
| stock `mgi-alleles` | (new 20 Nov) | none (MgiAllelesConverter, 4-argument super; no property read) | mgi-alleles: empty. Needs a converter change: CC BY 4.0 `https://creativecommons.org/licenses/by/4.0/` |
| stock `pubmed-gene` | (new 20 Nov) | none (PubMedGeneConverter, 4-argument super; no property read) | PubMed to gene mapping: empty. Needs a converter change: the NCBI policy URL |
| stock `humanmine-static`, `update-data-sources`, `update-publications`, `entrez-organism` | (new 20 Nov) | no converter sets one: they write items XML and the DataSets of other sources are untouched | no data set of their own |
| stock `rgd-identifiers` | RGD data are free to use with citation (unverified) | https://creativecommons.org/licenses/by/4.0/ (RgdIdentifiersConverter.java:40) | Rat gene identifiers: same URL |
| stock `psi-mi-ontology` | CC BY 4.0 (HUPO-PSI; unverified) | https://creativecommons.org/licenses/by/4.0/ (psi-mi-ontology.properties:10) | PSI Molecular Interactions: same URL |
| stock `psi-intact` | CC BY 4.0 (IntAct, EMBL-EBI) | https://creativecommons.org/licenses/by/4.0/ (PsiConverter.java:83) | IntAct molecular interactions: same URL |
| stock `biogrid` | MIT (BioGRID; unverified) | https://opensource.org/licenses/MIT (BioGridConverter.java:97) | BioGRID interaction data set: same URL |
| stock `protein-atlas` | CC BY 4.0, not share-alike | https://creativecommons.org/licenses/by/4.0/ (humanmine-bio-sources ProteinAtlasConverter.java:53) | The Human Protein Atlas expression profiles: same URL |
| stock `protein-atlas-rna` | CC BY 4.0, not share-alike | https://creativecommons.org/licenses/by/4.0/ (ProteinAtlasRNAConverter.java:40) | Protein Atlas RNA Gene data: same URL |
| stock `gtex` | GTEx Portal Data License | https://www.gtexportal.org/home/license (GtexConverter.java:45) | RNA-Seq Data, Single-Tissue cis-eQTL Data: same URL; "GTEx RNA-Seq Data" (a data set another path makes) stays empty |
| stock `atlas-express` | CC BY 4.0 (Expression Atlas, EMBL-EBI) | https://creativecommons.org/licenses/by/4.0/ (AtlasExpressConverter.java:37) | atlas-express: same URL |
| stock `hpo-annotation` | HPO licence | https://hpo.jax.org/license (HpoConverter.java:80) | hpo-annotation: same URL |
| stock `orphanet` | CC BY 4.0 (Orphanet) | https://creativecommons.org/licenses/by/4.0/ (OrphanetConverter.java:41) | orphanet: same URL |
| stock `reactome` | CC0 (Reactome), written in tools/source_manifest.py | https://creativecommons.org/publicdomain/zero/1.0/ (intermine ReactomeConverter.java:54) | Reactome pathways data set: same URL |
| ID resolver `gene_info` | not recorded | n/a (not a data set) | n/a |
| RDF `go` | not recorded | none: the rdfc2im items carry no DataSet.licence | GO (RDF Portal): empty |
| RDF `ncbigene` | not recorded | none: the rdfc2im items carry no DataSet.licence | NCBI Gene (RDF Portal): empty |
| RDF `reactome` | not recorded | none: the rdfc2im items carry no DataSet.licence | shares "Reactome pathways data set" with stock reactome: empty |
| RDF `hgnc` | not recorded | none: the rdfc2im items carry no DataSet.licence | HGNC identifiers (RDF Portal): empty |
| RDF `ensembl` | not recorded | `https://www.ensembl.org/info/about/legal/disclaimer.html` (the items write `data_set_licence` since 2026-11-20) | Ensembl genes (RDF Portal): empty until the next build |
| RDF `uniprot` | not recorded | none: the rdfc2im items carry no DataSet.licence | UniProtKB, Swiss-Prot and TrEMBL (RDF Portal): empty |
| RDF `clinvar` | not recorded | none: the rdfc2im items carry no DataSet.licence | ClinVar (RDF Portal): empty |
| RDF `gwascatalog` | not recorded | none: the rdfc2im items carry no DataSet.licence | GWAS Catalog (TogoVar): empty |
| RDF `pubmed` | not recorded | none: the rdfc2im items carry no DataSet.licence | PubMed (RDF Portal): empty |
| RDF `hpo` | not recorded | none: the rdfc2im items carry no DataSet.licence | Human Phenotype Ontology (RDF Portal): empty |

## What changed from the earlier record

First pass (17 to 18 Nov, morning), against the table written from general knowledge on 17 Nov:

| Source | Was | Is | Why |
|---|---|---|---|
| protein-atlas, protein-atlas-rna | CC BY-SA 4.0, share-alike | **CC BY 4.0**, not share-alike | proteinatlas.org/about/licence: "licensed under the Creative Commons Attribution 4.0 International License". The share-alike duty the old notice described does not exist. |
| biogrid | MIT (unverified) | MIT, verified | downloads.thebiogrid.org: "under the MIT License" |
| mgi-identifiers | free to use with citation | CC BY 4.0 | informatics.jax.org copyright page: "licensed under a Creative Commons Attribution 4.0 International License (CC-BY)" |
| psi-mi-ontology | CC BY 4.0 (unverified) | CC BY 4.0, verified | the HUPO-PSI/psi-mi-CV repository (where mi.obo comes from) has a CC BY 4.0 LICENSE |
| atlas-express, orphanet, uniprot* | CC BY 4.0 | CC BY 4.0, verified | stated on the sources' pages and files |
| stock reactome | CC0 (hard-coded in the manifest tool) | CC0, now read from other_licences.yaml | reactome.org/license: "All data ... are licensed under the Creative Commons Public Domain Dedication (CC0)" |

Second pass (18 Nov, after the project owner allowed the hosts that blocked the first):

| Source | First pass | Now | Read at |
|---|---|---|---|
| go-annotation, RDF go | GOA notice / CC BY 4.0 from the OBO header, partial | **CC BY 4.0, verified** (GO Consortium page), plus the GOA copyright statement for the EBI files | geneontology.org/docs/go-citation-policy/ |
| psi-intact | not verified | **CC BY 4.0, verified**; Apache-2.0 is for IntAct's software only | the IntAct portal documentation (license-privacy.md) |
| rgd-identifiers | not stated | **CC BY 4.0, verified** | rgd.mcw.edu/wg/disclaimer/ |
| gtex | not stated | **GTEx Portal Data License, verified**: acknowledge, no endorsement, currency statement on redistribution | www.gtexportal.org/home/license (a JavaScript page, read in a browser; the proxy let it through, the redirect target gtexportal.org was not needed) |
| hpo-annotation, RDF hpo | not verified | **HPO licence, verified**: acknowledge and cite, show dates or versions, do not alter content or relationships | hpo.jax.org/license (the old /app/license redirects) |
| interpro-go | not stated | **CC0 1.0, verified** | interpro-documentation.readthedocs.io/en/latest/license.html |
| RDF hgnc | not verified | **CC0, verified** | genenames.org/about/license/ |
| ncbi-gff, ncbi-fasta, gene_info, RDF ncbigene | "unrestricted public data" (FTP notice), partial | **no restrictions by NCBI, verified** (the policy page); no licence is named | ncbi.nlm.nih.gov/home/about/policies/ |
| RDF clinvar | partial | partial: the general NCBI policy is read, ClinVar's own page is behind NCBI's bot check | |
| RDF pubmed | verified | verified; the NLM page RDF Portal names was read and gives the same terms | nlm.nih.gov/databases/download.html |
| panther | not stated | **not stated**: pantherdb.org refuses automated readers; no terms anywhere in the FTP tree | |
| RDF ensembl | not verified | **not verified**: www.ensembl.org now redirects to jun2026.archive.ensembl.org, which is not allowed | |
| RDF gwascatalog | partial | partial: TogoVar's terms are behind a Cloudflare bot check | |

The UniProt (www.uniprot.org/help/license, a JavaScript page that holds no text for a plain client), BioGRID wiki and
NLM web-policies pages add nothing to the verified records (the NLM copyright page says "Please acknowledge NLM as the
source of the information by including the phrase "Courtesy of the National Library of Medicine" or "Source: National
Library of Medicine." for government works on its sites; the PubMed data terms are the ones above).

No `redistributable` flag was changed in either pass: nothing read forbids a copy. What the second pass changed is the
conditions: GTEx and HPO now carry conditions a copy must meet (see the notices), and PANTHER and Ensembl remained
without any stated term (Ensembl was settled in the third pass, below).

## Converter mismatches (for a follow-up in the intermine and humanmine-bio-sources checkouts)

State after the rebuild of 20 Nov 2026 (im-9n4.50): fixed in the converters and seen in the mine: protein-atlas, protein-atlas-rna,
atlas-express, gtex, hpo-annotation (the ontology `hpo` is not loaded by this build), mgi-identifiers, rgd-identifiers, interpro-go;
psi (IntAct) was already right. Set through project.xml: uniprot-fasta and ncbi-gff (seen), ncbi-fasta (the same property; the source is not
in this build). Still to do in a converter: panther (GPL URL, terms unread), go-annotation (the setter runs after the DataSet is made),
and interpro, protein2ipr, mgi-alleles and pubmed-gene (no licence stamped, no property read). The table below is the record
of 18 Nov and keeps its original wording.

Paths: intermine is the `maint-2026` merge worktree (`worktrees/intermine/merge-maint-2026`, `bio/sources/<source>/...`,
which has the IntAct fix 6e1209b48c); humanmine-bio-sources is `repos/humanmine-bio-sources`. Nothing there was edited.
"Value to set" is the licence URL form the converters already use for their CC licences.

| Source | Converter file:line | Stamps today | What the source states | Value to set | Test fixtures that pin the old value |
|---|---|---|---|---|---|
| protein-atlas | humanmine-bio-sources `protein-atlas/.../ProteinAtlasConverter.java:53` | `https://creativecommons.org/licenses/by-sa/3.0/` | CC BY 4.0 | `https://creativecommons.org/licenses/by/4.0/` | `protein-atlas/src/test/resources/ProteinAtlasConverterTest.xml:28` |
| protein-atlas-rna | `protein-atlas-rna/.../ProteinAtlasRNAConverter.java:40` | `by-sa/3.0` | CC BY 4.0 | as above | `protein-atlas-rna/protein-atlas-rna-tgt.xml:50`, `protein-atlas-rna/src/test/resources/ProteinAtlasRNAConverterTest-tgt.xml:23` |
| panther | intermine `panther/.../PantherConverter.java:69-70` | `http://www.gnu.org/licenses/gpl.txt` | nothing found (GPL is a software licence) | none until the terms are read; then remove the GPL URL | `panther/src/test/resources/PantherConverterTest_tgt.xml:25` |
| go-annotation | intermine `go-annotation/.../GoConverter.java:113,146,160` (setter `setLicence`); the property is set in the mine's project.xml, `<source name="go-annotation">` (rdfc2im `in/humanmine_project.xml:93-96`) | none (no `licence` property) | CC BY 4.0 | add `<property name="licence" value="https://creativecommons.org/licenses/by/4.0/"/>` to that source | none |
| mgi-identifiers | intermine `mgi-identifiers/.../MgiIdentifiersConverter.java:43` | none (4-argument super) | CC BY 4.0 | pass `"https://creativecommons.org/licenses/by/4.0/"` as the fifth argument | none (no test target) |
| rgd-identifiers | intermine `rgd-identifiers/.../RgdIdentifiersConverter.java:50` | `null` | CC BY 4.0 | `"https://creativecommons.org/licenses/by/4.0/"` instead of `null` | none |
| interpro-go | intermine `interpro-go/.../InterproGoConverter.java:48` | `null` | CC0 1.0 | `"https://creativecommons.org/publicdomain/zero/1.0/"` instead of `null` | none |
| gtex | humanmine-bio-sources `gtex/.../GtexConverter.java:55` | none (`super(writer, model, null, null)`; the data source and data set names are null too) | GTEx Portal Data License | `https://www.gtexportal.org/home/license` as the licence; needs the data source and data set names filled in as well | `gtex/src/test/resources/GtexConverterTest_tgt.xml` has no licence |
| atlas-express | `atlas-express/.../AtlasExpressConverter.java:53` | none | CC BY 4.0 | `https://creativecommons.org/licenses/by/4.0/` as a fifth argument | none |
| psi (IntAct) | intermine `psi/.../PsiConverter.java:80-83` | already `https://creativecommons.org/licenses/by/4.0/` (fixed in 6e1209b48c) | CC BY 4.0, as stated | none | `psi/src/test/resources/PsiConverterTest_tgt.xml:20` and `PsiConverterTest.java:96` already expect the new value |
| hpo-annotation | humanmine-bio-sources `hpo-annotation/.../HpoConverter.java:80` | `https://hpo.jax.org/app/license` (redirects to /license) | HPO licence page is now `https://hpo.jax.org/license` | `https://hpo.jax.org/license` | `hpo-annotation/src/test/resources/HpoConverterOboTest_tgt.xml:92` |
| hpo (ontology) | humanmine-bio-sources `hpo/hpo.properties:17` | `obo.ontology.licence = https://hpo.jax.org/app/license` | as above | `https://hpo.jax.org/license` | none found |
| uniprot-fasta | intermine `fasta/.../FastaLoaderTask.java:385` (setter `setLicence`, 159) | none unless the mine's project.xml sets `licence` | CC BY 4.0 | add the `licence` property `https://creativecommons.org/licenses/by/4.0/` to the uniprot-fasta source in project.xml | none |
| ncbi-gff, ncbi-fasta | mine's project.xml (the GFF3 loader's DataSet has no licence; the fasta loader takes the `licence` property as above) | none | no restrictions by NCBI; no licence named | `https://www.ncbi.nlm.nih.gov/home/about/policies/` (the policy page, since there is no licence text) | none |

They agree with the source (cosmetic differences only): UniprotConverter.java:82, UniprotKeywordConverter.java:45 (both
`http://creativecommons.org/licenses/by/4.0/`, http not https; `uniprot/src/test/resources/UniprotConverterTest_tgt.xml` and
`uniprot-keywords/src/test/resources/UniprotKeywordImporterTest_tgt.xml:20` pin the http form), BioGridConverter.java:97
(MIT; BioGridConverterTest_tgt.xml), OrphanetConverter.java:41 (CC BY 4.0), ReactomeConverter.java:54 (CC0;
ReactomeConverterTest_tgt.xml), psi-mi-ontology.properties:10 (CC BY 4.0). `uberon.properties:17` says CC BY 3.0 and
`go.properties:6`, `mammalian-phenotype-ontology.properties:17` CC BY 4.0; they are not in the demo and were not checked.

### The ten RDF data sets

rdfc2im's `emit_items` (`rdfc2im/items.py`, the DataSource/DataSet block near the end of the function) writes the
DataSet item for every RDF source. It now reads the optional key `data_set_licence` of the source in
`rdfc2im/data/sources.yaml` and writes it as `DataSet.licence` (added after the DataSet is made, so the DataSet's key
stays its name; `tests/test_items.py::test_data_set_gets_the_upstream_licence_when_the_source_config_declares_one`).
Set for nine sources: ensembl (added 2026-11-20, third pass), ncbigene and clinvar (NCBI policy page), hgnc and reactome (CC0), uniprot and go (CC BY 4.0),
hpo (`https://hpo.jax.org/license`), pubmed (NLM's download page). Not set for gwascatalog
(partial; TogoVar's terms unread). Effect: the demo mine shows these only after the next build with this code; the
reactome data set is shared with stock reactome, which stamps the same CC0 URL.

Third pass (20 Nov, after the project owner allowed the Ensembl archive host):

| Source | Second pass | Now | Read at |
|---|---|---|---|
| RDF `clinvar` | partial | **still partial**: retried 2026-11-20, the data-use page still answers with NCBI's "Checking your browser" page; the ClinVar FTP README holds no terms | https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/ (bot check), https://ftp.ncbi.nlm.nih.gov/pub/clinvar/README.txt |
| RDF ensembl | not verified | **verified: "Ensembl imposes no restrictions on access to, or use of, the data provided and the software used to analyse and present it. Ensembl data generated by members of the project are available without restriction."** Third-party data may carry constraints; code is Apache 2.0 | https://jun2026.archive.ensembl.org/info/about/legal/disclaimer.html (www.ensembl.org redirects there); the legal index and RDF Portal's data set page (Ensembl version 115, issued 2026-02-27, licence given as `http://ensembl.org/info/about/legal/disclaimer.html`) |

## Sources not verified, and what would settle them

| Source | Why not | What would settle it |
|---|---|---|
| stock `panther` | www.pantherdb.org answers curl with Cloudflare's "Just a moment" page and a headless browser times out; pantherdb.org (no www) fails the certificate check through the proxy; no LICENSE or README with terms in the data.pantherdb.org/ftp tree (about 14 directories listed) | a person reads https://www.pantherdb.org/tou.jsp in an ordinary browser and pastes the wording (no sbx rule helps) |
| stock `humanmine-static` | nothing states a licence: the repository intermine/humanmine-datasets has only README.md ("# humanmine-datasets to store datasets.xml") and datasets.xml; GitHub's licence field is null | the InterMine maintainers say how the descriptive text may be reused |
| stock `update-publications`, `entrez-organism` (E-utilities terms) | eutils.ncbi.nlm.nih.gov answers HTTP 403 "Approval required" from the sandbox, and the E-utilities usage policy (NBK25497) is behind a reCAPTCHA page | `sbx policy allow network eutils.ncbi.nlm.nih.gov` for the loader itself; a person reads https://www.ncbi.nlm.nih.gov/books/NBK25497/ in a browser for the policy |
| RDF `gwascatalog` (TogoVar's terms) | togovar.org answers with a Cloudflare bot check, plain client and headless browser alike | a person reads https://togovar.org/doc/terms in a browser; the GWAS Catalog's own EMBL-EBI terms are read |
| RDF `clinvar` (ClinVar's own page) | www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/ answers with a reCAPTCHA page ("Checking your browser before accessing www.ncbi.nlm.nih.gov") | a person reads the page in a browser; NCBI's general policy (read) already says no restrictions |

None of these needs more than the one command or a person's reading. The bot checks were not worked around.

## Sources not loaded yet

Record: `rdfc2im/data/planned_sources.yaml` (nothing reads it: `stock_sources.yaml` lists only sources the build
fetches, so a known-but-unbuilt source would have been fetched there).

### depmap (third pass, 2026-11-20): licence NOT read, status not-verified

* **What HumanMine loaded.** Two stock sources, not three (`repos/humanmine-bio-sources` has `depmap-expression` and
  `depmap-sample-info` only; `repos/humanmine/project.xml` lines 189-193 load both from `/micklem/data/human/depmap`,
  version 4.3.0). `depmap-expression` reads `CCLE_expression.csv` (cell lines in rows, genes in columns, the gene symbol
  taken as the first word of each header; one `DepMapExpression` item per value). `depmap-sample-info` reads `sample_info.csv` (columns
  `DepMap_ID`, `cell_line_name`, `stripped_cell_line_name`, `CCLE_Name`, ..., `primary_disease`, `Subtype`, `age`,
  `Sanger_Model_ID`, `lineage` ...; one `CellLine` item per row). The converters were written on 2021-10-06 to 2021-11-11
  (DepMap's 2021 releases; the repository names no release).
* **What was read.** `https://depmap.org/portal/` (home page, plain client): the current release is **26Q3**, "DepMap
  releases data bi-annually", highlights include updates to the CRISPR pipeline and the mutation dataset. Its footer
  links "Terms & Conditions" (`/portal/terms/`), but every deeper page (terms, data page, download index API, release
  notes) answers with a Cloudflare Turnstile check: "We're verifying you're a person, not a bot ... Need DepMap data in
  bulk? You're always welcome to grab everything from the downloads section - please don't scrape the portal."
  The check was not worked around. WebFetch got the same page.
* **Not read, so not recorded:** the licence name and wording, attribution text, any non-commercial or redistribution
  clause, per-data-set exceptions (Sanger, drug screens), current file names and sizes of `CCLE_expression.csv` and
  `sample_info.csv` (the 26Q3 file names were not checked),
  and whether the old names still exist. Earlier secondary sources said CC BY 4.0: not recorded as the licence.
* **Hosts not allowed:** `forum.depmap.org` (the 26Q3 announcement), `api.figshare.com` and `figshare.com` (the
  releases' archive record, which states a licence per item).
* **Recommendation: unclear, needs the owner's decision (do not wire it in yet).** Nothing at source was read, and the
  portal asks automated clients to use the downloads section. A person reads https://depmap.org/portal/terms/ and the
  data page's release README in a browser and pastes the licence line and the 26Q3 file list; then it can be
  decided. The old converters also read 2021 file layouts, so they would need rework whatever the licence says.
  `redistributable` is recorded false until then.

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
* RGD (rgd-identifiers): CC BY 4.0, credit the Rat Genome Database, link the licence, say if changed; cite as RGD asks
  ("RGD [species and datatype] Download file, Rat Genome Database Web Site, Medical College of Wisconsin, Milwaukee,
  Wisconsin. World Wide Web (URL: http://rgd.mcw.edu/). [date retrieved]"; RRID:SCR_006444).
* IntAct (psi-intact): CC BY 4.0, "appropriate credit"; the publications to cite are listed on
  https://www.ebi.ac.uk/intact/about#publications.
* BioGRID (biogrid): MIT; keep the notice. Requested: cite Stark C et al., BioGRID: a general repository for interaction
  datasets, Nucleic Acids Res 2006;34:D535-9.
* PSI-MI controlled vocabulary (psi-mi-ontology): CC BY 4.0, credit HUPO-PSI.
* GO (go-annotation, RDF go): CC BY 4.0. Say which GO release the data come from (date, optionally the Zenodo DOI) and
  give the notice, for example "Gene Ontology data from the [date] release is made available under the terms of the CC
  BY 4.0 license" with a link to the licence; cite Ashburner et al. 2000 and the GO Consortium's 2026 knowledgebase
  paper in publications. For the GOA files also reproduce "GOA - GO Annotation. Copyright 2018 (C) The European
  Bioinformatics Institute."
* GTEx (gtex): acknowledge the GTEx Portal in a clear and conspicuous manner with "The data used for the analyses
  described in this manuscript were obtained from: [insert, where appropriate] the GTEx Portal on MM/DD/YY and/or dbGaP
  accession number phs000424.vN.pN on MM/DD/YYYY."; do not imply endorsement; the v8 median TPM are not the most
  current GTEx data, so say so clearly.
* HPO (hpo-annotation, RDF hpo): acknowledge and cite the Human Phenotype Ontology Consortium; show the date or
  version of each HPO file displayed; do not alter the files' content or relationships; add "This service/product
  uses the Human Phenotype Ontology (version information). Find out more at http://www.human-phenotype-ontology.org"
  (the HPO logo is requested).
* InterPro (interpro-go): CC0; citing InterPro and its member databases is requested.
* HGNC (RDF hgnc): CC0; attribution recommended ("Genenames.org: the HGNC and PGNC resources in 2026", Nucleic Acids
  Research; or HGNC, RRID:SCR_002827).
* PubMed (RDF pubmed): acknowledge NLM as the source "in a clear and conspicuous manner"; do not use the PubMed
  wordmark or logo or imply NLM, NIH or HHS endorsement; the data are a snapshot, so say that they may not reflect the
  most current data from NLM; some abstracts may be copyrighted.
* NCBI (ncbi-gff, ncbi-fasta, gene_info, RDF ncbigene, clinvar): no restrictions by NCBI; acknowledge NCBI/NLM as
  the source; some records may carry rights claimed by their submitters, which NCBI cannot waive.
* Ensembl (RDF ensembl): the disclaimer imposes no restriction and asks for no attribution wording. Name Ensembl (via
  RDF Portal, Ensembl release 115) as the source; the disclaimer says some data in the distribution may be subject to
  third-party constraints, which the user must establish.
* Reactome: CC0, no attribution required (given as courtesy). GWAS Catalog: cite the GWAS Catalog; EMBL-EBI terms apply.
* Software shown to users: imjs (LGPL-3.0) and the two LGPL BlueGenes tools (cytoscape-interaction-network-viewer
  LGPL-3.0, protvista LGPL-2.1) need their licence text and a pointer to the source available.

## Release assets (second pass, 18 Nov)

The three archives, on the terms as now read. The notices are `docs/LICENCES-stock-filtered.txt` and
`docs/LICENCES-panel-cache.txt`. Nothing was built, uploaded or edited.

* `stock_filtered-2026-11-18.tar.gz` (13 groups, not published): **may be published without `stock-panther`**, with
  the corrected notice `docs/LICENCES-stock-filtered.txt` replacing the `LICENCES-stock-filtered.txt` inside it (the one
  inside says CC BY-SA for the Human Protein Atlas and lists four groups as unverified). Twelve groups rest on
  verified statements: uniprot, uniprot-fasta, mgi-identifiers, biogrid, protein-atlas, protein-atlas-rna,
  atlas-express, go-annotation, ncbi-gff, psi-intact, gtex, hpo-annotation. Leave out `stock-panther` (PANTHER's terms
  were not readable). Two carry conditions the notice states: `stock-gtex` must say it may not be the current GTEx
  data, and `stock-hpo-annotation` is a gene-panel subset of HPO files whose licence says content must not be
  altered; the rows are unchanged, but the project owner has to accept that reading (or drop the group).
* `cached_raw_data_allgenes-2026-11-18.tar.gz` (not published): **may be published**: `ncbigene` (no restrictions by
  NCBI) and `hgnc` (CC0) are both verified. It needs a short notice (NCBI acknowledgement and the rights caveat; HGNC
  attribution recommended); the text is the ncbigene and hgnc entries of `docs/LICENCES-panel-cache.txt`.
* release `demo-data-2026-11-18` on gmicklem/rdfc2im (the 16-group panel cache): **may stay published**, and it has
  had no notice file so far: add `docs/LICENCES-panel-cache.txt` to it. Two things for the project owner: the
  `ensembl` group's terms are now read (third pass, 2026-11-20: no restrictions, see the table), and `hpo` is the whole ontology as tables (HPO's no-alteration condition: nothing left out
  or changed, a reading to accept). `clinvar` and `gwascatalog` are partial (the owner's pages are behind bot checks;
  the general NCBI policy and the EMBL-EBI terms say no further restriction). If any of these three is not
  acceptable, withdraw that group and re-upload the asset without it.

## Refreshing this record

Read the source's own statement, then change the YAML (not this file): set `licence_checked`, `licence_url`,
`licence_quote`, `licence_status`. `tests/test_stock.py::test_every_source_has_a_complete_licence_record` checks that
every source has a complete record, and the tests of `tools/source_pages.py` show it on the pages. The pages for a
build come from `tools/source_manifest.py` and `tools/source_pages.py` (USAGE.md, "Data-source status pages"). The
tables above are a snapshot of the YAML at 2026-11-18 (second pass); the milestone 3 sources (protein2ipr to entrez-organism) were read on 2026-11-20 [im-9n4.27].
