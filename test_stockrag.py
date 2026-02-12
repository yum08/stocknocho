"""Quick integration test for StockRAG system."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_rag.database import Database, Platform
from stock_rag.stock_identifier import StockIdentifier
from stock_rag.sentiment import SentimentAnalyzer

# Test 1: Create database
db = Database('test_stockrag.db')
print("DB created:", db.get_stats())

# Test 2: Stock identifier
identifier = StockIdentifier(db)
identifier.initialize(seed_stocks=True)
print("Stocks seeded:", db.get_stats()['stocks'])

# Test 3: Stock identification
text = "RELIANCE target 2800, SBI looking bullish, Airtel breakout above 1200"
matches = identifier.identify_stocks(text)
print(f"Matches found: {len(matches)}")
for m in matches:
    print(f"  {m['matched_text']} -> stock_id={m['stock_id']} via {m['match_method']} (conf={m['confidence']})")

# Test 4: Trading details extraction
details = identifier.extract_trading_details("Buy RELIANCE target 2800 SL 2650 for swing trade")
print("Trading details:", details)

# Test 5: Sentiment analysis
analyzer = SentimentAnalyzer()
result = analyzer.analyze("RELIANCE breakout above resistance, strong volume, target 3000. Very bullish. Accumulate on dips.")
print(f"Sentiment: {result['label'].value} score={result['score']} conf={result['confidence']}")

# Test 6: Bearish sentiment
result2 = analyzer.analyze("Avoid HDFC Bank, weak results, sell on bounce. Breakdown below support.")
print(f"Sentiment: {result2['label'].value} score={result2['score']}")

# Cleanup
try:
    db.engine.dispose()
    os.remove('test_stockrag.db')
except Exception:
    pass
print("\nAll tests passed!")
