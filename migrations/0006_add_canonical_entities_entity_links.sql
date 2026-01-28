-- Add canonical_entities and entity_links for conservative canonicalization

CREATE TABLE IF NOT EXISTS public.canonical_entities (
    id integer NOT NULL,
    canonical_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    jurisdiction text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS public.canonical_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.canonical_entities_id_seq OWNED BY public.canonical_entities.id;
ALTER TABLE ONLY public.canonical_entities ALTER COLUMN id SET DEFAULT nextval('public.canonical_entities_id_seq'::regclass);

ALTER TABLE ONLY public.canonical_entities
    ADD CONSTRAINT canonical_entities_pkey PRIMARY KEY (id);

CREATE INDEX IF NOT EXISTS ix_canonical_entities_id ON public.canonical_entities USING btree (id);

CREATE TABLE IF NOT EXISTS public.entity_links (
    id integer NOT NULL,
    extracted_entity_id integer NOT NULL,
    canonical_entity_id integer NOT NULL,
    link_confidence double precision,
    link_method text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS public.entity_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.entity_links_id_seq OWNED BY public.entity_links.id;
ALTER TABLE ONLY public.entity_links ALTER COLUMN id SET DEFAULT nextval('public.entity_links_id_seq'::regclass);

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_extracted_entity_id_fkey FOREIGN KEY (extracted_entity_id) REFERENCES public.extracted_entities(id);

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_canonical_entity_id_fkey FOREIGN KEY (canonical_entity_id) REFERENCES public.canonical_entities(id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_links_extracted_entity ON public.entity_links USING btree (extracted_entity_id);
CREATE INDEX IF NOT EXISTS ix_entity_links_id ON public.entity_links USING btree (id);
CREATE INDEX IF NOT EXISTS ix_entity_links_canonical_entity_id ON public.entity_links USING btree (canonical_entity_id);
