"""
Test suite for StockRAG Database Layer (database.py)
=====================================================

Tests the SQLAlchemy ORM models, Database class CRUD operations,
deduplication logic, and schema integrity.

Test Categories:
  TC-DB-01: Database creation & schema
  TC-DB-02: Source CRUD (upsert, query, dedup)
  TC-DB-03: RawPost insertion & deduplication
  TC-DB-04: Bulk insert with stats
  TC-DB-05: Stock upsert & search
  TC-DB-06: StockMention insertion & dedup
  TC-DB-07: StockSignal creation & retrieval
  TC-DB-08: ScrapeJob lifecycle
  TC-DB-09: get_stats correctness
  TC-DB-10: Cross-table relationships
"""

import os
import pytest
from datetime import datetime, timedelta

from stock_rag.database import (
    Database, Platform, SentimentLabel, AnalysisType, SignalStrength,
    Source, ScrapeJob, RawPost, Stock, StockMention, StockSignal,
)


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like DB for each test."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def db_with_source(db):
    """DB pre-populated with one source."""
    source = db.upsert_source(
        Platform.TELEGRAM, "@stocktips",
        display_name="Stock Tips Channel",
        category="stock_tip",
        reliability_score=0.8,
    )
    return db, source


@pytest.fixture
def db_with_post(db_with_source):
    """DB pre-populated with one source and one raw post."""
    db, source = db_with_source
    post = db.insert_raw_post({
        "source_id": source.id,
        "platform": Platform.TELEGRAM,
        "external_id": "msg_001",
        "text": "Buy RELIANCE target 2800 SL 2650",
        "text_clean": "Buy RELIANCE target 2800 SL 2650",
        "author": "@stocktips",
        "posted_at": datetime.utcnow(),
        "views": 1500,
        "likes": 45,
    })
    return db, source, post


# ──────────────────────────────────────────────────────────────────────
# TC-DB-01: Database creation & schema
# ──────────────────────────────────────────────────────────────────────

class TestDatabaseCreation:
    """TC-DB-01: Verify database and schema creation."""

    def test_creates_db_file(self, tmp_path):
        """DB file is created on disk."""
        db_path = str(tmp_path / "new.db")
        assert not os.path.exists(db_path)
        db = Database(db_path)
        assert os.path.exists(db_path)
        db.engine.dispose()

    def test_all_tables_exist(self, db):
        """All 6 expected tables are created."""
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        for expected in ["sources", "scrape_jobs", "raw_posts",
                         "stocks", "stock_mentions", "stock_signals"]:
            assert expected in table_names, f"Missing table: {expected}"

    def test_empty_stats_on_fresh_db(self, db):
        """Fresh DB should report zero counts everywhere."""
        stats = db.get_stats()
        assert stats["sources"] == 0
        assert stats["raw_posts"] == 0
        assert stats["stocks"] == 0
        assert stats["stock_mentions"] == 0
        assert stats["signals"] == 0


# ──────────────────────────────────────────────────────────────────────
# TC-DB-02: Source CRUD
# ──────────────────────────────────────────────────────────────────────

class TestSourceOperations:
    """TC-DB-02: Source creation, update, and dedup."""

    def test_create_source(self, db):
        """Source is created with correct fields."""
        src = db.upsert_source(Platform.TELEGRAM, "@test_channel",
                               display_name="Test Channel")
        assert src.id is not None
        assert src.platform == Platform.TELEGRAM
        assert src.handle == "@test_channel"
        assert src.display_name == "Test Channel"

    def test_upsert_updates_existing(self, db):
        """Upserting same platform+handle updates, doesn't duplicate."""
        src1 = db.upsert_source(Platform.X, "@trader",
                                display_name="Old Name")
        src2 = db.upsert_source(Platform.X, "@trader",
                                display_name="New Name")
        assert src1.id == src2.id
        assert src2.display_name == "New Name"
        assert db.get_stats()["sources"] == 1

    def test_different_platforms_create_separate(self, db):
        """Same handle on different platforms = two separate sources."""
        s1 = db.upsert_source(Platform.TELEGRAM, "@handle")
        s2 = db.upsert_source(Platform.X, "@handle")
        assert s1.id != s2.id
        assert db.get_stats()["sources"] == 2

    def test_get_sources_filter(self, db):
        """get_sources filters by platform correctly."""
        db.upsert_source(Platform.TELEGRAM, "@tg1")
        db.upsert_source(Platform.TELEGRAM, "@tg2")
        db.upsert_source(Platform.X, "@x1")

        tg = db.get_sources(platform=Platform.TELEGRAM)
        x = db.get_sources(platform=Platform.X)
        assert len(tg) == 2
        assert len(x) == 1


# ──────────────────────────────────────────────────────────────────────
# TC-DB-03: RawPost insertion & deduplication
# ──────────────────────────────────────────────────────────────────────

