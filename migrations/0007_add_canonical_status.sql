-- Add status to canonical_entities and backfill based on jurisdiction

ALTER TABLE public.canonical_entities
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'provisional';

UPDATE public.canonical_entities
SET status = 'confirmed'
WHERE jurisdiction IS NOT NULL
  AND status = 'provisional';
