-- Track domain extraction per article

ALTER TABLE public.news_articles
    ADD COLUMN IF NOT EXISTS domains_extracted_at timestamp with time zone;
