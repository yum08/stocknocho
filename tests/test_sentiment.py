"""
Test suite for StockRAG Sentiment Analyzer (sentiment.py)
==========================================================

Tests the rule-based sentiment scorer, negation handling,
Indian market slang, and signal aggregation.

Test Categories:
  TC-SA-01: Bullish sentiment detection
  TC-SA-02: Bearish sentiment detection
  TC-SA-03: Neutral sentiment
  TC-SA-04: Negation handling ("not bullish" → bearish)
  TC-SA-05: Indian market slang recognition
  TC-SA-06: Sentiment score range validation
  TC-SA-07: Confidence scaling with signal count
  TC-SA-08: Empty / edge-case input
  TC-SA-09: SignalAggregator.analyze_mentions
  TC-SA-10: SignalAggregator.generate_signals & classify_signal
"""

import pytest
from datetime import datetime, timedelta

from stock_rag.database import (
    Database, Platform, SentimentLabel, SignalStrength, AnalysisType,
)
from stock_rag.sentiment import (
    SentimentAnalyzer, SignalAggregator,
    BULLISH_WORDS, BEARISH_WORDS, NEGATORS,
)
from stock_rag.stock_identifier import StockIdentifier


# ──────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def analyzer():
    return SentimentAnalyzer()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_sa.db")
    database = Database(db_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def populated_db(db):
    """DB with source, posts, stocks, and mentions for aggregation tests."""
    source = db.upsert_source(Platform.TELEGRAM, "@test_sa")
    stock = db.upsert_stock("RELIANCE", "Reliance Industries", "NSE",
                            aliases=["RIL"], sector="Oil & Gas")

    si = StockIdentifier(db)
    si.initialize(seed_stocks=True)

    # Insert bullish posts
    bullish_texts = [
        "RELIANCE breakout above 2700! Strong buy. Target 3000. Multibagger!",
        "RIL rally continues. Bullish on daily chart. Accumulate on dips.",
        "Reliance is on fire! Rocket to moon! All time high incoming!",
    ]
    # Insert bearish posts
    bearish_texts = [
        "Avoid RELIANCE. Weak results. Sell on bounce. Breakdown below support.",
        "RIL crash incoming. Scam exposed. Dump immediately. Panic selling.",
    ]

    for i, text in enumerate(bullish_texts + bearish_texts):
        post = db.insert_raw_post({
            "source_id": source.id,
            "platform": Platform.TELEGRAM,
            "external_id": f"sa_{i}",
            "text": text,
            "posted_at": datetime.utcnow() - timedelta(hours=i),
        })

    si.process_unprocessed_posts()
    return db, stock


# ──────────────────────────────────────────────────────────────────────
# TC-SA-01: Bullish sentiment detection
# ──────────────────────────────────────────────────────────────────────

class TestBullishSentiment:
    """TC-SA-01: Correctly identify bullish text."""

    def test_strong_bullish(self, analyzer):
        result = analyzer.analyze(
            "RELIANCE breakout above resistance! Strong buy! Rocket to moon! "
            "Target 3000. Multibagger potential. Accumulate on every dip."
        )
        assert result["score"] > 0.5
        assert result["label"] in (SentimentLabel.VERY_BULLISH,
                                    SentimentLabel.BULLISH)
        assert len(result["bullish_signals"]) > 0

    def test_moderate_bullish(self, analyzer):
        result = analyzer.analyze("Looking bullish. Buy on dips. Upside expected.")
        assert result["score"] > 0
        assert result["label"] in (SentimentLabel.BULLISH,
                                    SentimentLabel.VERY_BULLISH)

    def test_bullish_signals_returned(self, analyzer):
        result = analyzer.analyze("Strong buy! Breakout confirmed. Rally expected.")
        assert "strong buy" in result["bullish_signals"]
        assert "breakout" in result["bullish_signals"]


# ──────────────────────────────────────────────────────────────────────
# TC-SA-02: Bearish sentiment detection
# ──────────────────────────────────────────────────────────────────────

class TestBearishSentiment:
    """TC-SA-02: Correctly identify bearish text."""

    def test_strong_bearish(self, analyzer):
        result = analyzer.analyze(
            "Avoid HDFC Bank! Weak results. Crash expected. "
            "Breakdown below support. Strong sell. Dump this stock."
        )
        assert result["score"] < -0.3
        assert result["label"] in (SentimentLabel.BEARISH,
                                    SentimentLabel.VERY_BEARISH)

    def test_bearish_signals_returned(self, analyzer):
        result = analyzer.analyze("Crash likely. Avoid. Sell immediately.")
        assert "crash" in result["bearish_signals"]
        assert "avoid" in result["bearish_signals"]
        assert "sell" in result["bearish_signals"]


# ──────────────────────────────────────────────────────────────────────
# TC-SA-03: Neutral sentiment
# ──────────────────────────────────────────────────────────────────────

class TestNeutralSentiment:
    """TC-SA-03: Neutral text produces near-zero score."""

    def test_neutral_text(self, analyzer):
        result = analyzer.analyze(
            "Company announced quarterly results. Revenue was in line with estimates."
        )
        assert -0.3 <= result["score"] <= 0.3

    def test_mixed_signals_near_neutral(self, analyzer):
        """Equal bullish and bearish signals → near neutral."""
        result = analyzer.analyze(
            "Buy on dips but sell on rallies. Bullish chart but bearish fundamentals."
        )
        assert -0.5 <= result["score"] <= 0.5


# ──────────────────────────────────────────────────────────────────────
# TC-SA-04: Negation handling
# ──────────────────────────────────────────────────────────────────────

class TestNegation:
    """TC-SA-04: Negators flip sentiment correctly."""

    def test_not_bullish(self, analyzer):
        """'not bullish' should register as bearish signal."""
        result = analyzer.analyze("This stock is not bullish at all.")
        assert "NOT bullish" in result["bearish_signals"]

    def test_not_bearish(self, analyzer):
        """'not bearish' should register as bullish signal."""
        result = analyzer.analyze("Don't be bearish on this stock.")
        # Negation of bearish → bullish
        assert any("NOT" in s for s in result["bullish_signals"])


# ──────────────────────────────────────────────────────────────────────
# TC-SA-05: Indian market slang
# ──────────────────────────────────────────────────────────────────────

class TestIndianMarketSlang:
    """TC-SA-05: Recognize Indian market-specific terminology."""

    def test_upper_circuit(self, analyzer):
        result = analyzer.analyze("Stock hit upper circuit! UC locked!")
        assert result["score"] > 0
        assert "upper circuit" in result["bullish_signals"]

    def test_lower_circuit(self, analyzer):
        result = analyzer.analyze("Lower circuit hit. LC for 3 days straight.")
        assert result["score"] < 0
        assert "lower circuit" in result["bearish_signals"]

    def test_fii_buying(self, analyzer):
        result = analyzer.analyze("FII buying in this stock is strong")
        assert "fii buying" in result["bullish_signals"]

    def test_operator_selling(self, analyzer):
        result = analyzer.analyze("Operator selling happening in this stock")
        assert "operator selling" in result["bearish_signals"]


# ──────────────────────────────────────────────────────────────────────
# TC-SA-06: Score range validation
# ──────────────────────────────────────────────────────────────────────

class TestScoreRange:
    """TC-SA-06: Score always within [-1, +1], confidence within [0, 1]."""

    @pytest.mark.parametrize("text", [
        "Rocket moon multibagger breakout strong buy accumulate rally surge",
        "Crash scam fraud avoid strong sell dump panic",
        "The weather is nice",
        "",
    ])
    def test_score_bounds(self, analyzer, text):
        result = analyzer.analyze(text)
        assert -1.0 <= result["score"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0


# ──────────────────────────────────────────────────────────────────────
# TC-SA-07: Confidence scaling
# ──────────────────────────────────────────────────────────────────────

class TestConfidenceScaling:
    """TC-SA-07: More signals → higher confidence."""

    def test_low_signal_low_confidence(self, analyzer):
        result = analyzer.analyze("Maybe buy")
        assert result["confidence"] < 0.5

    def test_high_signal_high_confidence(self, analyzer):
        result = analyzer.analyze(
            "Strong buy! Breakout! Target! Rally! Surge! Rocket! Moon! "
            "Accumulate! Bullish! Upside! Multibagger!"
        )
        assert result["confidence"] >= 0.8


# ──────────────────────────────────────────────────────────────────────
# TC-SA-08: Empty / edge-case input
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """TC-SA-08: Handle empty, None, and special inputs."""

    def test_empty_string(self, analyzer):
        result = analyzer.analyze("")
        assert result["score"] == 0.0
        assert result["label"] == SentimentLabel.NEUTRAL
        assert result["confidence"] == 0.0

    def test_none_input(self, analyzer):
        """None should be handled gracefully."""
        result = analyzer.analyze(None)
        assert result["score"] == 0.0

    def test_numbers_only(self, analyzer):
        result = analyzer.analyze("123 456 789")
        assert result["label"] == SentimentLabel.NEUTRAL

    def test_word_lists_not_empty(self):
        """Verify bullish/bearish dictionaries have entries."""
        assert len(BULLISH_WORDS) > 20
        assert len(BEARISH_WORDS) > 20
        assert len(NEGATORS) > 3


# ──────────────────────────────────────────────────────────────────────
# TC-SA-09: SignalAggregator.analyze_mentions
# ──────────────────────────────────────────────────────────────────────

class TestAnalyzeMentions:
    """TC-SA-09: Sentiment analysis runs on stock mentions."""

    def test_analyze_mentions(self, populated_db):
        db, stock = populated_db
        aggregator = SignalAggregator(db)
        count = aggregator.analyze_mentions()
        assert count >= 3  # At least some mentions should get analyzed


# ──────────────────────────────────────────────────────────────────────
# TC-SA-10: Signal generation & classification
# ──────────────────────────────────────────────────────────────────────

class TestSignalGeneration:
    """TC-SA-10: Aggregated signal generation from mentions."""

    def test_generate_signals(self, populated_db):
        db, stock = populated_db
        aggregator = SignalAggregator(db)
        # First analyze mentions
        aggregator.analyze_mentions()
        # Then generate signals
        signals = aggregator.generate_signals(window_hours=72)
        assert len(signals) >= 1

    def test_signal_has_required_fields(self, populated_db):
        db, stock = populated_db
        aggregator = SignalAggregator(db)
        aggregator.analyze_mentions()
        signals = aggregator.generate_signals(window_hours=72)
        if signals:
            sig = signals[0]
            assert sig.total_mentions > 0
            assert sig.avg_sentiment is not None
            assert sig.signal_strength is not None
            assert sig.predicted_direction in ("up", "down", "flat")

    def test_classify_strong_buy(self):
        """Strong buy: high avg sentiment, bullish >> bearish."""
        agg = SignalAggregator.__new__(SignalAggregator)
        strength, direction, magnitude = agg._classify_signal(
            avg_sent=0.7, std=0.1, count=15, bullish=12, bearish=3
        )
        assert strength == SignalStrength.STRONG_BUY
        assert direction == "up"

    def test_classify_strong_sell(self):
        """Strong sell: very negative sentiment, bearish >> bullish."""
        agg = SignalAggregator.__new__(SignalAggregator)
        strength, direction, magnitude = agg._classify_signal(
            avg_sent=-0.7, std=0.1, count=15, bullish=2, bearish=13
        )
        assert strength == SignalStrength.STRONG_SELL
        assert direction == "down"

    def test_classify_hold(self):
        """Near-zero sentiment → HOLD."""
        agg = SignalAggregator.__new__(SignalAggregator)
        strength, direction, magnitude = agg._classify_signal(
            avg_sent=0.05, std=0.3, count=10, bullish=5, bearish=5
        )
        assert strength == SignalStrength.HOLD
        assert direction == "flat"
