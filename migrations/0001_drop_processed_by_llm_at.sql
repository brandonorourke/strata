alter table news_articles
drop column processed_by_llm_at,
add column llm_raw jsonb;
