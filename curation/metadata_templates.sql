-- Metadata templates [im-9n4.60]: public templates about the mine's own data, in the BlueGenes category
-- "Metadata" (tag im:aspect:Metadata; BlueGenes makes a category of every im:aspect:<Name> tag it finds on a
-- public template, nothing is defined mine-side). One so far:
--
--   All_data_sources  "All data sources": every DataSet with its DataSource, version, description, url, licence
--                     and the paper its source asks to be cited (first author, year, title, PubMed id), sorted by
--                     data set name. The publication and the data source are outer joins, so every DataSet shows,
--                     one without a citation and one without a DataSource too ("modMine gene flanking regions",
--                     made by InterMine's flanking-regions postprocess, has none); licence, version, description
--                     and url are DataSet attributes (empty when unset). The sort cannot be by data source: a sort
--                     path must be in the root outer join group, which DataSet.dataSource.name no longer is (the
--                     same holds for a click on that column in the results table). The one editable constraint InterMine
--                     requires is DataSet.name = * (every data set; = with a wildcard is a case-insensitive LIKE).
--                     The BlueGenes home page links it (curation/rdfc2im.web.properties).
--
-- Applied by tools/full-build.sh phase apply_templates on every build, after demo_public_templates.sql, into the
-- userprofile database (savedtemplatequery + tag, owned by the superuser 1000001 as the stock templates are).
-- Unlike demo_public_templates.sql it can run again: it deletes its own templates and their tags first, so it
-- can also be applied to a mine that is already built:
--
--   docker exec -i <prefix>-postgres psql -U intermine -d humanmine-userprofile < curation/metadata_templates.sql
--   docker restart <prefix>-mine <prefix>-bluegenes   # the webapp reads its templates at startup
--
-- Ids: its own batch of the userprofile 'serial' sequence (see demo_public_templates.sql), template +1, tags +101..
\set ON_ERROR_STOP on
SELECT nextval('serial') * 1000000 AS idbase \gset

BEGIN;
DELETE FROM tag WHERE type = 'template' AND objectidentifier = 'All_data_sources' AND userprofileid = 1000001;
DELETE FROM savedtemplatequery WHERE templatequery LIKE '<template name="All_data_sources" %' AND userprofileid = 1000001;

INSERT INTO savedtemplatequery (id, templatequery, userprofileid) VALUES (:idbase + 1, '<template name="All_data_sources" title="All data sources" comment="" dataTypes="java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String java.lang.String java.lang.Integer java.lang.String java.lang.String"><query name="All_data_sources" model="genomic" view="DataSet.dataSource.name DataSet.name DataSet.version DataSet.description DataSet.url DataSet.licence DataSet.publication.firstAuthor DataSet.publication.year DataSet.publication.title DataSet.publication.pubMedId" longDescription="Every data set in this mine with its data source, the version loaded, a description, its web page, its licence and the paper the source asks you to cite. Leave the data set name as * for all of them, or type a name (* is a wildcard)." sortOrder="DataSet.name asc"><join path="DataSet.publication" style="OUTER"/><join path="DataSet.dataSource" style="OUTER"/><constraint path="DataSet.name" code="A" editable="true" description="Data set name (* for every data set)" op="=" value="*"/></query></template>', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 101, 'All_data_sources', 'template', 'im:public', 1000001);
INSERT INTO tag (id, objectidentifier, type, tagname, userprofileid) VALUES (:idbase + 102, 'All_data_sources', 'template', 'im:aspect:Metadata', 1000001);
COMMIT;
