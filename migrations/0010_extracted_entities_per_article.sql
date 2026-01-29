-- Move extracted_entities to per-article mentions
-- NOTE: This migration assumes extracted_entities/extracted_events/entity_links/canonical_entities
-- have been truncated or are safe to lose, since article_id is required.

ALTER TABLE public.extracted_entities
    ADD COLUMN IF NOT EXISTS article_id integer NOT NULL;

ALTER TABLE public.extracted_entities
    ADD CONSTRAINT extracted_entities_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.news_articles(id);

ALTER TABLE public.extracted_entities
    DROP CONSTRAINT IF EXISTS extracted_entities_legal_name_normalized_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_entities_article_legal
    ON public.extracted_entities (article_id, legal_name_normalized);
