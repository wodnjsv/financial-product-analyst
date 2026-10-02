\set ON_ERROR_STOP on
\set dataset 'personal-2026-08-24-v1'
BEGIN READ ONLY;
SET LOCAL ROLE fa_runtime;
SET LOCAL statement_timeout = '30s';

-- Four product families, with the original snapshot dates preserved.
SELECT product_family, count(*) AS products
FROM catalog.product WHERE dataset_version = :'dataset'
GROUP BY product_family ORDER BY product_family;

-- Change the keyword to inspect a retained product name.
SELECT p.product_family, e.entity_id, e.canonical_name
FROM catalog.product p JOIN catalog.entity e USING (dataset_version, entity_id)
WHERE p.dataset_version = :'dataset' AND e.canonical_name ILIKE '%TIGER%'
ORDER BY e.canonical_name, e.entity_id LIMIT 10;

-- Which products have sampled holdings? Missing from this list means
-- outside this sample, not proof that the product holds nothing.
SELECT p.product_family, e.canonical_name, count(*) AS holdings
FROM relation.relation_record r
JOIN catalog.product p ON p.dataset_version=r.dataset_version AND p.entity_id=r.subject_id
JOIN catalog.entity e ON e.dataset_version=r.dataset_version AND e.entity_id=r.subject_id
WHERE r.dataset_version=:'dataset' AND r.predicate_id='holdsSecurity'
GROUP BY p.product_family, e.canonical_name, e.entity_id
ORDER BY p.product_family, e.canonical_name LIMIT 15;

-- Inspect an observed value together with its exact source locator.
SELECT p.canonical_name, o.metric_id, o.numeric_value, o.text_value,
       o.value_status, o.applicable_date, er.locator_uri_or_object_key,
       er.locator_sheet, er.locator_row, er.locator_column
FROM observation.observation_record o
JOIN catalog.entity p ON p.dataset_version=o.dataset_version AND p.entity_id=o.entity_id
JOIN evidence.evidence_observation_origin eo
  ON eo.dataset_version=o.dataset_version AND eo.observation_id=o.observation_id
JOIN evidence.evidence_record er
  ON er.dataset_version=eo.dataset_version AND er.evidence_id=eo.evidence_id
WHERE o.dataset_version=:'dataset' AND p.canonical_name ILIKE '%TIGER%'
ORDER BY p.entity_id, o.metric_id LIMIT 10;

-- Local document keyword search requires no model/API.
SELECT d.document_title, c.section_path, left(c.exact_text, 250) AS excerpt
FROM document.document_chunk c
JOIN document.document_record d USING (dataset_version, document_id)
WHERE c.dataset_version=:'dataset' AND c.exact_text LIKE '%위험%'
ORDER BY d.document_id, c.chunk_id LIMIT 5;

-- Check nearest chunks using one stored vector: this tests pgvector locally
-- without generating a new query embedding or spending API credits.
WITH anchor AS (
    SELECT embedding_id, embedding FROM search.document_embedding
    WHERE dataset_version=:'dataset' ORDER BY embedding_id LIMIT 1
)
SELECT v.document_id, v.chunk_id,
       v.embedding OPERATOR(cdb_admin.<=>) a.embedding AS cosine_distance
FROM search.document_embedding v CROSS JOIN anchor a
WHERE v.dataset_version=:'dataset' AND v.embedding_id<>a.embedding_id
ORDER BY cosine_distance, v.embedding_id LIMIT 5;
ROLLBACK;
