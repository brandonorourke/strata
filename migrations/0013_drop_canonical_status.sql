-- Drop status column from canonical_entities (confirmation is derived from confirmed_domain)

ALTER TABLE public.canonical_entities
    DROP COLUMN IF EXISTS status;
