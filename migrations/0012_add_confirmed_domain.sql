-- Add confirmed_domain to canonical_entities

ALTER TABLE public.canonical_entities
    ADD COLUMN IF NOT EXISTS confirmed_domain text;
