# strata_core/models.py
from datetime import datetime
from typing import Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    Date,
    Float,
    JSON,
    Boolean,
    ForeignKey,
    Enum,
    Numeric,
    and_,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship, foreign

from .db import Base

class NewsSource(PyEnum):
    FREIGHTWAVES = "freightwaves"
    PRNEWSWIRE = "prnewswire"
    BUSINESSWIRE = "businesswire"
    SEC_PRESS_RELEASES = "sec_press_releases"
    SEC_LITIGATION_RELEASES = "sec_litigation_releases"
    SEC_ADMIN_PROCEEDINGS = "sec_admin_proceedings"
    DOJ = "doj"
    FCC_ICFS = "fcc_icfs"


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(Enum(NewsSource, name="news_source_enum"), nullable=False)
    url = Column(Text, nullable=False, unique=True)
    title = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())

    raw_html = Column(Text, nullable=True)
    clean_text = Column(Text, nullable=True)
    llm_raw = Column(JSONB, nullable=True)
    entities_extracted_at = Column(DateTime(timezone=True), nullable=True)
    domains_extracted_at = Column(DateTime(timezone=True), nullable=True)

    # No real FK on ExtractedEvent.source_id (it's polymorphic) — read-only, news_article-only view.
    extracted_events = relationship(
        "ExtractedEvent",
        primaryjoin=lambda: and_(
            ExtractedEvent.source_type == "news_article",
            foreign(ExtractedEvent.source_id) == NewsArticle.id,
        ),
        viewonly=True,
    )
    article_domains = relationship("ArticleDomain", back_populates="article")


class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(Text, nullable=False, server_default="news_article")
    source_id = Column(Integer, nullable=False)
    extracted_name = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=True)
    jurisdiction = Column(Text, nullable=True)
    hq_country = Column(Text, nullable=True)
    hq_region = Column(Text, nullable=True)
    legal_name_normalized = Column(Text, nullable=False)
    loose_name_normalized = Column(Text, nullable=True)
    created_from = Column(Text, nullable=False, server_default="news")
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    icfs_canonical_entity_id = Column(Integer, ForeignKey("icfs_canonical_entities.id"), nullable=True)

    extracted_events = relationship("ExtractedEvent", back_populates="entity")
    entity_links = relationship("EntityLink", back_populates="extracted_entity")
    icfs_canonical_entity = relationship("IcfsCanonicalEntity", back_populates="extracted_entities")
    # No real FK backs source_id (it's polymorphic across news_articles/icfs_filings/etc.),
    # so this is a read-only convenience relationship scoped to the news_article case only.
    article = relationship(
        "NewsArticle",
        primaryjoin=lambda: and_(
            ExtractedEntity.source_type == "news_article",
            foreign(ExtractedEntity.source_id) == NewsArticle.id,
        ),
        viewonly=True,
        uselist=False,
    )


class ExtractedEvent(Base):
    __tablename__ = "extracted_events"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(Text, nullable=False, server_default="news_article")
    source_id = Column(Integer, nullable=False)
    entity_id = Column(Integer, ForeignKey("extracted_entities.id"), nullable=False)
    extracted_name = Column(Text, nullable=False)
    is_primary_entity = Column(Boolean, nullable=False, default=False)
    event_type = Column(Text, nullable=True)
    transaction_role = Column(Text, nullable=True)
    event_date = Column(Date, nullable=True)
    event_description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    llm_summary = Column(Text, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    signal_tier = Column(Text, nullable=True)
    signal_reason = Column(Text, nullable=True)

    # Same caveat as ExtractedEntity.article: no real FK, read-only, news_article-only.
    article = relationship(
        "NewsArticle",
        primaryjoin=lambda: and_(
            ExtractedEvent.source_type == "news_article",
            foreign(ExtractedEvent.source_id) == NewsArticle.id,
        ),
        viewonly=True,
        uselist=False,
    )
    entity = relationship("ExtractedEntity", back_populates="extracted_events")


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=True)
    legal_name_normalized = Column(Text, nullable=False)
    loose_name_normalized = Column(Text, nullable=True)
    jurisdiction = Column(Text, nullable=True)
    hq_country = Column(Text, nullable=True)
    hq_region = Column(Text, nullable=True)
    confirmed_domain = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    entity_links = relationship("EntityLink", back_populates="canonical_entity")


