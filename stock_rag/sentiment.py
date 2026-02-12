"""
Sentiment & Analysis Engine
=============================

Performs:
1. Rule-based sentiment scoring (fast, no API needed)
2. LLM-based sentiment analysis (via Gemini/OpenAI for deeper analysis)
3. Technical/Fundamental keyword extraction
4. Aggregated signal generation per stock per time window
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import statistics

from .database import (
    Database, StockMention, StockSignal, RawPost,
    SentimentLabel, SignalStrength, AnalysisType
)


# ──────────────────────────────────────────────────────────────────────
# RULE-BASED SENTIMENT ANALYZER
# ──────────────────────────────────────────────────────────────────────

# Bullish/Bearish word lists tuned for Indian stock market social media
BULLISH_WORDS = {
    # Strong bullish
    'rocket': 2, 'moon': 2, 'multibagger': 2, 'breakout': 1.5,
    'strong buy': 2, 'must buy': 2, 'accumulate': 1.5, 'outperform': 1.5,
    # Moderate bullish
    'buy': 1, 'bullish': 1.5, 'long': 1, 'upside': 1, 'target': 0.8,
    'positive': 1, 'growth': 0.8, 'rally': 1.2, 'surge': 1.2,
    'rising': 0.8, 'uptrend': 1, 'bounce': 0.8, 'recovery': 0.8,
    'all time high': 1.5, 'ath': 1.2, 'new high': 1.2,
    'golden cross': 1.5, 'gap up': 1, 'green': 0.5,
    'outperformer': 1.2, 'undervalued': 1.2, 'cheap': 0.8,
    'double': 1.5, 'triple': 2, '52 week high': 1,
    # Hinglish / Indian market slang
    'upper circuit': 1.5, 'uc': 1, 'operator buying': 1.2,
    'fii buying': 1.2, 'dii buying': 1, 'bulk deal': 0.8,
}

BEARISH_WORDS = {
    # Strong bearish
    'crash': -2, 'scam': -2, 'fraud': -2, 'avoid': -1.5,
    'strong sell': -2, 'dump': -1.5, 'panic': -1.5,
    # Moderate bearish
    'sell': -1, 'bearish': -1.5, 'short': -1, 'downside': -1,
    'negative': -1, 'decline': -0.8, 'fall': -0.8, 'drop': -0.8,
    'falling': -0.8, 'downtrend': -1, 'breakdown': -1.2,
    'weak': -0.8, 'correction': -0.5, 'pullback': -0.3,
    'death cross': -1.5, 'gap down': -1, 'red': -0.5,
    'overvalued': -1, 'expensive': -0.8, 'risky': -0.8,
    '52 week low': -1, 'new low': -1, 'all time low': -1.5,
    # Indian market slang
    'lower circuit': -1.5, 'lc': -1, 'operator selling': -1.2,
    'fii selling': -1.2, 'dii selling': -1, 'pledge': -0.8,
    'npa': -1, 'default': -1.5, 'sebi action': -1,
    'book profit': -0.3, 'exit': -0.5, 'stop loss hit': -1,
}

# Intensity modifiers
INTENSIFIERS = {
    'very': 1.5, 'extremely': 2, 'highly': 1.5, 'super': 1.5,
    'massive': 1.8, 'huge': 1.5, 'big': 1.3,
}

NEGATORS = ['not', "don't", "doesn't", "won't", "no", "never", "hardly"]


class SentimentAnalyzer:
    """Rule-based sentiment scoring for stock market posts."""

    def analyze(self, text: str) -> Dict:
        """
        Analyze sentiment of a text.
        Returns: {score, label, confidence, bullish_signals, bearish_signals}
        """
        if not text:
            return {
                'score': 0.0,
                'label': SentimentLabel.NEUTRAL,
                'confidence': 0.0,
                'bullish_signals': [],
                'bearish_signals': [],
            }

        text_lower = text.lower()

        bullish_score = 0
        bearish_score = 0
        bullish_signals = []
        bearish_signals = []

        # Check multi-word phrases first
        for phrase, weight in BULLISH_WORDS.items():
            if phrase in text_lower:
                # Check for negation
                negated = self._is_negated(text_lower, phrase)
                if negated:
                    bearish_score += abs(weight) * 0.7
                    bearish_signals.append(f"NOT {phrase}")
                else:
                    bullish_score += weight
                    bullish_signals.append(phrase)

        for phrase, weight in BEARISH_WORDS.items():
            if phrase in text_lower:
                negated = self._is_negated(text_lower, phrase)
                if negated:
                    bullish_score += abs(weight) * 0.7
                    bullish_signals.append(f"NOT {phrase}")
                else:
                    bearish_score += abs(weight)
                    bearish_signals.append(phrase)

        # Calculate final score (-1 to +1)
        total = bullish_score + bearish_score
        if total == 0:
            score = 0.0
            confidence = 0.0
        else:
            score = (bullish_score - bearish_score) / (bullish_score + bearish_score)
            confidence = min(1.0, total / 5.0)  # More signals = more confident

        # Map to label
        if score > 0.5:
            label = SentimentLabel.VERY_BULLISH
        elif score > 0.1:
            label = SentimentLabel.BULLISH
        elif score < -0.5:
            label = SentimentLabel.VERY_BEARISH
        elif score < -0.1:
            label = SentimentLabel.BEARISH
        else:
            label = SentimentLabel.NEUTRAL

        return {
            'score': round(score, 3),
            'label': label,
            'confidence': round(confidence, 3),
            'bullish_signals': bullish_signals,
            'bearish_signals': bearish_signals,
        }

    def _is_negated(self, text: str, phrase: str) -> bool:
        """Check if a phrase is preceded by a negator within 3 words."""
        idx = text.find(phrase)
        if idx <= 0:
            return False
        preceding = text[max(0, idx - 30):idx].split()
        return any(neg in preceding[-3:] for neg in NEGATORS) if preceding else False


# ──────────────────────────────────────────────────────────────────────
# SIGNAL AGGREGATOR
# ──────────────────────────────────────────────────────────────────────

class SignalAggregator:
    """
    Aggregates individual post sentiments into stock-level signals.
    Creates entries in the stock_signals table.
    """

    def __init__(self, db: Database):
        self.db = db
        self.sentiment_analyzer = SentimentAnalyzer()

    def analyze_mentions(self, batch_size: int = 500) -> int:
        """
        Run sentiment analysis on stock mentions that don't have sentiment yet.
        Returns count of mentions analyzed.
        """
        session = self.db.get_session()
        try:
            # Get mentions without sentiment
            mentions = session.query(StockMention).filter(
                StockMention.sentiment_score == None
            ).limit(batch_size).all()

            count = 0
            for mention in mentions:
                post = session.query(RawPost).get(mention.raw_post_id)
                if not post:
                    continue

                result = self.sentiment_analyzer.analyze(post.text or "")
                mention.sentiment_score = result['score']
                mention.sentiment_label = result['label']
                count += 1

            session.commit()
            return count
        finally:
            session.close()

    def generate_signals(self, window_hours: int = 24) -> List[StockSignal]:
        """
        Generate aggregated signals for each stock based on recent mentions.
        Groups mentions by stock within the time window and computes stats.
        """
        session = self.db.get_session()
        try:
            window_start = datetime.utcnow() - timedelta(hours=window_hours)
            window_end = datetime.utcnow()

            # Get all mentions in the window grouped by stock
            mentions = session.query(StockMention).filter(
                StockMention.created_at >= window_start
            ).all()

            # Group by stock
            by_stock: Dict[int, List[StockMention]] = defaultdict(list)
            for m in mentions:
                by_stock[m.stock_id].append(m)

            signals = []
            for stock_id, stock_mentions in by_stock.items():
                signal = self._compute_signal(
                    stock_id, stock_mentions, window_start, window_end
                )
                if signal:
                    signals.append(signal)

            return signals
        finally:
            session.close()

    def _compute_signal(self, stock_id: int, mentions: List[StockMention],
                        window_start: datetime, window_end: datetime) -> Optional[StockSignal]:
        """Compute aggregated signal for one stock from its mentions."""
        if not mentions:
            return None

        scores = [m.sentiment_score for m in mentions if m.sentiment_score is not None]
        if not scores:
            return None

        # Unique sources
        source_ids = set()
        post_ids = []
        for m in mentions:
            post_ids.append(m.raw_post_id)

        avg_sentiment = statistics.mean(scores)
        sentiment_std = statistics.stdev(scores) if len(scores) > 1 else 0

        bullish = sum(1 for s in scores if s > 0.1)
        bearish = sum(1 for s in scores if s < -0.1)
        neutral = sum(1 for s in scores if -0.1 <= s <= 0.1)

        # Analysis type breakdown
        tech = sum(1 for m in mentions if m.analysis_type == AnalysisType.TECHNICAL)
        fund = sum(1 for m in mentions if m.analysis_type == AnalysisType.FUNDAMENTAL)
        news = sum(1 for m in mentions if m.analysis_type == AnalysisType.NEWS)

        # Determine signal
        signal_strength, direction, magnitude = self._classify_signal(
            avg_sentiment, sentiment_std, len(mentions), bullish, bearish
        )

        confidence = min(1.0, len(mentions) / 10) * (1 - sentiment_std)

        return self.db.insert_signal(
            stock_id=stock_id,
            window_start=window_start,
            window_end=window_end,
            total_mentions=len(mentions),
            unique_sources=len(source_ids) if source_ids else 1,
            avg_sentiment=round(avg_sentiment, 3),
            sentiment_std=round(sentiment_std, 3),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            technical_mentions=tech,
            fundamental_mentions=fund,
            news_mentions=news,
            signal_strength=signal_strength,
            confidence=round(max(0, confidence), 3),
            predicted_direction=direction,
            predicted_magnitude=round(magnitude, 2),
            rag_context_ids=post_ids[:20],  # top 20 post IDs for RAG reference
        )

    def _classify_signal(self, avg_sent: float, std: float,
                         count: int, bullish: int, bearish: int
                         ) -> Tuple[SignalStrength, str, float]:
        """Classify signal strength based on aggregated metrics."""
        # Direction
        if avg_sent > 0.5 and bullish > bearish * 2:
            return SignalStrength.STRONG_BUY, "up", abs(avg_sent) * 2
        elif avg_sent > 0.15:
            return SignalStrength.BUY, "up", abs(avg_sent) * 1.5
        elif avg_sent < -0.5 and bearish > bullish * 2:
            return SignalStrength.STRONG_SELL, "down", abs(avg_sent) * 2
        elif avg_sent < -0.15:
            return SignalStrength.SELL, "down", abs(avg_sent) * 1.5
        else:
            return SignalStrength.HOLD, "flat", 0
