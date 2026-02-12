"""
Database Models & Schema - Inspired by nrsyed's ProBoards scraper design.
=========================================================================

Architecture (similar to the ProBoards scraper pattern):
  - SQLAlchemy ORM for database abstraction (no raw SQL)
  - Database class as single interface (like ProBoards' Database class)
  - Two-level database design:
      Level 1: raw_posts, sources, scrape_jobs  (all scraped data)
      Level 2: stocks, stock_mentions, stock_signals  (filtered & mapped)

The ProBoards design used:
  - SQLite backend (lightweight, single-file)
  - SQLAlchemy ORM for Python-object mapping
  - Separate tables for each entity type
  - A Database class wrapping all DB operations

We adapt this for our stock market use case.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float,
    DateTime, Boolean, ForeignKey, Index, Enum as SAEnum,
    JSON, UniqueConstraint
)
from sqlalchemy.orm import (
    declarative_base, relationship, sessionmaker, Session
)
import enum

Base = declarative_base()


# ──────────────────────────────────────────────────────────────────────
# ENUMS
# ──────────────────────────────────────────────────────────────────────

class Platform(enum.Enum):
    TELEGRAM = "telegram"
    X = "x"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    OTHER = "other"


class SentimentLabel(enum.Enum):
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class AnalysisType(enum.Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    NEWS = "news"


class SignalStrength(enum.Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


# ──────────────────────────────────────────────────────────────────────
# LEVEL 1: RAW DATA TABLES
# ──────────────────────────────────────────────────────────────────────

class Source(Base):
    """A channel / handle / profile we scrape from."""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(SAEnum(Platform), nullable=False, index=True)
    handle = Column(String(255), nullable=False)            # e.g. "@stockstix"
    display_name = Column(String(255))
    url = Column(String(512))
    description = Column(Text)
    category = Column(String(100))                           # e.g. "stock_tip", "news", "analyst"
    reliability_score = Column(Float, default=0.5)           # 0.0 - 1.0
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    raw_posts = relationship("RawPost", back_populates="source")
    scrape_jobs = relationship("ScrapeJob", back_populates="source")

    __table_args__ = (
        UniqueConstraint('platform', 'handle', name='uq_platform_handle'),
    )

    def __repr__(self):
        return f"<Source {self.platform.value}:{self.handle}>"


class ScrapeJob(Base):
    """Track each scrape run (like ProBoards' run tracking)."""
    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(50), default="running")          # running, completed, failed
    posts_scraped = Column(Integer, default=0)
    posts_new = Column(Integer, default=0)
    error_message = Column(Text)
    config_snapshot = Column(JSON)                           # store the scrape config used

    # Relationships
    source = relationship("Source", back_populates="scrape_jobs")

    def __repr__(self):
        return f"<ScrapeJob {self.id} source={self.source_id} status={self.status}>"


class RawPost(Base):
    """
    Level 1: ALL scraped posts land here (unified schema across platforms).
    This is the 'first level database' the user described.
    """
    __tablename__ = "raw_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    platform = Column(SAEnum(Platform), nullable=False, index=True)

    # Post identity
    external_id = Column(String(255))                        # platform-specific post ID
    url = Column(String(512))

    # Content
    text = Column(Text)
    text_clean = Column(Text)                                # cleaned/normalized text
    language = Column(String(10), default="en")

    # Metadata
    author = Column(String(255))
    author_url = Column(String(512))
    posted_at = Column(DateTime, index=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    # Engagement metrics
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    reactions = Column(JSON)                                 # platform-specific reactions

    # Media
    has_media = Column(Boolean, default=False)
    media_urls = Column(JSON)                                # list of media URLs

    # Processing flags
    is_processed = Column(Boolean, default=False, index=True)
    is_stock_relevant = Column(Boolean, index=True)          # NULL = not checked

    # Relationships
    source = relationship("Source", back_populates="raw_posts")
    stock_mentions = relationship("StockMention", back_populates="raw_post")

    __table_args__ = (
        UniqueConstraint('platform', 'external_id', name='uq_platform_extid'),
        Index('ix_raw_posts_posted_at_platform', 'posted_at', 'platform'),
    )

    def __repr__(self):
        return f"<RawPost {self.platform.value}:{self.external_id}>"


# ──────────────────────────────────────────────────────────────────────
# LEVEL 2: STOCK-MAPPED TABLES
# ──────────────────────────────────────────────────────────────────────

class Stock(Base):
    """
    Master list of NSE/BSE stocks.
    Each row is a tradeable script/security.
    """
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False, unique=True, index=True)   # e.g. "RELIANCE"
    name = Column(String(255), nullable=False)                              # e.g. "Reliance Industries Ltd"
    isin = Column(String(20), unique=True)                                  # e.g. "INE002A01018"
    exchange = Column(String(10), nullable=False)                           # "NSE" or "BSE"
    bse_code = Column(String(20))                                           # BSE scrip code
    nse_symbol = Column(String(50), index=True)                             # NSE trading symbol
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(String(20))                                         # "large", "mid", "small"
    is_active = Column(Boolean, default=True)

    # Common aliases / keywords people use to refer to this stock
    aliases = Column(JSON)   # ["RIL", "Reliance", "Jio parent"] etc.

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    mentions = relationship("StockMention", back_populates="stock")
    signals = relationship("StockSignal", back_populates="stock")

    def __repr__(self):
        return f"<Stock {self.symbol} ({self.exchange})>"