class TestRawPostOperations:
    """TC-DB-03: Post insertion, dedup, and unprocessed query."""

    def test_insert_post(self, db_with_source):
        db, source = db_with_source
        post = db.insert_raw_post({
            "source_id": source.id,
            "platform": Platform.TELEGRAM,
            "external_id": "post_100",
            "text": "RELIANCE breakout above 2700",
            "author": "@stocktips",
            "posted_at": datetime.utcnow(),
        })
        assert post is not None
        assert post.id > 0
        assert post.is_processed is False
        assert post.is_stock_relevant is None

    def test_duplicate_post_returns_none(self, db_with_source):
        """Same platform + external_id = duplicate → returns None."""
        db, source = db_with_source
        data = {
            "source_id": source.id,
            "platform": Platform.TELEGRAM,
            "external_id": "dup_001",
            "text": "Test post",
        }
        p1 = db.insert_raw_post(data)
        p2 = db.insert_raw_post(data)
        assert p1 is not None
        assert p2 is None
        assert db.get_stats()["raw_posts"] == 1

    def test_get_unprocessed_posts(self, db_with_post):
        db, source, post = db_with_post
        unproc = db.get_unprocessed_posts()
        assert len(unproc) >= 1
        assert any(p.id == post.id for p in unproc)

    def test_mark_post_processed(self, db_with_post):
        db, source, post = db_with_post
        db.mark_post_processed(post.id, is_stock_relevant=True)
        unproc = db.get_unprocessed_posts()
        assert all(p.id != post.id for p in unproc)


# ──────────────────────────────────────────────────────────────────────
# TC-DB-04: Bulk insert with stats
# ──────────────────────────────────────────────────────────────────────

class TestBulkInsert:
    """TC-DB-04: bulk_insert_raw_posts returns correct counts."""

    def test_bulk_insert_counts(self, db_with_source):
        db, source = db_with_source
        posts = [
            {"source_id": source.id, "platform": Platform.TELEGRAM,
             "external_id": f"bulk_{i}", "text": f"Post {i}"}
            for i in range(5)
        ]
        result = db.bulk_insert_raw_posts(posts)
        assert result["inserted"] == 5
        assert result["skipped"] == 0
        assert result["total"] == 5

    def test_bulk_insert_with_duplicates(self, db_with_source):
        db, source = db_with_source
        # Pre-insert one
        db.insert_raw_post({
            "source_id": source.id, "platform": Platform.TELEGRAM,
            "external_id": "bulk_0", "text": "Existing"
        })
        posts = [
            {"source_id": source.id, "platform": Platform.TELEGRAM,
             "external_id": f"bulk_{i}", "text": f"Post {i}"}
            for i in range(3)
        ]
        result = db.bulk_insert_raw_posts(posts)
        assert result["inserted"] == 2
        assert result["skipped"] == 1


# ──────────────────────────────────────────────────────────────────────
# TC-DB-05: Stock upsert & search
# ──────────────────────────────────────────────────────────────────────

class TestStockOperations:
    """TC-DB-05: Stock CRUD and search."""

    def test_upsert_stock(self, db):
        stock = db.upsert_stock("RELIANCE", "Reliance Industries Ltd", "NSE",
                                aliases=["RIL", "Reliance"], sector="Oil & Gas")
        assert stock.id > 0
        assert stock.symbol == "RELIANCE"
        assert stock.aliases == ["RIL", "Reliance"]

    def test_upsert_stock_idempotent(self, db):
        """Upserting same symbol updates, doesn't create duplicate."""
        s1 = db.upsert_stock("TCS", "Tata Consultancy Services", "NSE")
        s2 = db.upsert_stock("TCS", "Tata Consultancy Services", "NSE",
                             sector="IT")
        assert s1.id == s2.id
        assert db.get_stats()["stocks"] == 1

    def test_search_stock_by_symbol(self, db):
        db.upsert_stock("INFY", "Infosys Ltd", "NSE")
        results = db.search_stock("INFY")
        assert len(results) == 1
        assert results[0].symbol == "INFY"

    def test_search_stock_by_name(self, db):
        db.upsert_stock("WIPRO", "Wipro Ltd", "NSE")
        results = db.search_stock("wipro")
        assert len(results) >= 1

    def test_get_all_stocks(self, db):
        db.upsert_stock("A", "Stock A", "NSE")
        db.upsert_stock("B", "Stock B", "NSE")
        stocks = db.get_all_stocks()
        assert len(stocks) == 2


# ──────────────────────────────────────────────────────────────────────
# TC-DB-06: StockMention insertion & dedup
# ──────────────────────────────────────────────────────────────────────

