--
-- PostgreSQL database dump
--

\restrict uOy8B2zSdtDSeY8vyLQtagV7hF6ctY71zUSgaafoKZPaxZ3ho9BMNNXwZDl5Ppu

-- Dumped from database version 17.10 (Postgres.app)
-- Dumped by pg_dump version 17.10 (Postgres.app)

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
-- Name: alert_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alert_state (
    key text NOT NULL,
    value text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alerts (
    id integer NOT NULL,
    kind text NOT NULL,
    subject text,
    title text NOT NULL,
    body text,
    meta jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    sent_at timestamp with time zone
);


--
-- Name: alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;


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
-- Name: dow_awards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dow_awards (
    id integer NOT NULL,
    release_id integer NOT NULL,
    award_index integer NOT NULL,
    awardees jsonb,
    amounts jsonb,
    action_type text,
    completion_date_raw text,
    completion_date date,
    contracting_activity text,
    program_hint text,
    purpose text,
    source_excerpt text,
    llm_status text,
    extracted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dow_awards_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dow_awards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dow_awards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dow_awards_id_seq OWNED BY public.dow_awards.id;


--
-- Name: dow_contract_releases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dow_contract_releases (
    id integer NOT NULL,
    article_id text NOT NULL,
    url text NOT NULL,
    title text,
    release_date date,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    fetched_at timestamp with time zone,
    raw_text text,
    content_hash text,
    raw_html text,
    llm_raw_response jsonb,
    llm_extracted_at timestamp with time zone
);


--
-- Name: dow_contract_releases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dow_contract_releases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dow_contract_releases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dow_contract_releases_id_seq OWNED BY public.dow_contract_releases.id;


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
    source_type text DEFAULT 'news_article'::text NOT NULL,
    llm_summary text,
    source_excerpt text,
    signal_tier text,
    signal_reason text
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
-- Name: icfs_filing_action_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_filing_action_history (
    id integer NOT NULL,
    filing_id integer NOT NULL,
    action text,
    action_taken_date date,
    detected_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: icfs_filing_action_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.icfs_filing_action_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: icfs_filing_action_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.icfs_filing_action_history_id_seq OWNED BY public.icfs_filing_action_history.id;


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
    action_taken_date date,
    target_table text,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    entities_extracted_at timestamp with time zone,
    brief_description text,
    action_pn_url text,
    grant_date date,
    expiration_date date,
    begin_date date,
    grant_doc_url text,
    detail_fetched_at timestamp with time zone,
    attachments jsonb,
    raw_detail jsonb
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
-- Name: icfs_ingest_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icfs_ingest_state (
    source_table text NOT NULL,
    backfill_page integer DEFAULT 1 NOT NULL,
    backfill_complete boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


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
    entities_extracted_at timestamp with time zone,
    filer_name text,
    attachments jsonb,
    detail_fetched_at timestamp with time zone,
    raw_detail jsonb
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
    public_notice_release_date date,
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
-- Name: ingest_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingest_runs (
    id integer NOT NULL,
    pipeline text DEFAULT 'icfs'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    failed_script text,
    script_results jsonb
);


--
-- Name: ingest_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingest_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingest_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingest_runs_id_seq OWNED BY public.ingest_runs.id;


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
-- Name: sam_award_notices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sam_award_notices (
    id integer NOT NULL,
    notice_id text NOT NULL,
    piid text,
    piid_key text,
    awardee_name text,
    awardee_uei text,
    amount numeric,
    agency_path text,
    title text,
    posted_date date,
    published_at timestamp with time zone,
    sam_created_at timestamp with time zone,
    sam_url text,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    raw jsonb
);


--
-- Name: sam_award_notices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sam_award_notices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sam_award_notices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sam_award_notices_id_seq OWNED BY public.sam_award_notices.id;


--
-- Name: usaspending_awards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usaspending_awards (
    id integer NOT NULL,
    generated_internal_id text NOT NULL,
    award_id text,
    award_id_key text,
    award_type text,
    is_idv boolean DEFAULT false NOT NULL,
    parent_award_id text,
    parent_generated_id text,
    recipient_name text,
    recipient_uei text,
    recipient_id text,
    seed_uei text,
    ticker text,
    awarding_agency text,
    awarding_sub_agency text,
    description text,
    start_date date,
    end_date date,
    amount numeric,
    total_outlays numeric,
    naics_code text,
    psc_code text,
    last_modified text,
    base_obligation_date date,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    raw jsonb,
    ceiling numeric,
    total_obligation numeric,
    last_order_date date,
    base_exercised_options numeric,
    enriched_at timestamp with time zone
);


--
-- Name: usaspending_awards_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.usaspending_awards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: usaspending_awards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.usaspending_awards_id_seq OWNED BY public.usaspending_awards.id;


--
-- Name: alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);


--
-- Name: article_domains id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_domains ALTER COLUMN id SET DEFAULT nextval('public.article_domains_id_seq'::regclass);


--
-- Name: canonical_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_entities ALTER COLUMN id SET DEFAULT nextval('public.canonical_entities_id_seq'::regclass);


--
-- Name: dow_awards id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_awards ALTER COLUMN id SET DEFAULT nextval('public.dow_awards_id_seq'::regclass);


--
-- Name: dow_contract_releases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_contract_releases ALTER COLUMN id SET DEFAULT nextval('public.dow_contract_releases_id_seq'::regclass);


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
-- Name: icfs_filing_action_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filing_action_history ALTER COLUMN id SET DEFAULT nextval('public.icfs_filing_action_history_id_seq'::regclass);


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
-- Name: ingest_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingest_runs ALTER COLUMN id SET DEFAULT nextval('public.ingest_runs_id_seq'::regclass);


--
-- Name: news_articles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_articles ALTER COLUMN id SET DEFAULT nextval('public.news_articles_id_seq'::regclass);


--
-- Name: sam_award_notices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sam_award_notices ALTER COLUMN id SET DEFAULT nextval('public.sam_award_notices_id_seq'::regclass);


--
-- Name: usaspending_awards id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usaspending_awards ALTER COLUMN id SET DEFAULT nextval('public.usaspending_awards_id_seq'::regclass);


--
-- Name: alert_state alert_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_state
    ADD CONSTRAINT alert_state_pkey PRIMARY KEY (key);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


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
-- Name: dow_awards dow_awards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_awards
    ADD CONSTRAINT dow_awards_pkey PRIMARY KEY (id);


--
-- Name: dow_awards dow_awards_release_id_award_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_awards
    ADD CONSTRAINT dow_awards_release_id_award_index_key UNIQUE (release_id, award_index);


--
-- Name: dow_contract_releases dow_contract_releases_article_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_contract_releases
    ADD CONSTRAINT dow_contract_releases_article_id_key UNIQUE (article_id);


--
-- Name: dow_contract_releases dow_contract_releases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_contract_releases
    ADD CONSTRAINT dow_contract_releases_pkey PRIMARY KEY (id);


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
-- Name: icfs_filing_action_history icfs_filing_action_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filing_action_history
    ADD CONSTRAINT icfs_filing_action_history_pkey PRIMARY KEY (id);


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
-- Name: icfs_ingest_state icfs_ingest_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_ingest_state
    ADD CONSTRAINT icfs_ingest_state_pkey PRIMARY KEY (source_table);


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
-- Name: ingest_runs ingest_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingest_runs
    ADD CONSTRAINT ingest_runs_pkey PRIMARY KEY (id);


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
-- Name: sam_award_notices sam_award_notices_notice_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sam_award_notices
    ADD CONSTRAINT sam_award_notices_notice_id_key UNIQUE (notice_id);


--
-- Name: sam_award_notices sam_award_notices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sam_award_notices
    ADD CONSTRAINT sam_award_notices_pkey PRIMARY KEY (id);


--
-- Name: usaspending_awards usaspending_awards_generated_internal_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usaspending_awards
    ADD CONSTRAINT usaspending_awards_generated_internal_id_key UNIQUE (generated_internal_id);


--
-- Name: usaspending_awards usaspending_awards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usaspending_awards
    ADD CONSTRAINT usaspending_awards_pkey PRIMARY KEY (id);


--
-- Name: idx_alerts_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_created_at ON public.alerts USING btree (created_at DESC);


--
-- Name: idx_alerts_unsent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_unsent ON public.alerts USING btree (created_at) WHERE (sent_at IS NULL);


--
-- Name: idx_sam_notices_needs_detail; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sam_notices_needs_detail ON public.sam_award_notices USING btree (id) WHERE (published_at IS NULL);


--
-- Name: idx_sam_notices_piid_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sam_notices_piid_key ON public.sam_award_notices USING btree (piid_key);


--
-- Name: idx_sam_notices_posted_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sam_notices_posted_date ON public.sam_award_notices USING btree (posted_date DESC);


--
-- Name: idx_sam_notices_uei; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sam_notices_uei ON public.sam_award_notices USING btree (awardee_uei);


--
-- Name: idx_usa_awards_amount; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_amount ON public.usaspending_awards USING btree (amount DESC NULLS LAST);


--
-- Name: idx_usa_awards_award_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_award_id_key ON public.usaspending_awards USING btree (award_id_key);


--
-- Name: idx_usa_awards_is_idv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_is_idv ON public.usaspending_awards USING btree (is_idv);


--
-- Name: idx_usa_awards_needs_enrich; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_needs_enrich ON public.usaspending_awards USING btree (id) WHERE (enriched_at IS NULL);


--
-- Name: idx_usa_awards_parent_award_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_parent_award_id ON public.usaspending_awards USING btree (parent_award_id);


--
-- Name: idx_usa_awards_recipient_uei; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_recipient_uei ON public.usaspending_awards USING btree (recipient_uei);


--
-- Name: idx_usa_awards_seed_uei; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_usa_awards_seed_uei ON public.usaspending_awards USING btree (seed_uei);


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
-- Name: dow_awards dow_awards_release_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dow_awards
    ADD CONSTRAINT dow_awards_release_id_fkey FOREIGN KEY (release_id) REFERENCES public.dow_contract_releases(id);


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
-- Name: icfs_filing_action_history icfs_filing_action_history_filing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icfs_filing_action_history
    ADD CONSTRAINT icfs_filing_action_history_filing_id_fkey FOREIGN KEY (filing_id) REFERENCES public.icfs_filings(id);


--
-- PostgreSQL database dump complete
--

\unrestrict uOy8B2zSdtDSeY8vyLQtagV7hF6ctY71zUSgaafoKZPaxZ3ho9BMNNXwZDl5Ppu

