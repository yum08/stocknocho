"""
Stock Identifier - Maps social media posts to NSE/BSE stocks.
==============================================================

This is the core module that takes raw posts from Level 1 DB and:
1. Scans text for stock symbols, names, aliases
2. Maps matches to the stocks table
3. Creates entries in stock_mentions (Level 2 DB)

Matching strategies (in order of confidence):
- Exact NSE/BSE symbol match (e.g. "RELIANCE", "TCS")
- ISIN match
- Company name match
- Alias/nickname match (e.g. "RIL" for Reliance)
- Contextual match via regex patterns (e.g. "Reliance target 2800")
"""

import re
from typing import List, Dict, Optional

import pandas as pd

from .database import (
    Database, AnalysisType
)


# ──────────────────────────────────────────────────────────────────────
# NSE/BSE STOCK MASTER DATA (Top 200 + easy to extend)
# ──────────────────────────────────────────────────────────────────────

# This is a starter list. You can load the full list from NSE/BSE APIs.
STOCK_MASTER = [
    # NIFTY 50 major components
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "exchange": "NSE", "aliases": ["RIL", "Reliance", "Jio parent", "Mukesh Ambani stock"], "sector": "Oil & Gas", "market_cap": "large"},
    {"symbol": "TCS", "name": "Tata Consultancy Services", "exchange": "NSE", "aliases": ["Tata Consultancy", "TCS Ltd"], "sector": "IT", "market_cap": "large"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "exchange": "NSE", "aliases": ["HDFC Bank", "HDFC"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "INFY", "name": "Infosys Ltd", "exchange": "NSE", "aliases": ["Infosys", "Infy"], "sector": "IT", "market_cap": "large"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "exchange": "NSE", "aliases": ["ICICI Bank", "ICICI"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "exchange": "NSE", "aliases": ["HUL", "Hindustan Unilever"], "sector": "FMCG", "market_cap": "large"},
    {"symbol": "SBIN", "name": "State Bank of India", "exchange": "NSE", "aliases": ["SBI", "State Bank"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "exchange": "NSE", "aliases": ["Airtel", "Bharti"], "sector": "Telecom", "market_cap": "large"},
    {"symbol": "ITC", "name": "ITC Ltd", "exchange": "NSE", "aliases": ["ITC Limited"], "sector": "FMCG", "market_cap": "large"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank", "exchange": "NSE", "aliases": ["Kotak", "Kotak Bank"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "exchange": "NSE", "aliases": ["L&T", "Larsen", "Larsen Toubro"], "sector": "Infrastructure", "market_cap": "large"},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "exchange": "NSE", "aliases": ["Axis Bank", "Axis"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "WIPRO", "name": "Wipro Ltd", "exchange": "NSE", "aliases": ["Wipro Limited"], "sector": "IT", "market_cap": "large"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "exchange": "NSE", "aliases": ["Bajaj Finance", "BajFin"], "sector": "Finance", "market_cap": "large"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "exchange": "NSE", "aliases": ["Tata Motors", "JLR", "Jaguar Land Rover parent"], "sector": "Auto", "market_cap": "large"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "exchange": "NSE", "aliases": ["Maruti Suzuki", "Maruti"], "sector": "Auto", "market_cap": "large"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd", "exchange": "NSE", "aliases": ["HCL Tech", "HCL"], "sector": "IT", "market_cap": "large"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries", "exchange": "NSE", "aliases": ["Sun Pharma", "Sun Pharmaceutical"], "sector": "Pharma", "market_cap": "large"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "exchange": "NSE", "aliases": ["Tata Steel", "TISCO"], "sector": "Metals", "market_cap": "large"},
    {"symbol": "NTPC", "name": "NTPC Ltd", "exchange": "NSE", "aliases": ["NTPC Limited"], "sector": "Power", "market_cap": "large"},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation", "exchange": "NSE", "aliases": ["Power Grid", "PGCIL"], "sector": "Power", "market_cap": "large"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "exchange": "NSE", "aliases": ["Adani Enterprise", "Adani"], "sector": "Diversified", "market_cap": "large"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports & SEZ", "exchange": "NSE", "aliases": ["Adani Ports", "APSEZ"], "sector": "Infrastructure", "market_cap": "large"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Ltd", "exchange": "NSE", "aliases": ["Asian Paints", "Asian Paint"], "sector": "Consumer", "market_cap": "large"},
    {"symbol": "COALINDIA", "name": "Coal India Ltd", "exchange": "NSE", "aliases": ["Coal India", "CIL"], "sector": "Mining", "market_cap": "large"},
    {"symbol": "DRREDDY", "name": "Dr Reddy's Laboratories", "exchange": "NSE", "aliases": ["Dr Reddy", "DRL"], "sector": "Pharma", "market_cap": "large"},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd", "exchange": "NSE", "aliases": ["Tech Mahindra", "TechM"], "sector": "IT", "market_cap": "large"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "exchange": "NSE", "aliases": ["UltraTech", "UltraTech Cement"], "sector": "Cement", "market_cap": "large"},
    {"symbol": "TITAN", "name": "Titan Company Ltd", "exchange": "NSE", "aliases": ["Titan", "Tanishq parent"], "sector": "Consumer", "market_cap": "large"},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation", "exchange": "NSE", "aliases": ["ONGC Ltd"], "sector": "Oil & Gas", "market_cap": "large"},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Ltd", "exchange": "NSE", "aliases": ["Bajaj Finserv"], "sector": "Finance", "market_cap": "large"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Ltd", "exchange": "NSE", "aliases": ["JSW Steel", "JSW"], "sector": "Metals", "market_cap": "large"},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Ltd", "exchange": "NSE", "aliases": ["Mahindra", "M&M Ltd", "Mahindra Mahindra"], "sector": "Auto", "market_cap": "large"},
    {"symbol": "NESTLEIND", "name": "Nestle India Ltd", "exchange": "NSE", "aliases": ["Nestle India", "Nestle"], "sector": "FMCG", "market_cap": "large"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank Ltd", "exchange": "NSE", "aliases": ["IndusInd Bank", "IndusInd"], "sector": "Banking", "market_cap": "large"},
    {"symbol": "CIPLA", "name": "Cipla Ltd", "exchange": "NSE", "aliases": ["Cipla Limited"], "sector": "Pharma", "market_cap": "large"},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp Ltd", "exchange": "NSE", "aliases": ["Hero Moto", "Hero MotoCorp", "Hero Honda"], "sector": "Auto", "market_cap": "large"},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation", "exchange": "NSE", "aliases": ["BPCL Ltd", "Bharat Petroleum"], "sector": "Oil & Gas", "market_cap": "large"},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Ltd", "exchange": "NSE", "aliases": ["Eicher", "Royal Enfield parent"], "sector": "Auto", "market_cap": "large"},
    {"symbol": "GRASIM", "name": "Grasim Industries Ltd", "exchange": "NSE", "aliases": ["Grasim", "Aditya Birla group"], "sector": "Diversified", "market_cap": "large"},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories", "exchange": "NSE", "aliases": ["Divis Lab", "Divi's Lab"], "sector": "Pharma", "market_cap": "large"},
    {"symbol": "BRITANNIA", "name": "Britannia Industries", "exchange": "NSE", "aliases": ["Britannia"], "sector": "FMCG", "market_cap": "large"},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise", "exchange": "NSE", "aliases": ["Apollo Hospitals", "Apollo"], "sector": "Healthcare", "market_cap": "large"},
    {"symbol": "TATACONSUM", "name": "Tata Consumer Products", "exchange": "NSE", "aliases": ["Tata Consumer", "Tata Tea"], "sector": "FMCG", "market_cap": "large"},
    {"symbol": "SBILIFE", "name": "SBI Life Insurance", "exchange": "NSE", "aliases": ["SBI Life"], "sector": "Insurance", "market_cap": "large"},
    {"symbol": "HDFCLIFE", "name": "HDFC Life Insurance", "exchange": "NSE", "aliases": ["HDFC Life"], "sector": "Insurance", "market_cap": "large"},
    # Popular mid/small caps frequently discussed on social media
    {"symbol": "ZOMATO", "name": "Zomato Ltd", "exchange": "NSE", "aliases": ["Zomato", "Blinkit parent"], "sector": "Internet", "market_cap": "large"},
    {"symbol": "PAYTM", "name": "One97 Communications (Paytm)", "exchange": "NSE", "aliases": ["Paytm", "One97"], "sector": "Fintech", "market_cap": "mid"},
    {"symbol": "IRCTC", "name": "Indian Railway Catering & Tourism", "exchange": "NSE", "aliases": ["IRCTC", "Indian Railway"], "sector": "Travel", "market_cap": "mid"},
    {"symbol": "TATAELXSI", "name": "Tata Elxsi Ltd", "exchange": "NSE", "aliases": ["Tata Elxsi"], "sector": "IT", "market_cap": "mid"},
    {"symbol": "VEDL", "name": "Vedanta Ltd", "exchange": "NSE", "aliases": ["Vedanta"], "sector": "Metals", "market_cap": "mid"},
    {"symbol": "BANKBARODA", "name": "Bank of Baroda", "exchange": "NSE", "aliases": ["BOB", "Bank of Baroda"], "sector": "Banking", "market_cap": "mid"},
    {"symbol": "PNB", "name": "Punjab National Bank", "exchange": "NSE", "aliases": ["PNB", "Punjab National"], "sector": "Banking", "market_cap": "mid"},
    {"symbol": "YESBANK", "name": "Yes Bank Ltd", "exchange": "NSE", "aliases": ["Yes Bank"], "sector": "Banking", "market_cap": "mid"},
    {"symbol": "IDEA", "name": "Vodafone Idea Ltd", "exchange": "NSE", "aliases": ["Vi", "Vodafone Idea", "Voda Idea"], "sector": "Telecom", "market_cap": "small"},
    {"symbol": "SUZLON", "name": "Suzlon Energy Ltd", "exchange": "NSE", "aliases": ["Suzlon"], "sector": "Energy", "market_cap": "small"},
    {"symbol": "IRFC", "name": "Indian Railway Finance Corp", "exchange": "NSE", "aliases": ["IRFC"], "sector": "Finance", "market_cap": "mid"},
    {"symbol": "NHPC", "name": "NHPC Ltd", "exchange": "NSE", "aliases": ["NHPC"], "sector": "Power", "market_cap": "mid"},
    {"symbol": "HAL", "name": "Hindustan Aeronautics", "exchange": "NSE", "aliases": ["HAL", "Hindustan Aeronautics"], "sector": "Defence", "market_cap": "large"},
    {"symbol": "BEL", "name": "Bharat Electronics Ltd", "exchange": "NSE", "aliases": ["BEL", "Bharat Electronics"], "sector": "Defence", "market_cap": "mid"},
    # Index references
    {"symbol": "NIFTY", "name": "Nifty 50 Index", "exchange": "NSE", "aliases": ["Nifty", "Nifty50", "Nifty 50", "NIFTY50"], "sector": "Index", "market_cap": "large"},
    {"symbol": "SENSEX", "name": "BSE Sensex Index", "exchange": "BSE", "aliases": ["Sensex", "BSE Sensex", "BSE30"], "sector": "Index", "market_cap": "large"},
    {"symbol": "BANKNIFTY", "name": "Bank Nifty Index", "exchange": "NSE", "aliases": ["Bank Nifty", "BankNifty"], "sector": "Index", "market_cap": "large"},
]


# ──────────────────────────────────────────────────────────────────────
# STOCK IDENTIFICATION ENGINE
# ──────────────────────────────────────────────────────────────────────

# Regex patterns for extracting trading signals
TARGET_PATTERN = re.compile(
    r'(?:target|tgt|tp)\s*[:=\-]?\s*(?:Rs\.?\s*)?(\d{1,6}(?:\.\d{1,2})?)',
    re.IGNORECASE
)
STOPLOSS_PATTERN = re.compile(
    r'(?:stop\s*loss|sl|stoploss)\s*[:=\-]?\s*(?:Rs\.?\s*)?(\d{1,6}(?:\.\d{1,2})?)',
    re.IGNORECASE
)
ACTION_PATTERN = re.compile(
    r'\b(buy|sell|long|short|accumulate|avoid|book\s*profit)\b',
    re.IGNORECASE
)
TIMEFRAME_PATTERN = re.compile(
    r'\b(intraday|swing|positional|short\s*term|medium\s*term|long\s*term|weekly|daily|monthly)\b',
    re.IGNORECASE
)

# Patterns for analysis type detection
TECHNICAL_KEYWORDS = [
    'support', 'resistance', 'breakout', 'breakdown', 'moving average', 'ma',
    'rsi', 'macd', 'bollinger', 'fibonacci', 'trend', 'chart', 'pattern',
    'head and shoulders', 'double top', 'double bottom', 'triangle',
    'pennant', 'flag', 'wedge', 'channel', 'trendline', 'ema', 'sma',
    'volume', 'candlestick', 'doji', 'hammer', 'engulfing', 'crossover',
    'divergence', 'overbought', 'oversold', 'consolidation', 'reversal',
    'continuation', 'cup and handle', 'gap up', 'gap down', 'pivot'
]

FUNDAMENTAL_KEYWORDS = [
    'pe ratio', 'p/e', 'eps', 'revenue', 'profit', 'margin', 'growth',
    'dividend', 'book value', 'balance sheet', 'cash flow', 'debt',
    'market cap', 'roe', 'roce', 'promoter', 'holding', 'quarterly',
    'annual', 'results', 'guidance', 'outlook', 'order book', 'capex',
    'ebitda', 'earnings', 'topline', 'bottomline', 'net profit',
    'operating profit', 'sales', 'turnover', 'asset', 'liability',
    'valuation', 'intrinsic value', 'undervalued', 'overvalued', 'fair value'
]


class StockIdentifier:
    """
    Identifies stock mentions in text and maps them to the Stock table.
    This is the bridge between Level 1 (raw) and Level 2 (stock-mapped) DB.
    """

    def __init__(self, db: Database):
        self.db = db
        self._stock_lookup: Dict[str, int] = {}   # symbol -> stock_id
        self._alias_lookup: Dict[str, int] = {}   # alias -> stock_id
        self._name_lookup: Dict[str, int] = {}    # lowercase name -> stock_id
        self._initialized = False

    def initialize(self, seed_stocks: bool = True):
        """Load or seed the stocks table and build lookup indices."""
        if seed_stocks:
            self._seed_stock_master()
        self._build_lookup()
        self._initialized = True

    def _seed_stock_master(self):
        """Insert STOCK_MASTER data into DB (idempotent)."""
        for s in STOCK_MASTER:
            self.db.upsert_stock(
                symbol=s['symbol'],
                name=s['name'],
                exchange=s['exchange'],
                aliases=s.get('aliases', []),
                sector=s.get('sector'),
                market_cap=s.get('market_cap'),
            )

    def _build_lookup(self):
        """Build in-memory lookup tables for fast matching."""
        self._stock_lookup.clear()
        self._alias_lookup.clear()
        self._name_lookup.clear()

        stocks = self.db.get_all_stocks()
        for stock in stocks:
            self._stock_lookup[stock.symbol.upper()] = stock.id
            self._name_lookup[stock.name.lower()] = stock.id
            if stock.nse_symbol:
                self._stock_lookup[stock.nse_symbol.upper()] = stock.id
            if stock.aliases:
                for alias in stock.aliases:
                    self._alias_lookup[alias.upper()] = stock.id

    def identify_stocks(self, text: str) -> List[Dict]:
        """
        Identify all stock mentions in a piece of text.
        Returns list of {stock_id, matched_text, match_method, confidence}.
        """
        if not self._initialized:
            self.initialize()

        if not text:
            return []

        matches = []
        seen_stock_ids = set()
        text_upper = text.upper()

        # 1. Exact symbol match (highest confidence)
        for symbol, stock_id in self._stock_lookup.items():
            # Word boundary match to avoid false positives
            pattern = r'\b' + re.escape(symbol) + r'\b'
            if re.search(pattern, text_upper):
                if stock_id not in seen_stock_ids:
                    matches.append({
                        'stock_id': stock_id,
                        'matched_text': symbol,
                        'match_method': 'symbol',
                        'confidence': 0.95
                    })
                    seen_stock_ids.add(stock_id)

        # 2. Alias match (high confidence)
        for alias, stock_id in self._alias_lookup.items():
            if stock_id in seen_stock_ids:
                continue
            # Only match aliases with 3+ chars to avoid false positives
            if len(alias) < 3:
                continue
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, text_upper):
                matches.append({
                    'stock_id': stock_id,
                    'matched_text': alias,
                    'match_method': 'alias',
                    'confidence': 0.85
                })
                seen_stock_ids.add(stock_id)

        # 3. Company name match (medium confidence)
        text_lower = text.lower()
        for name, stock_id in self._name_lookup.items():
            if stock_id in seen_stock_ids:
                continue
            if name in text_lower:
                matches.append({
                    'stock_id': stock_id,
                    'matched_text': name,
                    'match_method': 'name',
                    'confidence': 0.75
                })
                seen_stock_ids.add(stock_id)

        return matches

    def extract_trading_details(self, text: str) -> Dict:
        """Extract target price, stop loss, action, timeframe from text."""
        details = {}

        # Target price
        target_match = TARGET_PATTERN.search(text)
        if target_match:
            details['target_price'] = float(target_match.group(1))

        # Stop loss
        sl_match = STOPLOSS_PATTERN.search(text)
        if sl_match:
            details['stop_loss'] = float(sl_match.group(1))

        # Action
        action_match = ACTION_PATTERN.search(text)
        if action_match:
            action = action_match.group(1).lower().replace(' ', '_')
            details['action_suggested'] = action

        # Timeframe
        tf_match = TIMEFRAME_PATTERN.search(text)
        if tf_match:
            details['time_horizon'] = tf_match.group(1).lower().replace(' ', '_')

        # Analysis type
        details['analysis_type'] = self._detect_analysis_type(text)

        return details

    def _detect_analysis_type(self, text: str) -> Optional[AnalysisType]:
        """Detect whether the post is technical, fundamental, or general sentiment."""
        text_lower = text.lower()

        tech_score = sum(1 for kw in TECHNICAL_KEYWORDS if kw in text_lower)
        fund_score = sum(1 for kw in FUNDAMENTAL_KEYWORDS if kw in text_lower)

        if tech_score > fund_score and tech_score >= 2:
            return AnalysisType.TECHNICAL
        elif fund_score > tech_score and fund_score >= 2:
            return AnalysisType.FUNDAMENTAL
        elif tech_score >= 1 or fund_score >= 1:
            return AnalysisType.SENTIMENT
        return AnalysisType.SENTIMENT

    def process_unprocessed_posts(self, batch_size: int = 100) -> dict:
        """
        Process unprocessed raw posts: identify stocks + create mentions.
        This is the main pipeline step that moves data from Level 1 → Level 2.
        """
        if not self._initialized:
            self.initialize()

        posts = self.db.get_unprocessed_posts(limit=batch_size)
        stats = {"processed": 0, "stock_relevant": 0, "mentions_created": 0}

        for post in posts:
            text = post.text or post.text_clean or ""
            stock_matches = self.identify_stocks(text)

            is_relevant = len(stock_matches) > 0

            if is_relevant:
                details = self.extract_trading_details(text)
                for match in stock_matches:
                    self.db.insert_stock_mention(
                        raw_post_id=post.id,
                        stock_id=match['stock_id'],
                        matched_text=match['matched_text'],
                        match_method=match['match_method'],
                        confidence=match['confidence'],
                        analysis_type=details.get('analysis_type'),
                        target_price=details.get('target_price'),
                        stop_loss=details.get('stop_loss'),
                        time_horizon=details.get('time_horizon'),
                        action_suggested=details.get('action_suggested'),
                    )
                    stats["mentions_created"] += 1
                stats["stock_relevant"] += 1

            self.db.mark_post_processed(post.id, is_relevant)
            stats["processed"] += 1

        return stats


def load_stock_master_from_nse_csv(db: Database, csv_path: str):
    """
    Load full NSE/BSE stock list from a CSV file.
    Expected columns: SYMBOL, NAME OF COMPANY, ISIN NUMBER, SERIES
    You can download this from: https://www.nseindia.com/market-data/securities-available-for-trading
    """
    df = pd.read_csv(csv_path)
    count = 0
    for _, row in df.iterrows():
        symbol = str(row.get('SYMBOL', row.get('symbol', ''))).strip()
        name = str(row.get('NAME OF COMPANY', row.get('name', row.get('Company Name', '')))).strip()
        isin = str(row.get('ISIN NUMBER', row.get('isin', row.get('ISIN', '')))).strip()

        if symbol and name:
            db.upsert_stock(
                symbol=symbol,
                name=name,
                exchange="NSE",
                isin=isin if isin != 'nan' else None,
            )
            count += 1
    return count
