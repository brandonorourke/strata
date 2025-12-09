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

    processed_by_llm_on = Column(DateTime, nullable=True)
