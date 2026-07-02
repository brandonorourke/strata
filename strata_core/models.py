# strata_core/models.py
from datetime import datetime
from typing import Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    Float,
    JSON,
    Boolean,
    ForeignKey,
    Enum,
    and_,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    action_taken_date = Column(DateTime(timezone=True), nullable=True)
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
    public_notice_release_date = Column(DateTime(timezone=True), nullable=True)
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


class IcfsIngestState(Base):
    """One row per ICFS source table, tracking resumable backfill progress."""

    __tablename__ = "icfs_ingest_state"

    source_table = Column(Text, primary_key=True)
    backfill_page = Column(Integer, nullable=False, default=1)
    backfill_complete = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
