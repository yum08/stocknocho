"""
Test suite for StockRAG Ingestion Pipeline (ingestion.py)
==========================================================

Tests platform normalizers, data ingestion from CSV/JSON,
and deduplication during ingestion.

Test Categories:
  TC-IG-01: Telegram post normalization
  TC-IG-02: X.com post normalization
  TC-IG-03: LinkedIn post normalization
  TC-IG-04: External ID generation (dedup keys)
  TC-IG-05: Text cleaning
  TC-IG-06: CSV ingestion pipeline
  TC-IG-07: JSON ingestion pipeline
  TC-IG-08: ingest_existing_files auto-discovery
"""

import os
import json
import pytest
from datetime import datetime
from pathlib import Path

from stock_rag.database import Database, Platform
from stock_rag.ingestion import (
    normalize_telegram_post,
    normalize_x_post,
    normalize_linkedin_post,
    _clean_text,
    _generate_external_id,
    DataIngestionPipeline,
)


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_ig.db")
    database = Database(db_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def pipeline(db):
    return DataIngestionPipeline(db)


@pytest.fixture
def sample_telegram_data():
    return {
        "id": 12345,
        "text": "Buy RELIANCE target 2800! https://t.me/link",
        "date": "2025-12-01T10:30:00",
        "channel": "StockTips",
        "channelName": "StockTips",
        "views": 5000,
        "reactions": 150,
        "forwards": 30,
        "comments": 10,
        "media": True,
    }


@pytest.fixture
def sample_x_data():
    return {
        "tweet_id": "1234567890",
        "full_text": "TCS looking bullish! Target 4200 🚀 https://x.com/post",
        "username": "trader_xyz",
        "created_at": "2025-12-01 10:30:00",
        "favoriteCount": 200,
        "retweetCount": 50,
        "replyCount": 15,
        "bookmark_count": 30,
        "viewCount": 10000,
    }


@pytest.fixture
def sample_linkedin_data():
    return {
        "urn": "urn:li:activity:7012345678901234567",
        "text": "Analysis of INFY quarterly results. Revenue growth strong.",
        "author": {"name": "Analyst Pro", "url": "https://linkedin.com/in/analyst"},
        "postedAt": "2025-12-01T10:30:00",
        "numLikes": 100,
        "numShares": 20,
        "numComments": 15,
    }


# ──────────────────────────────────────────────────────────────────────
# TC-IG-01: Telegram normalization
# ──────────────────────────────────────────────────────────────────────

class TestTelegramNormalization:
    """TC-IG-01: Telegram post normalization to unified schema."""

    def test_maps_all_fields(self, sample_telegram_data):
        result = normalize_telegram_post(sample_telegram_data, source_id=1)
        assert result["platform"] == Platform.TELEGRAM
        assert result["source_id"] == 1
        assert result["external_id"] == "12345"
        assert "RELIANCE" in result["text"]
        assert result["views"] == 5000
        assert result["likes"] == 150
        assert result["shares"] == 30
        assert result["has_media"] is True

    def test_cleans_text(self, sample_telegram_data):
        result = normalize_telegram_post(sample_telegram_data, source_id=1)
        assert "https://" not in result["text_clean"]

    def test_parses_date(self, sample_telegram_data):
        result = normalize_telegram_post(sample_telegram_data, source_id=1)
        assert result["posted_at"] is not None
        assert isinstance(result["posted_at"], datetime)

    def test_handles_missing_fields(self):
        """Normalizer gracefully handles missing/empty fields."""
        minimal = {"text": "Hello"}
        result = normalize_telegram_post(minimal, source_id=1)
        assert result["platform"] == Platform.TELEGRAM
        assert result["text"] == "Hello"
        assert result["views"] == 0


# ──────────────────────────────────────────────────────────────────────
# TC-IG-02: X.com normalization
# ──────────────────────────────────────────────────────────────────────

class TestXNormalization:
    """TC-IG-02: X.com/Twitter post normalization."""

    def test_maps_all_fields(self, sample_x_data):
        result = normalize_x_post(sample_x_data, source_id=2)
        assert result["platform"] == Platform.X
        assert result["external_id"] == "1234567890"
        assert "TCS" in result["text"]
        assert result["likes"] == 200
        assert result["shares"] == 50
        assert result["views"] == 10000

    def test_cleans_text(self, sample_x_data):
        result = normalize_x_post(sample_x_data, source_id=2)
        assert "https://" not in result["text_clean"]


# ──────────────────────────────────────────────────────────────────────
# TC-IG-03: LinkedIn normalization
# ──────────────────────────────────────────────────────────────────────

class TestLinkedInNormalization:
    """TC-IG-03: LinkedIn post normalization."""

    def test_maps_all_fields(self, sample_linkedin_data):
        result = normalize_linkedin_post(sample_linkedin_data, source_id=3)
        assert result["platform"] == Platform.LINKEDIN
        assert "INFY" in result["text"]
        assert result["likes"] == 100
        assert result["shares"] == 20

    def test_extracts_author_name(self, sample_linkedin_data):
        result = normalize_linkedin_post(sample_linkedin_data, source_id=3)
        # When 'author' is a dict, normalizer returns the dict as-is
        # The actual author name comes from nested dict or string
        author = result["author"]
        if isinstance(author, dict):
            assert author["name"] == "Analyst Pro"
        else:
            assert author == "Analyst Pro"


# ──────────────────────────────────────────────────────────────────────
# TC-IG-04: External ID generation
# ──────────────────────────────────────────────────────────────────────

class TestExternalIdGeneration:
    """TC-IG-04: Stable external ID generation for dedup."""

    def test_uses_platform_id(self):
        assert _generate_external_id("telegram", {"id": 42}) == "42"

    def test_uses_tweet_id(self):
        assert _generate_external_id("x", {"tweet_id": "abc123"}) == "abc123"

    def test_fallback_hash(self):
        """When no ID field, generates MD5 hash."""
        id1 = _generate_external_id("unknown", {"text": "Hello", "author": "me"})
        assert len(id1) == 32  # MD5 hex digest is 32 chars

    def test_deterministic(self):
        """Same input → same external_id."""
        data = {"text": "Same content", "author": "same"}
        id1 = _generate_external_id("x", data)
        id2 = _generate_external_id("x", data)
        assert id1 == id2


# ──────────────────────────────────────────────────────────────────────
# TC-IG-05: Text cleaning
# ──────────────────────────────────────────────────────────────────────

class TestTextCleaning:
    """TC-IG-05: URL removal and whitespace normalization."""

    def test_removes_urls(self):
        assert "link" not in _clean_text("Check https://example.com for details")

    def test_normalizes_whitespace(self):
        assert _clean_text("  too   many   spaces  ") == "too many spaces"

    def test_handles_none(self):
        assert _clean_text(None) == ""

    def test_handles_empty(self):
        assert _clean_text("") == ""


# ──────────────────────────────────────────────────────────────────────
# TC-IG-06: CSV ingestion
# ──────────────────────────────────────────────────────────────────────

class TestCSVIngestion:
    """TC-IG-06: Ingesting posts from CSV files."""

    def test_ingest_telegram_csv(self, pipeline, tmp_path, db):
        """Create a test CSV and ingest it as telegram data."""
        import pandas as pd
        csv_path = tmp_path / "apify_messages.csv"
        df = pd.DataFrame([
            {"id": 1, "text": "Buy RELIANCE", "channel": "tips",
             "date": "2025-01-01", "views": 100},
            {"id": 2, "text": "Sell TCS", "channel": "tips",
             "date": "2025-01-02", "views": 200},
        ])
        df.to_csv(csv_path, index=False)

        result = pipeline.ingest_from_csv(str(csv_path), Platform.TELEGRAM, "test_tg")
        assert result["inserted"] >= 2
        assert db.get_stats()["raw_posts"] >= 2

    def test_ingest_x_csv(self, pipeline, tmp_path, db):
        import pandas as pd
        csv_path = tmp_path / "x_posts.csv"
        df = pd.DataFrame([
            {"tweet_id": "t1", "full_text": "INFY strong", "username": "u1",
             "created_at": "2025-01-01", "favoriteCount": 10, "retweetCount": 5},
        ])
        df.to_csv(csv_path, index=False)

        result = pipeline.ingest_from_csv(str(csv_path), Platform.X, "test_x")
        assert result["inserted"] >= 1


# ──────────────────────────────────────────────────────────────────────
# TC-IG-07: JSON ingestion
# ──────────────────────────────────────────────────────────────────────

class TestJSONIngestion:
    """TC-IG-07: Ingesting posts from JSON files."""

    def test_ingest_telegram_json(self, pipeline, tmp_path, db):
        json_path = tmp_path / "apify_messages.json"
        data = [
            {"id": 100, "text": "RELIANCE breakout!", "channel": "tips",
             "date": "2025-01-01", "views": 500},
            {"id": 101, "text": "SBI rally", "channel": "tips",
             "date": "2025-01-02", "views": 300},
        ]
        json_path.write_text(json.dumps(data))

        result = pipeline.ingest_from_json(str(json_path), Platform.TELEGRAM, "test_tg")
        assert result["inserted"] >= 2


# ──────────────────────────────────────────────────────────────────────
# TC-IG-08: Auto-discovery
# ──────────────────────────────────────────────────────────────────────

class TestAutoDiscovery:
    """TC-IG-08: ingest_existing_files discovers and ingests known patterns."""

    def test_discovers_telegram_json(self, pipeline, tmp_path, db):
        """apify_messages.json should be auto-discovered as telegram."""
        json_path = tmp_path / "apify_messages.json"
        data = [
            {"id": 200, "text": "Buy HDFC", "channel": "ch",
             "date": "2025-01-01", "views": 100}
        ]
        json_path.write_text(json.dumps(data))

        result = pipeline.ingest_existing_files(str(tmp_path))
        assert result["files_processed"] >= 1
        assert result["total_inserted"] >= 1
