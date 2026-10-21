-- SRA_METADATA (native bucket; actual cohort below is this INTERSECTED with
-- jattr_criteria=['IBD diagnosis','calprotectin measurement'], jattr_combinator=all,
-- sql_jattr_combinator=intersect -- the jattr resolution is not expressible as flat SQL)
SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' AND (array_to_string(biosamplemodel_sam, ' ') ILIKE '%fecal%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%gut%');