class StockMention(Base):
    """
    Many-to-many mapping: a single post can mention multiple stocks,
    and a stock can be mentioned in many posts.
    This is the 'second level database' — filtered, stock-mapped data.
    """
    __tablename__ = "stock_mentions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_post_id = Column(Integer, ForeignKey("raw_posts.id"), nullable=False, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)

    # How we identified this stock in the post
    matched_text = Column(String(255))          # the actual text that matched
    match_method = Column(String(50))           # "symbol", "name", "alias", "isin", "context"
    confidence = Column(Float, default=1.0)     # 0.0 - 1.0

    # Sentiment for THIS stock in THIS post
    sentiment_score = Column(Float)             # -1.0 (very bearish) to +1.0 (very bullish)
    sentiment_label = Column(SAEnum(SentimentLabel))
    analysis_type = Column(SAEnum(AnalysisType))  # what kind of analysis is the post doing?

    # Extracted details
    target_price = Column(Float)
    stop_loss = Column(Float)
    time_horizon = Column(String(50))           # "intraday", "swing", "positional", "long_term"
    action_suggested = Column(String(50))       # "buy", "sell", "hold", "watch"

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    raw_post = relationship("RawPost", back_populates="stock_mentions")
    stock = relationship("Stock", back_populates="mentions")

    __table_args__ = (
        UniqueConstraint('raw_post_id', 'stock_id', name='uq_post_stock'),
        Index('ix_stock_mentions_created', 'created_at'),
    )

    def __repr__(self):
        return f"<StockMention post={self.raw_post_id} stock={self.stock_id}>"


class StockSignal(Base):
    """
    Aggregated signals per stock per time window.
    This is what we use for prediction — the derived intelligence.
    """
    __tablename__ = "stock_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)

    # Time window
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)

    # Aggregated metrics
    total_mentions = Column(Integer, default=0)
    unique_sources = Column(Integer, default=0)
    avg_sentiment = Column(Float)
    sentiment_std = Column(Float)               # standard deviation of sentiment
    bullish_count = Column(Integer, default=0)
    bearish_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)

    # Analysis breakdown
    technical_mentions = Column(Integer, default=0)
    fundamental_mentions = Column(Integer, default=0)
    news_mentions = Column(Integer, default=0)

    # Signal
    signal_strength = Column(SAEnum(SignalStrength))
    confidence = Column(Float)
    predicted_direction = Column(String(10))    # "up", "down", "flat"
    predicted_magnitude = Column(Float)         # expected % move

    # RAG context used for this signal
    rag_context_ids = Column(JSON)              # list of raw_post_ids used
    llm_reasoning = Column(Text)               # LLM's explanation

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="signals")

    __table_args__ = (
        Index('ix_stock_signals_window', 'stock_id', 'window_start', 'window_end'),
    )

    def __repr__(self):
        return f"<StockSignal stock={self.stock_id} {self.signal_strength}>"


# ──────────────────────────────────────────────────────────────────────
# DATABASE CLASS (inspired by ProBoards scraper's Database class)
# ──────────────────────────────────────────────────────────────────────

