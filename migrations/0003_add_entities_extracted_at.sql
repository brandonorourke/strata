-- Track whether entities extraction has run for an article

ALTER TABLE public.news_articles
    ADD COLUMN IF NOT EXISTS entities_extracted_at timestamp with time zone;