class EntityLink(Base):
    __tablename__ = "entity_links"

    id = Column(Integer, primary_key=True, index=True)
    extracted_entity_id = Column(Integer, ForeignKey("extracted_entities.id"), nullable=False)
    canonical_entity_id = Column(Integer, ForeignKey("canonical_entities.id"), nullable=False)
    link_confidence = Column(Float, nullable=True)
    link_method = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    extracted_entity = relationship("ExtractedEntity", back_populates="entity_links")
    canonical_entity = relationship("CanonicalEntity", back_populates="entity_links")


class ArticleDomain(Base):
    __tablename__ = "article_domains"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)
    domain = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("NewsArticle", back_populates="article_domains")


class IcfsFiling(Base):
    """Mirrors ServiceNow's x_fmc_ibfs_base_table (backs both Recent Filings and Recent Actions)."""

    __tablename__ = "icfs_filings"

    id = Column(Integer, primary_key=True, index=True)
    source_sys_id = Column(Text, nullable=False, unique=True)
    file_number = Column(Text, nullable=True)
    call_sign = Column(Text, nullable=True)
    applicant_name = Column(Text, nullable=True)
    submission_date = Column(DateTime(timezone=True), nullable=True)
    action = Column(Text, nullable=True)
    action_taken_date = Column(Date, nullable=True)   # date-only (ServiceNow glide_date); see migration 0040
    target_table = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    entities_extracted_at = Column(DateTime(timezone=True), nullable=True)
    brief_description = Column(Text, nullable=True)
    action_pn_url = Column(Text, nullable=True)
    grant_date = Column(Date, nullable=True)
    expiration_date = Column(Date, nullable=True)
    begin_date = Column(Date, nullable=True)
    grant_doc_url = Column(Text, nullable=True)
    detail_fetched_at = Column(DateTime(timezone=True), nullable=True)
    attachments = Column(JSON, nullable=True)
    raw_detail = Column(JSONB, nullable=True)

    # No real FK on ExtractedEvent.source_id (it's polymorphic) — read-only, icfs_filing-only view.
    extracted_events = relationship(
        "ExtractedEvent",
        primaryjoin=lambda: and_(
            ExtractedEvent.source_type == "icfs_filing",
            foreign(ExtractedEvent.source_id) == IcfsFiling.id,
        ),
        viewonly=True,
    )


