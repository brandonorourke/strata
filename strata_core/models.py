# strata_core/models.py
from datetime import datetime
from typing import Optional
from enum import PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    JSON,
    Boolean,
    ForeignKey,
    Enum
)
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
    published_at = Column(DateTime, nullable=False, index=True)

    raw_html = Column(Text, nullable=True)
    clean_text = Column(Text, nullable=True)

    processed_by_llm = Column(Boolean, default=False, nullable=False)

    events = relationship("EntityEvent", back_populates="article")


class EntityEvent(Base):
    __tablename__ = "entity_events"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)

    canonical_company_name = Column(String(500), nullable=False)
    normalized_name = Column(String(500), nullable=False, index=True)

    event_type = Column(String(100), nullable=False)    # "legal_action", "layoff", etc.
    event_date = Column(DateTime, nullable=True)
    is_primary_entity = Column(Boolean, default=False, nullable=False)

    raw_mentions = Column(JSON, nullable=True)          # list of strings
    event_description = Column(Text, nullable=True)
    transaction_role = Column(String(100), nullable=True)
    confidence = Column(Integer, nullable=True)         # or Float

    article = relationship("NewsArticle", back_populates="events")
