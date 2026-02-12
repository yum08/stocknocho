"""
Test suite for StockRAG Vector Store (vector_store.py)
=======================================================

Tests ChromaDB vector store operations — add, search,
sync, and metadata filtering.

Test Categories:
  TC-VS-01: Collection creation
  TC-VS-02: Add posts to vector store
  TC-VS-03: Semantic search returns results
  TC-VS-04: Platform metadata filtering
  TC-VS-05: Short/empty text is skipped
  TC-VS-06: Sync from SQLite database
"""

import pytest
from datetime import datetime

from stock_rag.database import Database, Platform
from stock_rag.vector_store import VectorStore, HAS_CHROMADB


pytestmark = pytest.mark.skipif(
    not HAS_CHROMADB, reason="chromadb not installed"
)


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def vs(tmp_path):
    store = VectorStore(persist_dir=str(tmp_path / "chroma_test"))
    return store


@pytest.fixture
def sample_posts():
    return [
        {"id": 1, "text": "RELIANCE breakout above 2700 resistance level. "
         "Strong volume accumulation. Target 3000.", "platform": "telegram",
         "author": "tips_channel", "posted_at": "2025-01-01", "views": 5000,
         "likes": 100, "stock_symbols": ["RELIANCE"]},
        {"id": 2, "text": "TCS quarterly results beat estimates. Revenue growth "
         "of 12%. EPS strong. Positive outlook.", "platform": "x",
         "author": "analyst_x", "posted_at": "2025-01-02", "views": 3000,
         "likes": 80, "stock_symbols": ["TCS"]},
        {"id": 3, "text": "Banking sector outlook remains strong. HDFC Bank and "
         "ICICI Bank fundamentals solid.", "platform": "linkedin",
         "author": "expert", "posted_at": "2025-01-03", "views": 2000,
         "likes": 60, "stock_symbols": ["HDFCBANK", "ICICIBANK"]},
    ]


# ──────────────────────────────────────────────────────────────────────
# TC-VS-01: Collection creation
# ──────────────────────────────────────────────────────────────────────

class TestCollectionCreation:
    """TC-VS-01: Vector store collection is created properly."""

    def test_collection_exists(self, vs):
        assert vs.collection is not None
        assert vs.collection.name == "stock_posts"

    def test_collection_empty_initially(self, vs):
        assert vs.collection.count() == 0


# ──────────────────────────────────────────────────────────────────────
# TC-VS-02: Add posts
# ──────────────────────────────────────────────────────────────────────

class TestAddPosts:
    """TC-VS-02: Posts are embedded and stored correctly."""

    def test_add_posts(self, vs, sample_posts):
        count = vs.add_posts(sample_posts)
        assert count == 3
        assert vs.collection.count() == 3

    def test_upsert_no_duplicate(self, vs, sample_posts):
        """Upserting same posts twice doesn't create duplicates."""
        vs.add_posts(sample_posts)
        vs.add_posts(sample_posts)
        assert vs.collection.count() == 3

    def test_add_empty_list(self, vs):
        count = vs.add_posts([])
        assert count == 0


# ──────────────────────────────────────────────────────────────────────
# TC-VS-03: Semantic search
# ──────────────────────────────────────────────────────────────────────

class TestSemanticSearch:
    """TC-VS-03: Search returns semantically relevant results."""

    def test_search_returns_results(self, vs, sample_posts):
        vs.add_posts(sample_posts)
        results = vs.search("Reliance stock breakout", n_results=3)
        assert len(results) >= 1
        # The RELIANCE post should be most relevant
        assert any("RELIANCE" in r.get("text", "").upper() or
                    "reliance" in r.get("text", "").lower() for r in results)

    def test_search_banking(self, vs, sample_posts):
        vs.add_posts(sample_posts)
        results = vs.search("banking sector outlook", n_results=3)
        assert len(results) >= 1

    def test_search_result_structure(self, vs, sample_posts):
        vs.add_posts(sample_posts)
        results = vs.search("stock market", n_results=1)
        if results:
            r = results[0]
            assert "id" in r
            assert "text" in r
            assert "metadata" in r
            assert "distance" in r


# ──────────────────────────────────────────────────────────────────────
# TC-VS-04: Platform filtering
# ──────────────────────────────────────────────────────────────────────

class TestPlatformFiltering:
    """TC-VS-04: Filter search results by platform metadata."""

    def test_filter_by_platform(self, vs, sample_posts):
        vs.add_posts(sample_posts)
        results = vs.search("stock analysis", n_results=10,
                           platform="telegram")
        # All results should be from telegram platform
        for r in results:
            assert r["metadata"].get("platform") == "telegram"


# ──────────────────────────────────────────────────────────────────────
# TC-VS-05: Short/empty text skipping
# ──────────────────────────────────────────────────────────────────────

class TestShortTextSkipping:
    """TC-VS-05: Short or empty texts are filtered out."""

    def test_skips_short_text(self, vs):
        posts = [
            {"id": 10, "text": "Hi", "platform": "x"},
            {"id": 11, "text": "", "platform": "x"},
            {"id": 12, "text": "Normal length post about RELIANCE breakout above key level",
             "platform": "x"},
        ]
        count = vs.add_posts(posts)
        assert count == 1  # Only post 12 should be added

    def test_skips_no_id(self, vs):
        posts = [{"text": "Valid text but no id field provided", "platform": "x"}]
        count = vs.add_posts(posts)
        assert count == 0


# ──────────────────────────────────────────────────────────────────────
# TC-VS-06: Sync from DB
# ──────────────────────────────────────────────────────────────────────

class TestSyncFromDB:
    """TC-VS-06: Sync stock-relevant posts from SQLite to ChromaDB."""

    def test_sync_from_db(self, vs, tmp_path):
        db = Database(str(tmp_path / "sync_test.db"))
        source = db.upsert_source(Platform.TELEGRAM, "@sync_test")
        post = db.insert_raw_post({
            "source_id": source.id,
            "platform": Platform.TELEGRAM,
            "external_id": "sync_1",
            "text": "RELIANCE breakout confirmed above resistance with strong volume",
            "text_clean": "RELIANCE breakout confirmed above resistance with strong volume",
            "author": "@tips",
            "posted_at": datetime.utcnow(),
            "views": 1000,
            "likes": 50,
        })
        db.mark_post_processed(post.id, is_stock_relevant=True)

        count = vs.sync_from_db(db)
        assert count >= 1
        assert vs.collection.count() >= 1
        db.engine.dispose()
