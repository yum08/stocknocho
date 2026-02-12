# StockRAG - RAG-based Stock Market Prediction System

## Architecture Overview

A multi-stage pipeline that scrapes social media, identifies stock mentions, analyzes sentiment, and generates predictions using RAG (Retrieval Augmented Generation).

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                 │
│   Telegram Channels  │  X.com Handles  │  LinkedIn  │  Others      │
│   (via Apify API)    │  (via Apify)    │  (via Apify)│             │
└───────────┬──────────┴────────┬────────┴──────┬─────┴─────────────┘
            │                   │               │
            ▼                   ▼               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   DATA INGESTION PIPELINE                           │
│   ingestion.py - Normalizes all platform data to unified schema     │
│   • Platform-specific normalizers (Telegram, X, LinkedIn)           │
│   • Deduplication via platform + external_id                        │
│   • Supports: JSON files, CSV files, Live Apify API calls           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              LEVEL 1 DATABASE (SQLite)                               │
│   database.py - "Raw Posts DB"                                       │
│   ┌──────────┐  ┌───────────┐  ┌────────────┐                      │
│   │ sources  │  │ raw_posts │  │ scrape_jobs│                      │
│   │──────────│  │───────────│  │────────────│                      │
│   │ platform │  │ text      │  │ source_id  │                      │
│   │ handle   │  │ author    │  │ status     │                      │
│   │ category │  │ posted_at │  │ posts_new  │                      │
│   │ score    │  │ views     │  │ error      │                      │
│   └──────────┘  │ likes     │  └────────────┘                      │
│                 │ platform  │                                       │
│                 └─────┬─────┘                                       │
│                       │                                             │
└───────────────────────┼─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 STOCK IDENTIFIER                                     │
│   stock_identifier.py                                                │
│   • Symbol matching (RELIANCE, TCS, INFY...)                        │
│   • Alias matching  (RIL → Reliance, SBI → State Bank)             │
│   • Company name matching                                           │
│   • Trading detail extraction (target, SL, action)                  │
│   • Analysis type detection (technical vs fundamental)              │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│              LEVEL 2 DATABASE (SQLite)                               │
│   database.py - "Stock-Mapped DB"                                    │
│   ┌──────────┐  ┌────────────────┐  ┌──────────────┐               │
│   │ stocks   │  │ stock_mentions │  │ stock_signals│               │
│   │──────────│  │────────────────│  │──────────────│               │
│   │ symbol   │  │ raw_post_id    │  │ stock_id     │               │
│   │ name     │  │ stock_id       │  │ avg_sentiment│               │
│   │ exchange │  │ sentiment      │  │ signal_type  │               │
│   │ sector   │  │ target_price   │  │ confidence   │               │
│   │ aliases  │  │ action         │  │ direction    │               │
│   └──────────┘  └────────────────┘  └──────────────┘               │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
┌────────────────────┐  ┌─────────────────────────────────────────────┐
│  SENTIMENT ENGINE  │  │          VECTOR STORE (ChromaDB)             │
│  sentiment.py      │  │  vector_store.py                             │
│  • Rule-based      │  │  • Semantic embeddings of posts              │
│  • Bullish/Bearish │  │  • Similarity search for RAG retrieval       │
│  • Indian market   │  │  • Filtered by platform/stock                │
│    slang support   │  │  • Auto-syncs from SQLite                    │
│  • Signal          │  │                                              │
│    aggregation     │  │                                              │
└────────┬───────────┘  └──────────────────┬──────────────────────────┘
         │                                  │
         └──────────┬───────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    RAG PIPELINE                                      │
│   rag_pipeline.py                                                    │
│   1. Query ChromaDB for relevant posts (semantic search)             │
│   2. Enrich with structured signals from SQLite                      │
│   3. Build context prompt with all evidence                          │
│   4. Send to LLM (Gemini / OpenAI / Ollama)                        │
│   5. Return structured prediction with reasoning                     │
│                                                                      │
│   Supports: Google Gemini, OpenAI GPT-4, Local Ollama               │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │    PREDICTION     │
                        │  • Direction      │
                        │  • Confidence     │
                        │  • Key factors    │
                        │  • Risk factors   │
                        │  • Target price   │
                        │  • Reasoning      │
                        └──────────────────┘
