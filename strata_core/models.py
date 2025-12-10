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
    JSON,
    Boolean,
    ForeignKey,
    Enum,
    func
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
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())

    raw_html = Column(Text, nullable=True)
    clean_text = Column(Text, nullable=True)

    processed_by_llm_at = Column(DateTime(timezone=True), nullable=True)
