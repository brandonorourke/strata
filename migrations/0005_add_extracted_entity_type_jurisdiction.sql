-- Add entity_type and jurisdiction to extracted_entities

ALTER TABLE public.extracted_entities
    ADD COLUMN IF NOT EXISTS entity_type text,
    ADD COLUMN IF NOT EXISTS jurisdiction text;
