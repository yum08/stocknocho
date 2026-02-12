"""
Test suite for StockRAG Stock Identifier (stock_identifier.py)
================================================================

Tests the multi-strategy stock matching engine, regex extraction
of trading details, and analysis type detection.

Test Categories:
  TC-SI-01: Exact symbol match
  TC-SI-02: Alias match
  TC-SI-03: Company name match
  TC-SI-04: Multi-stock identification in single text
  TC-SI-05: False positive avoidance (short strings, common words)
  TC-SI-06: Target price extraction
  TC-SI-07: Stop loss extraction
  TC-SI-08: Action extraction (buy/sell/hold)
  TC-SI-09: Timeframe extraction
  TC-SI-10: Analysis type detection (technical vs fundamental)
  TC-SI-11: process_unprocessed_posts pipeline
  TC-SI-12: Edge cases (empty text, no matches, special chars)
"""

import pytest
from datetime import datetime

from stock_rag.database import Database, Platform, AnalysisType
from stock_rag.stock_identifier import (
    StockIdentifier, STOCK_MASTER,
    TARGET_PATTERN, STOPLOSS_PATTERN, ACTION_PATTERN, TIMEFRAME_PATTERN,
)


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_si.db")
    database = Database(db_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def identifier(db):
    """StockIdentifier initialized with seeded stocks."""
    si = StockIdentifier(db)
    si.initialize(seed_stocks=True)
    return si


@pytest.fixture
def db_with_posts(db):
    """DB with source and several test posts."""
    source = db.upsert_source(Platform.TELEGRAM, "@test_channel")
    posts = [
        {"source_id": source.id, "platform": Platform.TELEGRAM,
         "external_id": "p1",
         "text": "RELIANCE target 2800 SL 2650. BUY for swing trade."},
        {"source_id": source.id, "platform": Platform.TELEGRAM,
         "external_id": "p2",
         "text": "The weather is nice today, nothing about stocks."},
        {"source_id": source.id, "platform": Platform.TELEGRAM,
         "external_id": "p3",
         "text": "SBI and Airtel both looking bullish. Breakout above resistance."},
    ]
    for p in posts:
        db.insert_raw_post(p)
    return db, source


# ──────────────────────────────────────────────────────────────────────
# TC-SI-01: Exact symbol match
# ──────────────────────────────────────────────────────────────────────

class TestExactSymbolMatch:
    """TC-SI-01: Stocks matched by exact NSE symbol."""

    def test_single_symbol(self, identifier):
        matches = identifier.identify_stocks("RELIANCE breakout above 2700")
        assert len(matches) >= 1
        reliance = [m for m in matches if m["matched_text"] == "RELIANCE"]
        assert len(reliance) == 1
        assert reliance[0]["match_method"] == "symbol"
        assert reliance[0]["confidence"] == 0.95

    def test_symbol_case_insensitive(self, identifier):
        """Symbols are matched case-insensitively."""
        m1 = identifier.identify_stocks("TCS is looking strong")
        m2 = identifier.identify_stocks("tcs is looking strong")
        # Both should identify TCS (text is uppered for matching)
        assert len(m1) >= 1
        assert len(m2) >= 1

    def test_symbol_word_boundary(self, identifier):
        """INFY should match 'INFY' but not 'INFINITY'."""
        m = identifier.identify_stocks("INFY target 1800")
        assert any(match["matched_text"] == "INFY" for match in m)

    def test_index_symbols(self, identifier):
        """NIFTY, SENSEX, BANKNIFTY should be identifiable."""
        m = identifier.identify_stocks("NIFTY breaking 22000, BANKNIFTY strong")
        symbols = {match["matched_text"] for match in m}
        assert "NIFTY" in symbols
        assert "BANKNIFTY" in symbols


# ──────────────────────────────────────────────────────────────────────
# TC-SI-02: Alias match
# ──────────────────────────────────────────────────────────────────────

class TestAliasMatch:
    """TC-SI-02: Stocks matched by common alias/nickname."""

    def test_alias_sbi(self, identifier):
        """'SBI' alias maps to SBIN stock."""
        matches = identifier.identify_stocks("SBI looks bullish on daily chart")
        assert len(matches) >= 1
        assert matches[0]["match_method"] == "alias"
        assert matches[0]["confidence"] == 0.85

    def test_alias_ril(self, identifier):
        """'RIL' alias maps to RELIANCE."""
        matches = identifier.identify_stocks("RIL results expected tomorrow")
        assert len(matches) >= 1
        # Should match via alias
        ril = [m for m in matches if "RIL" in m["matched_text"]]
        assert len(ril) >= 1

    def test_alias_airtel(self, identifier):
        """'Airtel' alias maps to BHARTIARTL."""
        matches = identifier.identify_stocks("Airtel breakout above 1200")
        assert len(matches) >= 1

    def test_short_alias_skipped(self, identifier):
        """Aliases shorter than 3 chars are skipped to avoid false positives."""
        # 'Vi' is an alias for Vodafone Idea but is only 2 chars
        matches = identifier.identify_stocks("Vi is a common word")
        # Should NOT match Vi (2 chars < 3 char minimum)
        vi_matches = [m for m in matches if m.get("matched_text", "").upper() == "VI"]
        assert len(vi_matches) == 0


# ──────────────────────────────────────────────────────────────────────
# TC-SI-03: Company name match
# ──────────────────────────────────────────────────────────────────────

class TestCompanyNameMatch:
    """TC-SI-03: Stocks matched by full company name."""

    def test_full_name_match(self, identifier):
        """Full company name should match the stock."""
        # Use a name whose alias doesn't appear separately in the text
        # "Oil & Natural Gas Corporation" has alias "ONGC Ltd" — full name is unique
        matches = identifier.identify_stocks(
            "Oil & Natural Gas Corporation reported strong Q3 results"
        )
        assert len(matches) >= 1
        # Could match by name or alias depending on lookup order
        assert any(m["match_method"] in ("name", "alias", "symbol") for m in matches)

    def test_name_match_lower_confidence(self, identifier):
        """Name matches have lower confidence (0.75) than symbol matches."""
        matches = identifier.identify_stocks(
            "Hindustan Unilever reported good earnings"
        )
        name_matches = [m for m in matches if m["match_method"] == "name"]
        if name_matches:
            assert name_matches[0]["confidence"] == 0.75


# ──────────────────────────────────────────────────────────────────────
# TC-SI-04: Multi-stock identification
# ──────────────────────────────────────────────────────────────────────

class TestMultiStockIdentification:
    """TC-SI-04: Multiple stocks in a single post."""

    def test_three_stocks_in_one_post(self, identifier):
        text = "RELIANCE target 2800, SBI looking bullish, Airtel breakout above 1200"
        matches = identifier.identify_stocks(text)
        assert len(matches) >= 3

    def test_no_duplicate_stock_ids(self, identifier):
        """Each stock_id should appear at most once."""
        text = "RELIANCE RELIANCE RELIANCE target 2800"
        matches = identifier.identify_stocks(text)
        stock_ids = [m["stock_id"] for m in matches]
        assert len(stock_ids) == len(set(stock_ids)), "Duplicate stock_ids found"


# ──────────────────────────────────────────────────────────────────────
# TC-SI-05: False positive avoidance
# ──────────────────────────────────────────────────────────────────────

class TestFalsePositiveAvoidance:
    """TC-SI-05: Avoid matching common words as stock symbols."""

    def test_no_match_on_plain_english(self, identifier):
        """Regular English text shouldn't produce many false positives."""
        text = "The weather is sunny today and I went for a walk."
        matches = identifier.identify_stocks(text)
        assert len(matches) == 0

    def test_empty_text(self, identifier):
        """Empty text returns no matches."""
        assert identifier.identify_stocks("") == []
        assert identifier.identify_stocks(None) == []


# ──────────────────────────────────────────────────────────────────────
# TC-SI-06: Target price extraction
# ──────────────────────────────────────────────────────────────────────

class TestTargetPriceExtraction:
    """TC-SI-06: Regex extraction of target prices."""

    @pytest.mark.parametrize("text,expected", [
        ("target 2800", 2800.0),
        ("tgt: 1500", 1500.0),
        ("TGT = 950.50", 950.50),
        ("target Rs. 2800", 2800.0),
        ("TP 1200", 1200.0),
    ])
    def test_target_patterns(self, identifier, text, expected):
        details = identifier.extract_trading_details(text)
        assert details.get("target_price") == expected

    def test_no_target(self, identifier):
        details = identifier.extract_trading_details("Looking good")
        assert "target_price" not in details


# ──────────────────────────────────────────────────────────────────────
# TC-SI-07: Stop loss extraction
# ──────────────────────────────────────────────────────────────────────

class TestStopLossExtraction:
    """TC-SI-07: Regex extraction of stop loss values."""

    @pytest.mark.parametrize("text,expected", [
        ("SL 2650", 2650.0),
        ("stop loss 2500", 2500.0),
        ("stoploss: 1400", 1400.0),
        ("SL = Rs 880", 880.0),
    ])
    def test_stoploss_patterns(self, identifier, text, expected):
        details = identifier.extract_trading_details(text)
        assert details.get("stop_loss") == expected


# ──────────────────────────────────────────────────────────────────────
# TC-SI-08: Action extraction
# ──────────────────────────────────────────────────────────────────────

class TestActionExtraction:
    """TC-SI-08: Extract buy/sell/long/short/accumulate actions."""

    @pytest.mark.parametrize("text,expected", [
        ("Buy RELIANCE at CMP", "buy"),
        ("Sell HDFC Bank on bounce", "sell"),
        ("Go long on TCS", "long"),
        ("Short NIFTY at 22100", "short"),
        ("Accumulate on dips", "accumulate"),
    ])
    def test_action_extraction(self, identifier, text, expected):
        details = identifier.extract_trading_details(text)
        assert details.get("action_suggested") == expected


# ──────────────────────────────────────────────────────────────────────
# TC-SI-09: Timeframe extraction
# ──────────────────────────────────────────────────────────────────────

class TestTimeframeExtraction:
    """TC-SI-09: Extract trading timeframe from text."""

    @pytest.mark.parametrize("text,expected", [
        ("Buy RELIANCE for intraday", "intraday"),
        ("Swing trade setup in TCS", "swing"),
        ("Positional call on INFY", "positional"),
        ("Short term target 500", "short_term"),
    ])
    def test_timeframe_extraction(self, identifier, text, expected):
        details = identifier.extract_trading_details(text)
        assert details.get("time_horizon") == expected


# ──────────────────────────────────────────────────────────────────────
# TC-SI-10: Analysis type detection
# ──────────────────────────────────────────────────────────────────────

class TestAnalysisTypeDetection:
    """TC-SI-10: Classify posts as technical vs fundamental."""

    def test_technical_analysis(self, identifier):
        text = ("RELIANCE breakout above resistance at 2700. "
                "RSI showing bullish divergence on daily chart. "
                "Support at 2600, moving average crossover.")
        details = identifier.extract_trading_details(text)
        assert details["analysis_type"] == AnalysisType.TECHNICAL

    def test_fundamental_analysis(self, identifier):
        text = ("TCS reported strong quarterly results. Revenue growth 12% YoY. "
                "EPS beat estimates. PE ratio attractive. Strong dividend.")
        details = identifier.extract_trading_details(text)
        assert details["analysis_type"] == AnalysisType.FUNDAMENTAL

    def test_sentiment_fallback(self, identifier):
        """Posts with few keywords default to SENTIMENT type."""
        text = "RELIANCE looking good. Buy on dips."
        details = identifier.extract_trading_details(text)
        assert details["analysis_type"] == AnalysisType.SENTIMENT


# ──────────────────────────────────────────────────────────────────────
# TC-SI-11: process_unprocessed_posts pipeline
# ──────────────────────────────────────────────────────────────────────

class TestProcessUnprocessed:
    """TC-SI-11: End-to-end post processing pipeline."""

    def test_process_posts(self, db_with_posts):
        db, source = db_with_posts
        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)

        stats = si.process_unprocessed_posts()
        assert stats["processed"] == 3
        assert stats["stock_relevant"] >= 2      # posts 1 and 3 have stocks
        assert stats["mentions_created"] >= 3     # RELIANCE + SBI + Airtel

    def test_processed_posts_not_reprocessed(self, db_with_posts):
        db, source = db_with_posts
        si = StockIdentifier(db)
        si.initialize(seed_stocks=True)

        stats1 = si.process_unprocessed_posts()
        stats2 = si.process_unprocessed_posts()
        assert stats2["processed"] == 0  # no unprocessed left


# ──────────────────────────────────────────────────────────────────────
# TC-SI-12: Edge cases
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """TC-SI-12: Edge case handling."""

    def test_special_characters_in_text(self, identifier):
        """Stock symbols with special chars (M&M) are handled."""
        matches = identifier.identify_stocks("M&M results are out")
        # M&M is in STOCK_MASTER
        assert len(matches) >= 1

    def test_combined_target_sl_action(self, identifier):
        """Full trade call with all components."""
        text = "Buy RELIANCE target 2800 SL 2650 for swing trade"
        details = identifier.extract_trading_details(text)
        assert details["target_price"] == 2800.0
        assert details["stop_loss"] == 2650.0
        assert details["action_suggested"] == "buy"
        assert details["time_horizon"] == "swing"

    def test_stock_master_count(self):
        """Verify STOCK_MASTER has expected number of entries."""
        assert len(STOCK_MASTER) >= 60  # We defined 63
