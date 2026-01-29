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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .db import Base

class NewsSource(PyEnum):
    FREIGHTWAVES = "freightwaves"
    PRNEWSWIRE = "prnewswire"
    BUSINESSWIRE = "businesswire"
    SEC = "sec"
    DOJ = "doj"


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

    extracted_events = relationship("ExtractedEvent", back_populates="article")


class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"

    id = Column(Integer, primary_key=True, index=True)
    extracted_name = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=True)
    jurisdiction = Column(Text, nullable=True)
    legal_name_normalized = Column(Text, nullable=False, unique=True)
    loose_name_normalized = Column(Text, nullable=True)
    created_from = Column(Text, nullable=False, server_default="news")
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    extracted_events = relationship("ExtractedEvent", back_populates="entity")
    entity_links = relationship("EntityLink", back_populates="extracted_entity")


class ExtractedEvent(Base):
    __tablename__ = "extracted_events"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("extracted_entities.id"), nullable=False)
    extracted_name = Column(Text, nullable=False)
    is_primary_entity = Column(Boolean, nullable=False, default=False)
    event_type = Column(Text, nullable=True)
    transaction_role = Column(Text, nullable=True)
    event_date = Column(Date, nullable=True)
    event_description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("NewsArticle", back_populates="extracted_events")
    entity = relationship("ExtractedEntity", back_populates="extracted_events")


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(Text, nullable=False)
    legal_name_normalized = Column(Text, nullable=False)
    loose_name_normalized = Column(Text, nullable=True)
    jurisdiction = Column(Text, nullable=True)
    status = Column(Text, nullable=False, server_default="provisional")
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
