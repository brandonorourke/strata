-- Add granular SEC sources to news_source_enum

ALTER TYPE public.news_source_enum ADD VALUE IF NOT EXISTS 'SEC_PRESS_RELEASES';
ALTER TYPE public.news_source_enum ADD VALUE IF NOT EXISTS 'SEC_LITIGATION_RELEASES';
ALTER TYPE public.news_source_enum ADD VALUE IF NOT EXISTS 'SEC_ADMIN_PROCEEDINGS';
