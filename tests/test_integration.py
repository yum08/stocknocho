"""
Test suite for StockRAG Integration Tests
===========================================

End-to-end tests that verify the complete pipeline from
ingestion → stock identification → sentiment → signal generation.

Test Categories:
  TC-INT-01: Full pipeline: ingest → process → signals
  TC-INT-02: Multiple platforms in single pipeline run
  TC-INT-03: Dedup across multiple ingestion runs
  TC-INT-04: Stats consistency after full pipeline
"""

import json
import pytest
from datetime import datetime, timedelta

from stock_rag.database import Database, Platform, SignalStrength
from stock_rag.ingestion import DataIngestionPipeline
from stock_rag.stock_identifier import StockIdentifier
from stock_rag.sentiment import SentimentAnalyzer, SignalAggregator


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_int.db")
    database = Database(db_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def full_pipeline(db, tmp_path):
    """Set up pipeline with test data files."""
    # Create telegram JSON
    tg_data = [
        {"id": 1, "text": "RELIANCE breakout above 2700! Strong buy! Target 3000. SL 2600.",
         "channel": "tips", "date": "2025-12-01T10:00:00", "views": 5000},
        {"id": 2, "text": "TCS reported excellent quarterly results. EPS beat estimates. Revenue growth strong.",
         "channel": "news", "date": "2025-12-01T11:00:00", "views": 3000},
        {"id": 3, "text": "Avoid HDFC Bank. Weak guidance. Sell on bounce. Breakdown below support. NPA concerns.",
         "channel": "alerts", "date": "2025-12-01T12:00:00", "views": 4000},
        {"id": 4, "text": "SBI looking bullish. Accumulate on dips. Government bank performing well.",
         "channel": "tips", "date": "2025-12-01T13:00:00", "views": 2000},
        {"id": 5, "text": "Good morning everyone, weather is nice today!",
         "channel": "general", "date": "2025-12-01T14:00:00", "views": 100},
    ]
    tg_path = tmp_path / "apify_messages.json"
    tg_path.write_text(json.dumps(tg_data))

    # Create X CSV
    import pandas as pd
    x_data = pd.DataFrame([
        {"tweet_id": "x1", "full_text": "RELIANCE rally continues! Upper circuit expected. FII buying heavy.",
         "username": "trader1", "created_at": "2025-12-01", "favorite_count": 500,
         "retweet_count": 100, "reply_count": 50, "views": 20000},
        {"tweet_id": "x2", "full_text": "INFY chart shows golden cross on daily. RSI bullish divergence. Buy.",
         "username": "chartist", "created_at": "2025-12-01", "favorite_count": 200,
         "retweet_count": 40, "reply_count": 10, "views": 8000},
    ])
    x_path = tmp_path / "x_posts.csv"
    x_data.to_csv(x_path, index=False)

    return db, tmp_path


# ──────────────────────────────────────────────────────────────────────
# TC-INT-01: Full pipeline end-to-end
# ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """TC-INT-01: Ingest → Stock ID → Sentiment → Signals."""

    def test_full_pipeline_execution(self, full_pipeline):
        db, data_dir = full_pipeline

        # Step 1: Ingest
        pipeline = DataIngestionPipeline(db)
        result = pipeline.ingest_existing_files(str(data_dir))
        assert result["total_inserted"] >= 5  # 5 TG + 2 X

        stats = db.get_stats()
        assert stats["raw_posts"] >= 5

        # Step 2: Identify stocks
        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)
        process_stats = si.process_unprocessed_posts(batch_size=100)
        assert process_stats["processed"] >= 5
        assert process_stats["stock_relevant"] >= 4  # Posts 1-4 + X posts
        assert process_stats["mentions_created"] >= 4

        # Step 3: Sentiment analysis
        aggregator = SignalAggregator(db)
        analyzed = aggregator.analyze_mentions()
        assert analyzed >= 4

        # Step 4: Signal generation
        signals = aggregator.generate_signals(window_hours=72)
        # Should have signals for at least RELIANCE and others
        assert len(signals) >= 1

        # Step 5: Verify final stats
        final = db.get_stats()
        assert final["stock_mentions"] >= 4
        assert final["signals"] >= 1

    def test_non_stock_post_not_relevant(self, full_pipeline):
        """Post #5 (weather) should be marked not stock-relevant."""
        db, data_dir = full_pipeline
        pipeline = DataIngestionPipeline(db)
        pipeline.ingest_existing_files(str(data_dir))

        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)
        si.process_unprocessed_posts()

        stats = db.get_stats()
        assert stats["raw_posts"] > stats["stock_relevant_posts"]


# ──────────────────────────────────────────────────────────────────────
# TC-INT-02: Multiple platforms
# ──────────────────────────────────────────────────────────────────────

class TestMultiPlatform:
    """TC-INT-02: Multiple platform data processed together."""

    def test_multi_platform_sources(self, full_pipeline):
        db, data_dir = full_pipeline
        pipeline = DataIngestionPipeline(db)
        pipeline.ingest_existing_files(str(data_dir))

        # Should have sources for both telegram and x
        stats = db.get_stats()
        assert stats["sources"] >= 2


# ──────────────────────────────────────────────────────────────────────
# TC-INT-03: Dedup across runs
# ──────────────────────────────────────────────────────────────────────

class TestDedupAcrossRuns:
    """TC-INT-03: Re-ingesting same data doesn't create duplicates."""

    def test_idempotent_ingestion(self, full_pipeline):
        db, data_dir = full_pipeline
        pipeline = DataIngestionPipeline(db)

        r1 = pipeline.ingest_existing_files(str(data_dir))
        r2 = pipeline.ingest_existing_files(str(data_dir))

        # Second run should ingest 0 new posts
        assert r2["total_inserted"] == 0
        # Total in DB should match first run
        assert db.get_stats()["raw_posts"] == r1["total_inserted"]


# ──────────────────────────────────────────────────────────────────────
# TC-INT-04: Stats consistency
# ──────────────────────────────────────────────────────────────────────

class TestStatsConsistency:
    """TC-INT-04: Stats are consistent after full pipeline."""

    def test_processed_equals_total(self, full_pipeline):
        """After processing, processed_posts == raw_posts."""
        db, data_dir = full_pipeline
        pipeline = DataIngestionPipeline(db)
        pipeline.ingest_existing_files(str(data_dir))

        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)
        si.process_unprocessed_posts(batch_size=100)

        stats = db.get_stats()
        assert stats["processed_posts"] == stats["raw_posts"]

    def test_relevant_leq_processed(self, full_pipeline):
        """stock_relevant_posts <= processed_posts."""
        db, data_dir = full_pipeline
        pipeline = DataIngestionPipeline(db)
        pipeline.ingest_existing_files(str(data_dir))

        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)
        si.process_unprocessed_posts()

        stats = db.get_stats()
        assert stats["stock_relevant_posts"] <= stats["processed_posts"]