class IcfsPleadingAndComment(Base):
    """Mirrors ServiceNow's x_fmc_ibfs_pleadings_and_comments table."""

    __tablename__ = "icfs_pleadings_and_comments"

    id = Column(Integer, primary_key=True, index=True)
    source_sys_id = Column(Text, nullable=False, unique=True)
    pleading_type = Column(Text, nullable=True)
    applicant_names = Column(Text, nullable=True)
    sys_created_on = Column(DateTime(timezone=True), nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    file_number = Column(Text, nullable=True)
    entities_extracted_at = Column(DateTime(timezone=True), nullable=True)
    filer_name = Column(Text, nullable=True)
    attachments = Column(JSON, nullable=True)
    detail_fetched_at = Column(DateTime(timezone=True), nullable=True)
    raw_detail = Column(JSONB, nullable=True)

    # No real FK on ExtractedEvent.source_id (it's polymorphic) — read-only, icfs_pleading-only view.
    extracted_events = relationship(
        "ExtractedEvent",
        primaryjoin=lambda: and_(
            ExtractedEvent.source_type == "icfs_pleading",
            foreign(ExtractedEvent.source_id) == IcfsPleadingAndComment.id,
        ),
        viewonly=True,
    )


class IcfsPublicNotice(Base):
    """Mirrors ServiceNow's x_fmc_ibfs_public_notices table."""

    __tablename__ = "icfs_public_notices"

    id = Column(Integer, primary_key=True, index=True)
    source_sys_id = Column(Text, nullable=False, unique=True)
    number = Column(Text, nullable=True)
    subsystem = Column(Text, nullable=True)
    type_of_document = Column(Text, nullable=True)
    public_notice_release_date = Column(Date, nullable=True)   # date-only (glide_date); see migration 0041
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    url = Column(Text, nullable=True)
    da_number = Column(Text, nullable=True)
    document_url = Column(Text, nullable=True)
    document_text = Column(Text, nullable=True)
    document_fetched_at = Column(DateTime(timezone=True), nullable=True)
    entities_extracted_at = Column(DateTime(timezone=True), nullable=True)

    # No real FK on ExtractedEvent.source_id (it's polymorphic) — read-only, icfs_notice-only view.
    extracted_events = relationship(
        "ExtractedEvent",
        primaryjoin=lambda: and_(
            ExtractedEvent.source_type == "icfs_notice",
            foreign(ExtractedEvent.source_id) == IcfsPublicNotice.id,
        ),
        viewonly=True,
    )


class IcfsCanonicalEntity(Base):
    """
    Tier 1 of entity resolution: one row per distinct ICFS applicant, collapsed by
    exact normalized name across all their filings. Deliberately not linked to
    CanonicalEntity yet — that cross-source hop is human-gated and deferred.
    """

    __tablename__ = "icfs_canonical_entities"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(Text, nullable=False)
    legal_name_normalized = Column(Text, nullable=False, unique=True)
    loose_name_normalized = Column(Text, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    extracted_entities = relationship("ExtractedEntity", back_populates="icfs_canonical_entity")


class IcfsFilingActionHistory(Base):
    """Append-only log of action changes detected during incremental ingest."""

    __tablename__ = "icfs_filing_action_history"

    id = Column(Integer, primary_key=True, index=True)
    filing_id = Column(Integer, ForeignKey("icfs_filings.id"), nullable=False)
    action = Column(Text, nullable=True)
    action_taken_date = Column(Date, nullable=True)   # date-only (ServiceNow glide_date); see migration 0040
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IcfsIngestState(Base):
    """One row per ICFS source table, tracking resumable backfill progress."""

    __tablename__ = "icfs_ingest_state"

    source_table = Column(Text, primary_key=True)
    backfill_page = Column(Integer, nullable=False, default=1)
    backfill_complete = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DowContractRelease(Base):
    __tablename__ = "dow_contract_releases"

    id            = Column(Integer, primary_key=True)
    article_id    = Column(Text, nullable=False, unique=True)
    url           = Column(Text, nullable=False)
    title         = Column(Text, nullable=True)
    release_date  = Column(Date, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    fetched_at    = Column(DateTime(timezone=True), nullable=True)
    raw_text      = Column(Text, nullable=True)
    content_hash  = Column(Text, nullable=True)
    raw_html      = Column(Text, nullable=True)

    llm_raw_response = Column(JSONB, nullable=True)
    llm_extracted_at = Column(DateTime(timezone=True), nullable=True)

    awards = relationship("DowAward", back_populates="release")


class DowAward(Base):
    __tablename__ = "dow_awards"

    id                   = Column(Integer, primary_key=True)
    release_id           = Column(Integer, ForeignKey("dow_contract_releases.id"), nullable=False)
    award_index          = Column(Integer, nullable=False)

    awardees             = Column(JSONB, nullable=True)   # [{name_raw, city_raw, state_raw, piid, parse_status, pairing_confidence}]
    amounts              = Column(JSONB, nullable=True)   # [{raw}]
    action_type          = Column(Text, nullable=True)    # award | modification | other (LLM)
    completion_date_raw  = Column(Text, nullable=True)
    completion_date      = Column(Date, nullable=True)
    contracting_activity = Column(Text, nullable=True)
    program_hint         = Column(Text, nullable=True)
    purpose              = Column(Text, nullable=True)
    source_excerpt       = Column(Text, nullable=True)
    llm_status           = Column(Text, nullable=True)
    extracted_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    release = relationship("DowContractRelease", back_populates="awards")


class Alert(Base):
    __tablename__ = "alerts"

    id          = Column(Integer, primary_key=True)
    kind        = Column(Text, nullable=False)                 # dow_match | dow_scan | icfs_match
    subject     = Column(Text, nullable=True)                  # watchlist company or release date
    title       = Column(Text, nullable=False)
    body        = Column(Text, nullable=True)
    meta        = Column(JSONB, nullable=True)                 # structured payload (piids, file_numbers, etc.)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at     = Column(DateTime(timezone=True), nullable=True)  # NULL until a sender delivers it


class AlertState(Base):
    __tablename__ = "alert_state"

    key         = Column(Text, primary_key=True)               # e.g. last_dow_award_id, last_icfs_ingested_at
    value       = Column(Text, nullable=True)
    updated_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SamAwardNotice(Base):
    """A SAM.gov award notice (ptype=a). Captured daily pre-market to test whether
    SAM publishes an award before DoW announces it. posted_date is date-only (search
    API); published_at/sam_created_at are precise (unkeyed detail endpoint)."""
    __tablename__ = "sam_award_notices"

    id             = Column(Integer, primary_key=True)
    notice_id      = Column(Text, nullable=False, unique=True)   # SAM noticeId (uiLink slug)
    piid           = Column(Text, nullable=True)                 # award.number
    piid_key       = Column(Text, nullable=True)                 # normalized join key (matches dow_awards)
    awardee_name   = Column(Text, nullable=True)
    awardee_uei    = Column(Text, nullable=True)                 # award.awardee.ueiSAM
    amount         = Column(Numeric, nullable=True)              # award.amount
    agency_path    = Column(Text, nullable=True)                 # fullParentPathName
    title          = Column(Text, nullable=True)
    posted_date    = Column(Date, nullable=True)                 # search API postedDate (date-only)
    published_at   = Column(DateTime(timezone=True), nullable=True)  # detail postedDate (precise); NULL until enriched
    sam_created_at = Column(DateTime(timezone=True), nullable=True)  # detail createdDate (precise)
    sam_url        = Column(Text, nullable=True)                 # uiLink
    fetched_at     = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # our first-seen
    raw            = Column(JSONB, nullable=True)                # full search-API record


class UsaspendingAward(Base):
    """Raw USASpending award — one row per spending_by_award result (an IDV vehicle
    or a contract/order), pulled by UEI. A manual pull-by-UEI viewer, NOT the daily
    pipeline — see apps/ingest/pull_usaspending.py. parent_award_id is parsed from
    generated_internal_id so a draw links to its vehicle; seed_uei records the family
    anchor we pulled under (a company is a set of UEIs)."""
    __tablename__ = "usaspending_awards"

    id                    = Column(Integer, primary_key=True)
    generated_internal_id = Column(Text, nullable=False, unique=True)  # USASpending stable id + upsert key
    award_id              = Column(Text, nullable=True)   # "Award ID" (PIID / order number)
    award_id_key          = Column(Text, nullable=True)   # normalized join key (matches dow/sam)
    award_type            = Column(Text, nullable=True)   # "Contract Award Type"
    is_idv                = Column(Boolean, nullable=False, server_default="false")  # vehicle vs contract/order
    parent_award_id       = Column(Text, nullable=True)   # parent PIID (NULL = standalone -NONE-)
    parent_generated_id   = Column(Text, nullable=True)   # CONT_IDV_{parent}_{ag} link
    recipient_name        = Column(Text, nullable=True)
    recipient_uei         = Column(Text, nullable=True)   # UEI on the award
    recipient_id          = Column(Text, nullable=True)   # USASpending recipient hash
    seed_uei              = Column(Text, nullable=True)   # family anchor pulled under
    awarding_agency       = Column(Text, nullable=True)
    awarding_sub_agency   = Column(Text, nullable=True)
    description           = Column(Text, nullable=True)
    start_date            = Column(Date, nullable=True)
    end_date              = Column(Date, nullable=True)
    amount                = Column(Numeric, nullable=True)  # "Award Amount"
    total_outlays         = Column(Numeric, nullable=True)
    naics_code            = Column(Text, nullable=True)
    psc_code              = Column(Text, nullable=True)
    last_modified         = Column(Text, nullable=True)     # raw "Last Modified Date"
    base_obligation_date  = Column(Date, nullable=True)
    fetched_at            = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw                   = Column(JSONB, nullable=True)
    # appended (migration 0043): ceiling/obligation come from the award DETAIL endpoint
    # (base_and_all_options — not in spending_by_award; populated by a later pass, NULL
    # for now); last_order_date is the IDV "Last Date to Order", set from the search.
    ceiling               = Column(Numeric, nullable=True)  # base_and_all_options (detail endpoint)
    total_obligation      = Column(Numeric, nullable=True)  # total_obligation (detail endpoint)
    last_order_date       = Column(Date, nullable=True)     # IDV "Last Date to Order"
    # appended (migration 0044): detail-endpoint enrichment
    base_exercised_options = Column(Numeric, nullable=True)  # base + exercised options (detail)
    enriched_at            = Column(DateTime(timezone=True), nullable=True)  # NULL until detail-fetched
    # NOTE: appended (migration 0045) FPDS metadata below; new IdiqRecipient class at EOF.
    # appended (migration 0045): FPDS metadata from the detail endpoint (via enrich)
    date_signed        = Column(Date, nullable=True)     # [top] action-signed date
    funding_sub_agency = Column(Text, nullable=True)     # [top] funding subtier (end customer)
    program_acronym    = Column(Text, nullable=True)     # [LTCD] program key, e.g. "PTS-G"
    is_multi_award     = Column(Boolean, nullable=True)  # [LTCD] MULTIPLE AWARD → the de-noiser
    solicitation_id    = Column(Text, nullable=True)     # [LTCD] solicitation_identifier
    set_aside          = Column(Text, nullable=True)     # [LTCD] type_set_aside_description
    pricing_type       = Column(Text, nullable=True)     # [LTCD] type_of_contract_pricing_description


class Company(Base):
    """Canonical company directory. `name` is the official exchange-registered name
    (NASDAQ/NYSE); `ticker` is NULL for privates; `aliases` holds extra match strings for
    subsidiary resolution when the official name + ticker aren't enough. Supersedes the
    DISPLAY_NAMES map in the API and the company-directory role of canonical_entities
    (news table, to be retired). See migration 0048."""
    __tablename__ = "companies"

    id         = Column(Integer, primary_key=True)
    slug       = Column(Text, nullable=False, unique=True)
    name       = Column(Text, nullable=False)
    ticker     = Column(Text, nullable=True, unique=True)            # NULL = private (no ticker)
    aliases    = Column(ARRAY(Text), nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdiqRecipient(Base):
    """UEI → ticker directory (normalized recipient mapping). Seeded from the resolved
    UEI family; the ticker mapping is human-curated via mapping_status (candidate →
    confirmed/excluded). Awards roll up to a ticker through recipient_uei = uei, counting
    only mapping_status='confirmed'. See migration 0046."""
    __tablename__ = "idiq_recipients"

    uei            = Column(Text, primary_key=True)
    recipient_name = Column(Text, nullable=True)
    ticker         = Column(Text, nullable=True)                     # NULL = unmapped / private
    mapping_status = Column(Text, nullable=False, server_default="candidate")  # candidate|confirmed|excluded
    seed_uei       = Column(Text, nullable=True)
    first_seen_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=True)
    # ownership-verify result (scan_stale_parents.py); see migration 0049
    ownership_verdict    = Column(Text, nullable=True)   # owned|divested|independent|jv|unknown
    ownership_confidence = Column(Text, nullable=True)
    ownership_as_of      = Column(Text, nullable=True)
    ownership_source     = Column(Text, nullable=True)
    ownership_rationale  = Column(Text, nullable=True)
    ownership_raw        = Column(Text, nullable=True)   # full LLM output
    ownership_model      = Column(Text, nullable=True)
    ownership_checked_at = Column(DateTime(timezone=True), nullable=True)


class AccessRequest(Base):
    """Inbound 'Request access' submissions from the public marketing page. One row per
    submission — no dedup, so the full inbound trail is preserved. See migration 0050."""
    __tablename__ = "access_requests"

    id         = Column(Integer, primary_key=True)
    email      = Column(Text, nullable=False)
    source     = Column(Text, nullable=False, server_default="marketing")
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

