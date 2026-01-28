--
-- PostgreSQL database dump
--

\restrict Oifq4nLNhZpPsb8ZqMubWvpnEGHv8C6DuoeMBK9e8dyLv2bKRsZzNUSfME4xqE0

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
    'DOJ'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: extracted_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extracted_entities (
    id integer NOT NULL,
    canonical_name text NOT NULL,
    legal_name_normalized text NOT NULL,
    loose_name_normalized text,
    created_from text DEFAULT 'news'::text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL
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
    entities_extracted_at timestamp with time zone
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
-- Name: extracted_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_entities ALTER COLUMN id SET DEFAULT nextval('public.extracted_entities_id_seq'::regclass);


--
-- Name: extracted_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events ALTER COLUMN id SET DEFAULT nextval('public.extracted_events_id_seq'::regclass);


--
-- Name: news_articles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles ALTER COLUMN id SET DEFAULT nextval('public.news_articles_id_seq'::regclass);


--
-- Name: extracted_entities extracted_entities_legal_name_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_entities
    ADD CONSTRAINT extracted_entities_legal_name_normalized_key UNIQUE (legal_name_normalized);


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
-- Name: ix_news_articles_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_id ON public.news_articles USING btree (id);


--
-- Name: ix_news_articles_published_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_published_at ON public.news_articles USING btree (published_at);


--
-- Name: ux_extracted_events_article_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_extracted_events_article_entity ON public.extracted_events USING btree (article_id, entity_id);


--
-- Name: extracted_events extracted_events_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.news_articles(id);


--
-- Name: extracted_events extracted_events_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_events
    ADD CONSTRAINT extracted_events_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.extracted_entities(id);


--
-- PostgreSQL database dump complete
--

\unrestrict Oifq4nLNhZpPsb8ZqMubWvpnEGHv8C6DuoeMBK9e8dyLv2bKRsZzNUSfME4xqE0

