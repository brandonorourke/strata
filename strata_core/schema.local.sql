--
-- PostgreSQL database dump
--

\restrict nQbpvTc0US6LUGyvbMqLJcgqcpQNk10q1tsUmjdMXHgp7zqb7iTGAxyjssNSZnd

-- Dumped from database version 17.6 (Postgres.app)
-- Dumped by pg_dump version 17.6 (Postgres.app)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: news_source_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.news_source_enum AS ENUM (
    'FREIGHTWAVES',
    'PRNEWSWIRE',
    'BUSINESSWIRE',
    'SEC',
    'DOJ',
    'SEC_PRESS_RELEASES',
    'SEC_LITIGATION_RELEASES',
    'SEC_ADMIN_PROCEEDINGS',
    'FCC_ICFS'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: article_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.article_domains (
    id integer NOT NULL,
    article_id integer NOT NULL,
    domain text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: article_domains_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.article_domains_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: article_domains_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.article_domains_id_seq OWNED BY public.article_domains.id;


--
-- Name: canonical_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.canonical_entities (
    id integer NOT NULL,
    canonical_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    jurisdiction text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    entity_type text,
    hq_country text,
    hq_region text,
    confirmed_domain text
);


--
-- Name: canonical_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.canonical_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: canonical_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.canonical_entities_id_seq OWNED BY public.canonical_entities.id;


--
-- Name: entity_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_links (
    id integer NOT NULL,
    extracted_entity_id integer NOT NULL,
    canonical_entity_id integer NOT NULL,
    link_confidence double precision,
    link_method text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: entity_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.entity_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entity_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.entity_links_id_seq OWNED BY public.entity_links.id;


--
-- Name: extracted_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extracted_entities (
    id integer NOT NULL,
    extracted_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    created_from text DEFAULT 'news'::text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    entity_type text,
    jurisdiction text,
    source_id integer NOT NULL,
    hq_country text,
    hq_region text,
    source_type text DEFAULT 'news_article'::text NOT NULL,
    icfs_canonical_entity_id integer
);


--
-- Name: extracted_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.extracted_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: extracted_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.extracted_entities_id_seq OWNED BY public.extracted_entities.id;


--
-- Name: extracted_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extracted_events (
    id integer NOT NULL,
    source_id integer NOT NULL,
    entity_id integer NOT NULL,
    extracted_name text NOT NULL,
    is_primary_entity boolean DEFAULT false NOT NULL,
    event_type text,
    transaction_role text,
    event_date date,
    event_description text,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now(),
    source_type text DEFAULT 'news_article'::text NOT NULL
);


--
-- Name: extracted_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.extracted_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: extracted_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.extracted_events_id_seq OWNED BY public.extracted_events.id;


--
-- Name: icfs_canonical_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_canonical_entities (
    id integer NOT NULL,
    canonical_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    first_seen_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: icfs_canonical_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.icfs_canonical_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: icfs_canonical_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.icfs_canonical_entities_id_seq OWNED BY public.icfs_canonical_entities.id;


--
-- Name: icfs_filings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_filings (
    id integer NOT NULL,
    source_sys_id text NOT NULL,
    file_number text,
    call_sign text,
    applicant_name text,
    submission_date timestamp with time zone,
    action text,
    action_taken_date timestamp with time zone,
    target_table text,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    entities_extracted_at timestamp with time zone
);


--
-- Name: icfs_filings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.icfs_filings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: icfs_filings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.icfs_filings_id_seq OWNED BY public.icfs_filings.id;


--
-- Name: icfs_pleadings_and_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_pleadings_and_comments (
    id integer NOT NULL,
    source_sys_id text NOT NULL,
    pleading_type text,
    applicant_names text,
    sys_created_on timestamp with time zone,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    file_number text,
    entities_extracted_at timestamp with time zone
);


--
-- Name: icfs_pleadings_and_comments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.icfs_pleadings_and_comments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: icfs_pleadings_and_comments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.icfs_pleadings_and_comments_id_seq OWNED BY public.icfs_pleadings_and_comments.id;


--
-- Name: icfs_public_notices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_public_notices (
    id integer NOT NULL,
    source_sys_id text NOT NULL,
    number text,
    subsystem text,
    type_of_document text,
    public_notice_release_date timestamp with time zone,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    url text,
    da_number text,
    document_url text,
    document_text text,
    document_fetched_at timestamp with time zone,
    entities_extracted_at timestamp with time zone
);


--
-- Name: icfs_public_notices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.icfs_public_notices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: icfs_public_notices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.icfs_public_notices_id_seq OWNED BY public.icfs_public_notices.id;


--
-- Name: news_articles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_articles (
    id integer NOT NULL,
    source public.news_source_enum NOT NULL,
    url text NOT NULL,
    title text NOT NULL,
    published_at timestamp with time zone NOT NULL,
    ingested_at timestamp with time zone DEFAULT now(),
    raw_html text,
    clean_text text,
    llm_raw jsonb,
    entities_extracted_at timestamp with time zone,
    domains_extracted_at timestamp with time zone
);


--
-- Name: news_articles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.news_articles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: news_articles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.news_articles_id_seq OWNED BY public.news_articles.id;


--
-- Name: article_domains id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_domains ALTER COLUMN id SET DEFAULT nextval('public.article_domains_id_seq'::regclass);


--
-- Name: canonical_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_entities ALTER COLUMN id SET DEFAULT nextval('public.canonical_entities_id_seq'::regclass);


--
-- Name: entity_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links ALTER COLUMN id SET DEFAULT nextval('public.entity_links_id_seq'::regclass);


--
-- Name: extracted_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_entities ALTER COLUMN id SET DEFAULT nextval('public.extracted_entities_id_seq'::regclass);


--
-- Name: extracted_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events ALTER COLUMN id SET DEFAULT nextval('public.extracted_events_id_seq'::regclass);


--
-- Name: icfs_canonical_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_canonical_entities ALTER COLUMN id SET DEFAULT nextval('public.icfs_canonical_entities_id_seq'::regclass);


--
-- Name: icfs_filings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filings ALTER COLUMN id SET DEFAULT nextval('public.icfs_filings_id_seq'::regclass);


--
-- Name: icfs_pleadings_and_comments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_pleadings_and_comments ALTER COLUMN id SET DEFAULT nextval('public.icfs_pleadings_and_comments_id_seq'::regclass);


--
-- Name: icfs_public_notices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_public_notices ALTER COLUMN id SET DEFAULT nextval('public.icfs_public_notices_id_seq'::regclass);


--
-- Name: news_articles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles ALTER COLUMN id SET DEFAULT nextval('public.news_articles_id_seq'::regclass);


--
-- Name: article_domains article_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_domains
    ADD CONSTRAINT article_domains_pkey PRIMARY KEY (id);


--
-- Name: canonical_entities canonical_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_entities
    ADD CONSTRAINT canonical_entities_pkey PRIMARY KEY (id);


--
-- Name: entity_links entity_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_pkey PRIMARY KEY (id);


--
-- Name: extracted_entities extracted_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_entities
    ADD CONSTRAINT extracted_entities_pkey PRIMARY KEY (id);


--
-- Name: extracted_events extracted_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_pkey PRIMARY KEY (id);


--
-- Name: icfs_canonical_entities icfs_canonical_entities_legal_name_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_canonical_entities
    ADD CONSTRAINT icfs_canonical_entities_legal_name_normalized_key UNIQUE (legal_name_normalized);


--
-- Name: icfs_canonical_entities icfs_canonical_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_canonical_entities
    ADD CONSTRAINT icfs_canonical_entities_pkey PRIMARY KEY (id);


--
-- Name: icfs_filings icfs_filings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filings
    ADD CONSTRAINT icfs_filings_pkey PRIMARY KEY (id);


--
-- Name: icfs_filings icfs_filings_source_sys_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filings
    ADD CONSTRAINT icfs_filings_source_sys_id_key UNIQUE (source_sys_id);


--
-- Name: icfs_pleadings_and_comments icfs_pleadings_and_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_pleadings_and_comments
    ADD CONSTRAINT icfs_pleadings_and_comments_pkey PRIMARY KEY (id);


--
-- Name: icfs_pleadings_and_comments icfs_pleadings_and_comments_source_sys_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_pleadings_and_comments
    ADD CONSTRAINT icfs_pleadings_and_comments_source_sys_id_key UNIQUE (source_sys_id);


--
-- Name: icfs_public_notices icfs_public_notices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_public_notices
    ADD CONSTRAINT icfs_public_notices_pkey PRIMARY KEY (id);


--
-- Name: icfs_public_notices icfs_public_notices_source_sys_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_public_notices
    ADD CONSTRAINT icfs_public_notices_source_sys_id_key UNIQUE (source_sys_id);


--
-- Name: news_articles news_articles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles
    ADD CONSTRAINT news_articles_pkey PRIMARY KEY (id);


--
-- Name: news_articles news_articles_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles
    ADD CONSTRAINT news_articles_url_key UNIQUE (url);


--
-- Name: ix_article_domains_article_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_article_domains_article_id ON public.article_domains USING btree (article_id);


--
-- Name: ix_article_domains_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_article_domains_id ON public.article_domains USING btree (id);


--
-- Name: ix_canonical_entities_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_canonical_entities_id ON public.canonical_entities USING btree (id);


--
-- Name: ix_entity_links_canonical_entity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_canonical_entity_id ON public.entity_links USING btree (canonical_entity_id);


--
-- Name: ix_entity_links_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_id ON public.entity_links USING btree (id);


--
-- Name: ix_extracted_entities_icfs_canonical; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_entities_icfs_canonical ON public.extracted_entities USING btree (icfs_canonical_entity_id);


--
-- Name: ix_extracted_entities_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_entities_id ON public.extracted_entities USING btree (id);


--
-- Name: ix_extracted_events_entity_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_events_entity_id_created_at ON public.extracted_events USING btree (entity_id, created_at);


--
-- Name: ix_extracted_events_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_events_id ON public.extracted_events USING btree (id);


--
-- Name: ix_icfs_filings_applicant_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_filings_applicant_name ON public.icfs_filings USING btree (applicant_name);


--
-- Name: ix_icfs_filings_file_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_filings_file_number ON public.icfs_filings USING btree (file_number);


--
-- Name: ix_icfs_filings_submission_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_filings_submission_date ON public.icfs_filings USING btree (submission_date);


--
-- Name: ix_icfs_pleadings_file_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_pleadings_file_number ON public.icfs_pleadings_and_comments USING btree (file_number);


--
-- Name: ix_icfs_pleadings_sys_created_on; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_pleadings_sys_created_on ON public.icfs_pleadings_and_comments USING btree (sys_created_on);


--
-- Name: ix_icfs_public_notices_release_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_icfs_public_notices_release_date ON public.icfs_public_notices USING btree (public_notice_release_date);


--
-- Name: ix_news_articles_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_id ON public.news_articles USING btree (id);


--
-- Name: ix_news_articles_published_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_published_at ON public.news_articles USING btree (published_at);


--
-- Name: ux_article_domains_article_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_article_domains_article_domain ON public.article_domains USING btree (article_id, domain);


--
-- Name: ux_entity_links_extracted_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_entity_links_extracted_entity ON public.entity_links USING btree (extracted_entity_id);


--
-- Name: ux_extracted_entities_source_legal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_extracted_entities_source_legal ON public.extracted_entities USING btree (source_type, source_id, legal_name_normalized);


--
-- Name: ux_extracted_events_source_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_extracted_events_source_entity ON public.extracted_events USING btree (source_type, source_id, entity_id);


--
-- Name: article_domains article_domains_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_domains
    ADD CONSTRAINT article_domains_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.news_articles(id);


--
-- Name: entity_links entity_links_canonical_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_canonical_entity_id_fkey FOREIGN KEY (canonical_entity_id) REFERENCES public.canonical_entities(id);


--
-- Name: entity_links entity_links_extracted_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_extracted_entity_id_fkey FOREIGN KEY (extracted_entity_id) REFERENCES public.extracted_entities(id);


--
-- Name: extracted_entities extracted_entities_icfs_canonical_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_entities
    ADD CONSTRAINT extracted_entities_icfs_canonical_entity_id_fkey FOREIGN KEY (icfs_canonical_entity_id) REFERENCES public.icfs_canonical_entities(id);


--
-- Name: extracted_events extracted_events_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.extracted_entities(id);


--
-- PostgreSQL database dump complete
--

\unrestrict nQbpvTc0US6LUGyvbMqLJcgqcpQNk10q1tsUmjdMXHgp7zqb7iTGAxyjssNSZnd