class Database:
    """
    Single interface for all database operations.

    Following the ProBoards design pattern:
    - Wraps SQLAlchemy session management
    - Provides convenient methods for insert/query
    - Client code never writes raw SQL
    - Handles deduplication via upsert logic
    """

    def __init__(self, db_path: str = "stock_rag.db"):
        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        return self._Session()

    # ── Source operations ────────────────────────────────────────────

    def upsert_source(self, platform: Platform, handle: str, **kwargs) -> Source:
        """Insert or update a source. Returns the Source object."""
        session = self.get_session()
        try:
            source = session.query(Source).filter_by(
                platform=platform, handle=handle
            ).first()
            if source:
                for k, v in kwargs.items():
                    if hasattr(source, k):
                        setattr(source, k, v)
                source.updated_at = datetime.utcnow()
            else:
                source = Source(platform=platform, handle=handle, **kwargs)
                session.add(source)
            session.commit()
            session.refresh(source)
            return source
        finally:
            session.close()

    def get_sources(self, platform: Optional[Platform] = None,
                    active_only: bool = True) -> List[Source]:
        session = self.get_session()
        try:
            q = session.query(Source)
            if platform:
                q = q.filter(Source.platform == platform)
            if active_only:
                q = q.filter(Source.is_active == True)
            return q.all()
        finally:
            session.close()

    # ── Raw Post operations ──────────────────────────────────────────

    def insert_raw_post(self, post_data: dict) -> Optional[RawPost]:
        """
        Insert a raw post if it doesn't already exist (dedup by platform+external_id).
        Returns the RawPost or None if duplicate.
        """
        session = self.get_session()
        try:
            # Check for duplicate
            existing = session.query(RawPost).filter_by(
                platform=post_data.get('platform'),
                external_id=str(post_data.get('external_id'))
            ).first()
            if existing:
                return None  # duplicate

            post = RawPost(**post_data)
            session.add(post)
            session.commit()
            session.refresh(post)
            return post
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def bulk_insert_raw_posts(self, posts: List[dict]) -> dict:
        """Bulk insert with dedup. Returns counts."""
        inserted = 0
        skipped = 0
        for post_data in posts:
            result = self.insert_raw_post(post_data)
            if result:
                inserted += 1
            else:
                skipped += 1
        return {"inserted": inserted, "skipped": skipped, "total": len(posts)}

    def get_unprocessed_posts(self, limit: int = 100) -> List[RawPost]:
        """Get posts that haven't been processed for stock identification."""
        session = self.get_session()
        try:
            return session.query(RawPost).filter(
                RawPost.is_processed == False
            ).order_by(RawPost.scraped_at.desc()).limit(limit).all()
        finally:
            session.close()

    def mark_post_processed(self, post_id: int, is_stock_relevant: bool):
        session = self.get_session()
        try:
            post = session.query(RawPost).get(post_id)
            if post:
                post.is_processed = True
                post.is_stock_relevant = is_stock_relevant
                session.commit()
        finally:
            session.close()

    # ── Stock operations ─────────────────────────────────────────────

    def upsert_stock(self, symbol: str, name: str, exchange: str, **kwargs) -> Stock:
        session = self.get_session()
        try:
            stock = session.query(Stock).filter_by(symbol=symbol).first()
            if stock:
                for k, v in kwargs.items():
                    if hasattr(stock, k):
                        setattr(stock, k, v)
                stock.updated_at = datetime.utcnow()
            else:
                stock = Stock(symbol=symbol, name=name, exchange=exchange, **kwargs)
                session.add(stock)
            session.commit()
            session.refresh(stock)
            return stock
        finally:
            session.close()

    def get_all_stocks(self) -> List[Stock]:
        session = self.get_session()
        try:
            return session.query(Stock).filter(Stock.is_active == True).all()
        finally:
            session.close()

    def search_stock(self, query: str) -> List[Stock]:
        """Search stocks by symbol, name, or alias."""
        session = self.get_session()
        try:
            query_upper = query.upper()
            # Exact symbol match first
            exact = session.query(Stock).filter(Stock.symbol == query_upper).first()
            if exact:
                return [exact]
            # Partial matches
            return session.query(Stock).filter(
                (Stock.symbol.contains(query_upper))
                | (Stock.name.ilike(f"%{query}%"))
                | (Stock.nse_symbol == query_upper)
            ).all()
        finally:
            session.close()

    # ── Stock Mention operations ─────────────────────────────────────

    def insert_stock_mention(self, raw_post_id: int, stock_id: int,
                             **kwargs) -> Optional[StockMention]:
        session = self.get_session()
        try:
            existing = session.query(StockMention).filter_by(
                raw_post_id=raw_post_id, stock_id=stock_id
            ).first()
            if existing:
                return existing

            mention = StockMention(
                raw_post_id=raw_post_id, stock_id=stock_id, **kwargs
            )
            session.add(mention)
            session.commit()
            session.refresh(mention)
            return mention
        finally:
            session.close()

    def get_mentions_for_stock(self, stock_id: int,
                               since: Optional[datetime] = None,
                               limit: int = 100) -> List[StockMention]:
        session = self.get_session()
        try:
            q = session.query(StockMention).filter(
                StockMention.stock_id == stock_id
            )
            if since:
                q = q.filter(StockMention.created_at >= since)
            return q.order_by(StockMention.created_at.desc()).limit(limit).all()
        finally:
            session.close()

    # ── Signal operations ────────────────────────────────────────────

    def insert_signal(self, stock_id: int, **kwargs) -> StockSignal:
        session = self.get_session()
        try:
            signal = StockSignal(stock_id=stock_id, **kwargs)
            session.add(signal)
            session.commit()
            session.refresh(signal)
            return signal
        finally:
            session.close()

    def get_latest_signal(self, stock_id: int) -> Optional[StockSignal]:
        session = self.get_session()
        try:
            return session.query(StockSignal).filter(
                StockSignal.stock_id == stock_id
            ).order_by(StockSignal.created_at.desc()).first()
        finally:
            session.close()

    # ── Scrape Job operations ────────────────────────────────────────

    def create_scrape_job(self, source_id: int, config: dict = None) -> ScrapeJob:
        session = self.get_session()
        try:
            job = ScrapeJob(source_id=source_id, config_snapshot=config)
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
        finally:
            session.close()

    def complete_scrape_job(self, job_id: int, posts_scraped: int,
                            posts_new: int, error: str = None):
        session = self.get_session()
        try:
            job = session.query(ScrapeJob).get(job_id)
            if job:
                job.completed_at = datetime.utcnow()
                job.status = "failed" if error else "completed"
                job.posts_scraped = posts_scraped
                job.posts_new = posts_new
                job.error_message = error
                session.commit()
        finally:
            session.close()

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        session = self.get_session()
        try:
            return {
                "sources": session.query(Source).count(),
                "raw_posts": session.query(RawPost).count(),
                "processed_posts": session.query(RawPost).filter(
                    RawPost.is_processed == True
                ).count(),
                "stock_relevant_posts": session.query(RawPost).filter(
                    RawPost.is_stock_relevant == True
                ).count(),
                "stocks": session.query(Stock).count(),
                "stock_mentions": session.query(StockMention).count(),
                "signals": session.query(StockSignal).count(),
            }
        finally:
            session.close()

    # ── Purge / cleanup ──────────────────────────────────────────────

    def purge_all_posts(self) -> dict:
        """Delete ALL raw posts, stock mentions, signals, and sources.
        Returns counts of deleted rows per table."""
        session = self.get_session()
        try:
            signals = session.query(StockSignal).delete()
            mentions = session.query(StockMention).delete()
            posts = session.query(RawPost).delete()
            sources = session.query(Source).delete()
            session.commit()
            return {"signals": signals, "mentions": mentions,
                    "posts": posts, "sources": sources}
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def purge_posts_by_source(self, source_id: int) -> dict:
        """Delete all posts (and their mentions) for a given source."""
        session = self.get_session()
        try:
            post_ids = [p.id for p in
                        session.query(RawPost.id).filter_by(source_id=source_id).all()]
            mentions = 0
            if post_ids:
                mentions = session.query(StockMention).filter(
                    StockMention.raw_post_id.in_(post_ids)
                ).delete(synchronize_session='fetch')
            posts = session.query(RawPost).filter_by(source_id=source_id).delete()
            session.query(Source).filter_by(id=source_id).delete()
            session.commit()
            return {"mentions": mentions, "posts": posts, "source_deleted": True}
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
