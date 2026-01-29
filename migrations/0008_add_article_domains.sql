-- Store candidate domains found in article raw_html

CREATE TABLE IF NOT EXISTS public.article_domains (
    id integer NOT NULL,
    article_id integer NOT NULL,
    domain text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS public.article_domains_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.article_domains_id_seq OWNED BY public.article_domains.id;
ALTER TABLE ONLY public.article_domains ALTER COLUMN id SET DEFAULT nextval('public.article_domains_id_seq'::regclass);

ALTER TABLE ONLY public.article_domains
    ADD CONSTRAINT article_domains_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.article_domains
    ADD CONSTRAINT article_domains_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.news_articles(id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_article_domains_article_domain ON public.article_domains USING btree (article_id, domain);
CREATE INDEX IF NOT EXISTS ix_article_domains_id ON public.article_domains USING btree (id);
CREATE INDEX IF NOT EXISTS ix_article_domains_article_id ON public.article_domains USING btree (article_id);