```

## Design Decisions

### Why SQLite + ChromaDB (Hybrid) instead of just one?

| Need | SQLite | ChromaDB |
|------|--------|----------|
| "Show all RELIANCE mentions from last 7 days" | ✅ Fast indexed query | ❌ Not designed for this |
| "What are people saying about banking sector?" | ❌ No semantic search | ✅ Embedding similarity |
| Deduplication by post ID | ✅ Unique constraints | ❌ Manual |
| Aggregated signals per stock | ✅ SQL GROUP BY | ❌ Not suitable |
| Finding similar posts to a query | ❌ Only exact match | ✅ Semantic match |
| Structured filters (date, platform, stock) | ✅ Indexed columns | ⚠️ Limited metadata filters |

**Verdict**: Use both. SQLite for structured data + ChromaDB for semantic RAG retrieval.

### Why this design over the ProBoards pattern?

The [ProBoards scraper design](https://nrsyed.com/2021/11/26/asynchronously-web-scraping-a-proboards-forum-with-python-part-1/) inspired several aspects:

1. **Database class pattern** → Our `Database` class wraps all SQLAlchemy operations
2. **SQLite + SQLAlchemy ORM** → Same approach, no raw SQL
3. **Queue-based ingestion** → Our `DataIngestionPipeline` normalizes and deduplicates
4. **Entity-per-table** → Sources, Posts, Stocks, Mentions, Signals as separate tables

**Additions** beyond ProBoards:
- Two-level DB (raw → stock-mapped) for filtering
- Vector store for semantic search
- LLM-powered RAG prediction
- Multi-platform normalizers

## Quick Start

### 1. Install dependencies
```bash
cd stock_rag
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Ingest existing data
```bash
# Auto-discovers and ingests all CSV/JSON files in workspace
python -m stock_rag ingest --dir ..
```

### 4. Process (identify stocks + sentiment)
```bash
python -m stock_rag process
```

### 5. Get prediction
```bash
python -m stock_rag predict RELIANCE
python -m stock_rag predict TCS --lookback 48
```

### 6. Ask questions (RAG)
```bash
python -m stock_rag query "What is the sentiment on IT stocks?"
```

### 7. View stats
```bash
python -m stock_rag stats
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m stock_rag` | Run full pipeline (ingest + process) |
| `python -m stock_rag ingest` | Ingest data from CSV/JSON files |
| `python -m stock_rag process` | Identify stocks + sentiment analysis |
| `python -m stock_rag predict SYMBOL` | Generate prediction for a stock |
| `python -m stock_rag query "question"` | Ask any question via RAG |
| `python -m stock_rag stats` | Show database statistics |
| `python -m stock_rag scrape telegram handle` | Live scrape via Apify |

## File Structure

```
stock_rag/
├── __init__.py              # Package init
├── __main__.py              # CLI entrypoint & orchestrator
├── database.py              # SQLAlchemy models + Database class
├── ingestion.py             # Data ingestion pipeline (CSV/JSON/Apify)
├── stock_identifier.py      # Stock mention detection + NSE/BSE mapping
├── sentiment.py             # Sentiment analysis + signal aggregation
├── vector_store.py          # ChromaDB vector store for RAG
├── rag_pipeline.py          # RAG pipeline + LLM providers
├── requirements.txt         # Python dependencies
├── .env.example             # Environment config template
└── README.md                # This file
```

## Database Schema

### Level 1: Raw Data
- **sources** — Channels/handles we scrape from (platform, handle, reliability)
- **raw_posts** — All scraped posts, unified schema (text, author, views, likes)
- **scrape_jobs** — Tracks each scrape run (status, counts, errors)

### Level 2: Stock-Mapped
- **stocks** — NSE/BSE stock master list (symbol, name, aliases, sector)
- **stock_mentions** — Post ↔ Stock mapping (sentiment, target price, action)
- **stock_signals** — Aggregated signals per stock per time window

## Extending

### Add a new platform scraper
1. Add normalizer function in `ingestion.py` (like `normalize_reddit_post`)
2. Add `Platform.REDDIT` to the enum in `database.py`
3. Register in `NORMALIZERS` dict
4. Add file detection pattern in `ingest_existing_files()`

### Add more stocks
- Edit `STOCK_MASTER` in `stock_identifier.py`
- Or load from NSE CSV: `load_stock_master_from_nse_csv(db, "nse_list.csv")`

### Use a different LLM
Set `STOCKRAG_LLM_PROVIDER` in `.env` to `gemini`, `openai`, or `ollama`.
