-- Add extracted_entities and extracted_events tables for LLM extraction pipeline

CREATE TABLE IF NOT EXISTS public.extracted_entities (
    id integer NOT NULL,
    canonical_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    created_from text NOT NULL DEFAULT 'news',
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.extracted_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.extracted_entities_id_seq OWNED BY public.extracted_entities.id;
ALTER TABLE ONLY public.extracted_entities ALTER COLUMN id SET DEFAULT nextval('public.extracted_entities_id_seq'::regclass);

ALTER TABLE ONLY public.extracted_entities
    ADD CONSTRAINT extracted_entities_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.extracted_entities
    ADD CONSTRAINT extracted_entities_legal_name_normalized_key UNIQUE (legal_name_normalized);

CREATE INDEX IF NOT EXISTS ix_extracted_entities_id ON public.extracted_entities USING btree (id);

CREATE TABLE IF NOT EXISTS public.extracted_events (
    id integer NOT NULL,
    article_id integer NOT NULL,
    entity_id integer NOT NULL,
    canonical_company_name text NOT NULL,
    is_primary_entity boolean DEFAULT false NOT NULL,
    event_type text,
    transaction_role text,
    event_date date,
    event_description text,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS public.extracted_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.extracted_events_id_seq OWNED BY public.extracted_events.id;
ALTER TABLE ONLY public.extracted_events ALTER COLUMN id SET DEFAULT nextval('public.extracted_events_id_seq'::regclass);

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.news_articles(id);

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.extracted_entities(id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_events_article_entity ON public.extracted_events USING btree (article_id, entity_id);
CREATE INDEX IF NOT EXISTS ix_extracted_events_id ON public.extracted_events USING btree (id);
CREATE INDEX IF NOT EXISTS ix_extracted_events_entity_id_created_at ON public.extracted_events USING btree (entity_id, created_at);
