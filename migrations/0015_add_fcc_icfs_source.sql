-- Add FCC ICFS source to news_source_enum

ALTER TYPE public.news_source_enum ADD VALUE IF NOT EXISTS 'FCC_ICFS';
