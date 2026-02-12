"""
StockRAG - RAG-based Stock Market Prediction System
====================================================

A multi-stage pipeline that:
1. Scrapes social media (Telegram, X.com, LinkedIn) via Apify
2. Stores raw data in SQLite (Level 1 - Raw Posts DB)
3. Identifies stock mentions and maps to NSE/BSE scripts (Level 2 - Stock DB)
4. Stores embeddings in ChromaDB for semantic search (Vector DB)
5. Performs sentiment + technical/fundamental analysis
6. Uses RAG pipeline with LLM for stock prediction
"""

__version__ = "0.1.0"
