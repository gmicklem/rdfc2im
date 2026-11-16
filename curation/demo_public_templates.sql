-- Six public templates for the 113-gene food/drug-metabolism demo panel, added on top of the
-- 3 stock HumanMine templates that survive "reducing a mine" (see LOAD-TRIAL.md) because they
-- only reference classes/fields this build actually loads (Gene, Protein, Organism).
--
-- These live ONLY in the running mine's userprofile database (savedtemplatequery + tag tables,
-- owned by the superuser account, same as every stock template) - there is no InterMine template
-- config file this build writes them into, so they do NOT survive a fresh `dbmodel:builddb` or
-- a userprofile volume wipe (they DO survive `docker compose down`/`up`, which keeps volumes).
-- Re-apply after a fresh build with:
--
--   docker exec -i rdfc2im-postgres psql -U intermine -d humanmine-userprofile \
--       < curation/demo_public_templates.sql
--   docker restart rdfc2im-mine   # the webapp caches its template list at startup
--
-- Ids come from a batch reserved on the userprofile database's own 'serial' sequence (one
-- nextval reserves ids nextval*1000000+1 .. +1000000 for this script, exactly as InterMine's
-- ObjectStoreInterMineImpl.getSerialWithConnection does), templates at +1..+6 and tags at
-- +101..+106. Hardcoded ids (2000001.. before im-jqz.55) were in the batch the webapp itself
-- took next, so the first list saved through the web service got id 2000001 as well and the
-- webapp failed to start (ClassCastException in ProfileManager.wrapUserProfile).
-- Re-running this file adds a second copy of the templates: DELETE them first.
\set ON_ERROR_STOP on
SELECT nextval('serial') * 1000000 AS idbase \gset

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 1, '<template name="GOTerm_Structure" title="GO term hierarchy: term to parent terms" comment="" dataTypes="java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String"><query name="GOTerm_Structure" model="genomic" view="GOTerm.identifier GOTerm.name GOTerm.namespace GOTerm.parents.identifier GOTerm.parents.name" longDescription="" sortOrder="GOTerm.identifier asc"><constraint path="GOTerm.identifier" editable="true" description="GOTerm.identifier" op="=" value="GO:0000016"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 101, 'GOTerm_Structure', 'template', 'im:public', 1000001);

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 2, '<template name="Gene_MultiSource_Identifiers" title="Gene identifiers across NCBI, Ensembl and HGNC" comment="" dataTypes="java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String"><query name="Gene_MultiSource_Identifiers" model="genomic" view="Gene.primaryIdentifier Gene.secondaryIdentifier Gene.symbol Gene.name Gene.chromosome.primaryIdentifier Gene.organism.taxonId" longDescription="" sortOrder="Gene.primaryIdentifier asc"><constraint path="Gene.symbol" editable="true" description="Gene.symbol" op="=" value="CYP2D6"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 102, 'Gene_MultiSource_Identifiers', 'template', 'im:public', 1000001);

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 3, '<template name="Gene_UniProt_Proteins" title="Gene to UniProt protein records" comment="" dataTypes="java.lang.String java.lang.String java.lang.Double"><query name="Gene_UniProt_Proteins" model="genomic" view="Gene.symbol Gene.proteins.primaryAccession Gene.proteins.molecularWeight" longDescription="" sortOrder="Gene.symbol asc"><constraint path="Gene.symbol" editable="true" description="Gene.symbol" op="=" value="VKORC1"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 103, 'Gene_UniProt_Proteins', 'template', 'im:public', 1000001);

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 4, '<template name="Gene_ClinVar_Alleles" title="Gene to ClinVar allele records" comment="" dataTypes="java.lang.String java.lang.String java.lang.String java.lang.String"><query name="Gene_ClinVar_Alleles" model="genomic" view="Gene.symbol Gene.alleles.primaryIdentifier Gene.alleles.type Gene.alleles.clinicalSignificance" longDescription="" sortOrder="Gene.symbol asc"><constraint path="Gene.symbol" editable="true" description="Gene.symbol" op="=" value="DPYD"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 104, 'Gene_ClinVar_Alleles', 'template', 'im:public', 1000001);

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 5, '<template name="GWASResult_AssociatedGene" title="GWAS associations for a gene" comment="" dataTypes="java.lang.String java.lang.String java.lang.Double java.lang.String"><query name="GWASResult_AssociatedGene" model="genomic" view="GWASResult.associatedGenes.symbol GWASResult.phenotype GWASResult.pValue GWASResult.SNP.primaryIdentifier" longDescription="" sortOrder="GWASResult.associatedGenes.symbol asc"><constraint path="GWASResult.associatedGenes.symbol" editable="true" description="GWASResult.associatedGenes.symbol" op="=" value="ABCB1"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 105, 'GWASResult_AssociatedGene', 'template', 'im:public', 1000001);

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 6, '<template name="Gene_Publications" title="Gene to cited publications" comment="" dataTypes="java.lang.String java.lang.String java.lang.String"><query name="Gene_Publications" model="genomic" view="Gene.symbol Gene.publications.pubMedId Gene.publications.title" longDescription="" sortOrder="Gene.symbol asc"><constraint path="Gene.symbol" editable="true" description="Gene.symbol" op="=" value="TPMT"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 106, 'Gene_Publications', 'template', 'im:public', 1000001);

-- Two of HumanMine's own stock templates (ids 1000082/1000084, both from before this session,
-- not the 6 new ones above) defaulted their editable Protein.organism.name constraint to
-- "Plasmodium falciparum 3D7" - a leftover from HumanMine's full stock template set, meaningless
-- once "reducing a mine" (see LOAD-TRIAL.md) leaves only human data. Running either with no
-- override returned zero results, which reads as broken rather than "wrong default organism"
-- to anyone trying the demo. Repointed at this mine's own Organism.name string (verified live:
-- `select distinct name from organism` returns exactly "Homo sapiens", not e.g. "H. sapiens").
UPDATE savedtemplatequery SET templatequery = replace(templatequery, 'Plasmodium falciparum 3D7', 'Homo sapiens')
    WHERE id IN (1000082, 1000084);