class TestStockMentionOperations:
    """TC-DB-06: StockMention CRUD and deduplication."""

    def test_insert_mention(self, db_with_post):
        db, source, post = db_with_post
        stock = db.upsert_stock("RELIANCE", "Reliance Industries", "NSE")
        mention = db.insert_stock_mention(
            raw_post_id=post.id, stock_id=stock.id,
            matched_text="RELIANCE", match_method="symbol",
            confidence=0.95,
        )
        assert mention is not None
        assert mention.raw_post_id == post.id
        assert mention.stock_id == stock.id

    def test_mention_dedup(self, db_with_post):
        """Same post+stock pair → returns existing, no duplicate."""
        db, source, post = db_with_post
        stock = db.upsert_stock("TCS", "TCS Ltd", "NSE")
        m1 = db.insert_stock_mention(raw_post_id=post.id, stock_id=stock.id)
        m2 = db.insert_stock_mention(raw_post_id=post.id, stock_id=stock.id)
        assert m1.id == m2.id

    def test_get_mentions_for_stock(self, db_with_post):
        db, source, post = db_with_post
        stock = db.upsert_stock("SBIN", "SBI", "NSE")
        db.insert_stock_mention(raw_post_id=post.id, stock_id=stock.id)
        mentions = db.get_mentions_for_stock(stock.id)
        assert len(mentions) == 1


# ──────────────────────────────────────────────────────────────────────
# TC-DB-07: StockSignal creation & retrieval
# ──────────────────────────────────────────────────────────────────────

class TestStockSignalOperations:
    """TC-DB-07: Signal creation and latest-signal query."""

    def test_insert_signal(self, db):
        stock = db.upsert_stock("RELIANCE", "Reliance", "NSE")
        now = datetime.utcnow()
        signal = db.insert_signal(
            stock_id=stock.id,
            window_start=now - timedelta(hours=24),
            window_end=now,
            total_mentions=10,
            avg_sentiment=0.65,
            bullish_count=8,
            bearish_count=2,
            signal_strength=SignalStrength.BUY,
            confidence=0.75,
            predicted_direction="up",
        )
        assert signal.id > 0
        assert signal.signal_strength == SignalStrength.BUY

    def test_get_latest_signal(self, db):
        stock = db.upsert_stock("TCS", "TCS", "NSE")
        now = datetime.utcnow()
        db.insert_signal(stock_id=stock.id,
                         window_start=now - timedelta(hours=48),
                         window_end=now - timedelta(hours=24),
                         signal_strength=SignalStrength.HOLD,
                         total_mentions=5, avg_sentiment=0.0,
                         predicted_direction="flat")
        db.insert_signal(stock_id=stock.id,
                         window_start=now - timedelta(hours=24),
                         window_end=now,
                         signal_strength=SignalStrength.STRONG_BUY,
                         total_mentions=15, avg_sentiment=0.8,
                         predicted_direction="up")
        latest = db.get_latest_signal(stock.id)
        assert latest.signal_strength == SignalStrength.STRONG_BUY


# ──────────────────────────────────────────────────────────────────────
# TC-DB-08: ScrapeJob lifecycle
# ──────────────────────────────────────────────────────────────────────

class TestScrapeJobLifecycle:
    """TC-DB-08: Create → complete / fail scrape jobs."""

    def test_create_and_complete(self, db_with_source):
        db, source = db_with_source
        job = db.create_scrape_job(source.id, config={"limit": 50})
        assert job.status == "running"

        db.complete_scrape_job(job.id, posts_scraped=50, posts_new=30)
        session = db.get_session()
        updated = session.query(ScrapeJob).get(job.id)
        assert updated.status == "completed"
        assert updated.posts_scraped == 50
        assert updated.posts_new == 30
        session.close()

    def test_scrape_job_failure(self, db_with_source):
        db, source = db_with_source
        job = db.create_scrape_job(source.id)
        db.complete_scrape_job(job.id, posts_scraped=0, posts_new=0,
                               error="Timeout")
        session = db.get_session()
        updated = session.query(ScrapeJob).get(job.id)
        assert updated.status == "failed"
        assert updated.error_message == "Timeout"
        session.close()


# ──────────────────────────────────────────────────────────────────────
# TC-DB-09: get_stats correctness
# ──────────────────────────────────────────────────────────────────────

class TestStats:
    """TC-DB-09: Stats reflect actual row counts accurately."""

    def test_stats_after_inserts(self, db_with_post):
        db, source, post = db_with_post
        stock = db.upsert_stock("REL", "Reliance", "NSE")
        db.insert_stock_mention(raw_post_id=post.id, stock_id=stock.id)
        db.mark_post_processed(post.id, is_stock_relevant=True)

        stats = db.get_stats()
        assert stats["sources"] == 1
        assert stats["raw_posts"] == 1
        assert stats["processed_posts"] == 1
        assert stats["stock_relevant_posts"] == 1
        assert stats["stocks"] == 1
        assert stats["stock_mentions"] == 1


# ──────────────────────────────────────────────────────────────────────
# TC-DB-10: Cross-table relationships
# ──────────────────────────────────────────────────────────────────────

class TestRelationships:
    """TC-DB-10: Verify ORM relationships work correctly."""

    def test_source_to_posts(self, db_with_post):
        """Source.raw_posts relationship loads related posts."""
        db, source, post = db_with_post
        session = db.get_session()
        src = session.query(Source).get(source.id)
        assert len(src.raw_posts) >= 1
        session.close()

    def test_post_to_source(self, db_with_post):
        """RawPost.source backref works."""
        db, source, post = db_with_post
        session = db.get_session()
        p = session.query(RawPost).get(post.id)
        assert p.source.handle == "@stocktips"
        session.close()
