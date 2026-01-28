-- Rename canonical_* columns to extracted_name after 0002 was applied

ALTER TABLE public.extracted_entities
    RENAME COLUMN canonical_name TO extracted_name;

ALTER TABLE public.extracted_events
    RENAME COLUMN canonical_company_name TO extracted_name;
