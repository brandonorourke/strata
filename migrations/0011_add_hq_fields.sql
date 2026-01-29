-- Add HQ fields and entity_type to support provisional clustering

ALTER TABLE public.extracted_entities
    ADD COLUMN IF NOT EXISTS hq_country text,
    ADD COLUMN IF NOT EXISTS hq_region text;

ALTER TABLE public.canonical_entities
    ADD COLUMN IF NOT EXISTS entity_type text,
    ADD COLUMN IF NOT EXISTS hq_country text,
    ADD COLUMN IF NOT EXISTS hq_region text;
