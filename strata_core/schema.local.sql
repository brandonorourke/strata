--
-- PostgreSQL database dump
--

\restrict v0qEpcjPqkVfS8eL8qM4e19T6qOHTwrDMmHI5r8oHKmhrcFsPSfbDX2UeJbj51j

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
    processed_by_llm_at timestamp with time zone
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
-- Name: news_articles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles ALTER COLUMN id SET DEFAULT nextval('public.news_articles_id_seq'::regclass);


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
-- Name: ix_news_articles_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_id ON public.news_articles USING btree (id);


--
-- Name: ix_news_articles_published_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_news_articles_published_at ON public.news_articles USING btree (published_at);


--
-- PostgreSQL database dump complete
--

\unrestrict v0qEpcjPqkVfS8eL8qM4e19T6qOHTwrDMmHI5r8oHKmhrcFsPSfbDX2UeJbj51j

