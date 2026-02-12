"""
StockRAG - Main Orchestrator
==============================

Ties together all components:
  - Data ingestion (from Apify scrapers)
  - Stock identification (Level 1 → Level 2)
  - Sentiment analysis
  - Vector store sync
  - RAG prediction

Usage:
  python -m stock_rag                    # Run full pipeline
  python -m stock_rag ingest             # Only ingest existing files
  python -m stock_rag process            # Only process (identify stocks + sentiment)
  python -m stock_rag predict RELIANCE   # Predict for a stock
  python -m stock_rag query "What is market sentiment on banking stocks?"
  python -m stock_rag stats              # Show database stats
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


def get_db(db_path: str = None):
    from .database import Database
    path = db_path or os.getenv("STOCKRAG_DB_PATH", "stock_rag.db")
    return Database(path)


def get_vector_store(persist_dir: str = None):
    from .vector_store import VectorStore
    path = persist_dir or os.getenv("STOCKRAG_VECTOR_DIR", "./chroma_db")
    return VectorStore(path)


def get_llm(provider: str = None):
    provider = provider or os.getenv("STOCKRAG_LLM_PROVIDER", "gemini")
    
    if provider == "gemini":
        from .rag_pipeline import GeminiProvider
        return GeminiProvider()
    elif provider == "openai":
        from .rag_pipeline import OpenAIProvider
        return OpenAIProvider()
    elif provider == "ollama":
        from .rag_pipeline import OllamaProvider
        model = os.getenv("OLLAMA_MODEL", "llama3.1")
        return OllamaProvider(model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def cmd_ingest(args):
    """Ingest data from existing files."""
    from .database import Database
    from .ingestion import DataIngestionPipeline

    db = get_db(args.db)
    pipeline = DataIngestionPipeline(db)

    print("=" * 60)
    print("StockRAG - Data Ingestion")
    print("=" * 60)

    base_dir = args.dir or "."
    print(f"\nScanning {base_dir} for data files...\n")
    result = pipeline.ingest_existing_files(base_dir)

    print(f"\n{'─' * 40}")
    print(f"Files processed: {result['files_processed']}")
    print(f"Posts inserted:  {result['total_inserted']}")
    print(f"Duplicates:      {result['total_skipped']}")
    print(f"{'─' * 40}")

    stats = db.get_stats()
    print(f"\nDatabase totals: {stats['raw_posts']} posts from {stats['sources']} sources")


def cmd_process(args):
    """Process raw posts: identify stocks + run sentiment analysis."""
    from .stock_identifier import StockIdentifier
    from .sentiment import SignalAggregator

    db = get_db(args.db)

    print("=" * 60)
    print("StockRAG - Processing Pipeline")
    print("=" * 60)

    # Step 1: Identify stocks
    print("\n[1/3] Identifying stocks in posts...")
    identifier = StockIdentifier(db)
    identifier.initialize(seed_stocks=True)
    id_stats = identifier.process_unprocessed_posts(batch_size=args.batch)
    print(f"  Processed: {id_stats['processed']}")
    print(f"  Stock relevant: {id_stats['stock_relevant']}")
    print(f"  Mentions created: {id_stats['mentions_created']}")

    # Step 2: Sentiment analysis
    print("\n[2/3] Running sentiment analysis...")
    aggregator = SignalAggregator(db)
    sent_count = aggregator.analyze_mentions(batch_size=args.batch)
    print(f"  Mentions analyzed: {sent_count}")

    # Step 3: Generate signals
    print("\n[3/3] Generating aggregated signals...")
    signals = aggregator.generate_signals(window_hours=args.window)
    print(f"  Signals generated: {len(signals)}")
    for sig in signals:
        print(f"    {sig}")

    # Step 4: Sync to vector store (if chromadb available)
    try:
        print("\n[bonus] Syncing to vector store...")
        vs = get_vector_store()
        synced = vs.sync_from_db(db, batch_size=args.batch)
        print(f"  Posts synced to ChromaDB: {synced}")
    except ImportError:
        print("  Skipped (chromadb not installed)")

    stats = db.get_stats()
    print(f"\n{'─' * 40}")
    print(f"DB Stats: {json.dumps(stats, indent=2)}")


def cmd_predict(args):
    """Generate prediction for a stock."""
    from .rag_pipeline import RAGPipeline

    db = get_db(args.db)
    vs = get_vector_store()
    llm = get_llm(args.llm)
    pipeline = RAGPipeline(db, vs, llm)

    print("=" * 60)
    print(f"StockRAG - Prediction for {args.symbol.upper()}")
    print("=" * 60)

    result = pipeline.predict(
        stock_symbol=args.symbol.upper(),
        lookback_hours=args.lookback,
        max_posts=args.max_posts,
    )

    print(json.dumps(result, indent=2, default=str))


def cmd_query(args):
    """Ask a general question using RAG."""
    from .rag_pipeline import RAGPipeline

    db = get_db(args.db)
    vs = get_vector_store()
    llm = get_llm(args.llm)
    pipeline = RAGPipeline(db, vs, llm)

    print("=" * 60)
    print("StockRAG - RAG Query")
    print("=" * 60)
    print(f"Q: {args.question}\n")

    answer = pipeline.query(args.question, n_results=args.max_posts)
    print(f"A: {answer}")


def cmd_stats(args):
    """Show database statistics."""
    db = get_db(args.db)
    stats = db.get_stats()
    
    print("=" * 60)
    print("StockRAG - Database Statistics")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:>25}: {v}")

    try:
        vs = get_vector_store()
        vs_stats = vs.get_stats()
        print(f"\n  Vector Store:")
        for k, v in vs_stats.items():
            print(f"  {k:>25}: {v}")
    except Exception:
        print(f"\n  Vector Store: not available")


def cmd_scrape_live(args):
    """Run a live scrape using Apify and ingest results."""
    from .database import Platform
    from .ingestion import DataIngestionPipeline

    db = get_db(args.db)
    pipeline = DataIngestionPipeline(db)

    platform_map = {
        'telegram': Platform.TELEGRAM,
        'x': Platform.X, 'twitter': Platform.X,
        'linkedin': Platform.LINKEDIN,
    }
    platform = platform_map.get(args.platform.lower())
    if not platform:
        print(f"Unknown platform: {args.platform}")
        return

    print(f"Starting live scrape: {args.platform} / {args.handle}")
    
    # Actor IDs from your existing scrapers
    actor_ids = {
        'telegram': 'f9ah2tzQwzhF8OyfK',
        'x': 'heLL6fUofdPgRXqzn',
        'linkedin': 'kOyFSbazDuKXqGxfg',
    }

    actor_input = {"handle": args.handle, "maxPosts": args.max_posts}
    
    try:
        result = pipeline.ingest_from_apify_live(
            platform=platform,
            handle=args.handle,
            actor_id=actor_ids.get(args.platform.lower(), ''),
            actor_input=actor_input,
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="StockRAG - RAG-based Stock Market Prediction System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--db', default=None, help='Database file path')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # ingest
    p_ingest = subparsers.add_parser('ingest', help='Ingest data from files')
    p_ingest.add_argument('--dir', default='.', help='Directory to scan')
    p_ingest.set_defaults(func=cmd_ingest)

    # process
    p_process = subparsers.add_parser('process', help='Process posts (stock ID + sentiment)')
    p_process.add_argument('--batch', type=int, default=500, help='Batch size')
    p_process.add_argument('--window', type=int, default=72, help='Signal window (hours)')
    p_process.set_defaults(func=cmd_process)

    # predict
    p_predict = subparsers.add_parser('predict', help='Predict stock movement')
    p_predict.add_argument('symbol', help='Stock symbol (e.g. RELIANCE)')
    p_predict.add_argument('--lookback', type=int, default=72, help='Lookback hours')
    p_predict.add_argument('--max-posts', type=int, default=20, help='Max RAG posts')
    p_predict.add_argument('--llm', default=None, help='LLM provider (gemini/openai/ollama)')
    p_predict.set_defaults(func=cmd_predict)

    # query
    p_query = subparsers.add_parser('query', help='Ask a question via RAG')
    p_query.add_argument('question', help='Your question')
    p_query.add_argument('--max-posts', type=int, default=10, help='Max context posts')
    p_query.add_argument('--llm', default=None, help='LLM provider')
    p_query.set_defaults(func=cmd_query)

    # stats
    p_stats = subparsers.add_parser('stats', help='Show database stats')
    p_stats.set_defaults(func=cmd_stats)

    # scrape
    p_scrape = subparsers.add_parser('scrape', help='Live scrape via Apify')
    p_scrape.add_argument('platform', help='Platform (telegram/x/linkedin)')
    p_scrape.add_argument('handle', help='Channel/handle to scrape')
    p_scrape.add_argument('--max-posts', type=int, default=50, help='Max posts')
    p_scrape.set_defaults(func=cmd_scrape_live)

    args = parser.parse_args()
    
    if not args.command:
        # Default: run full pipeline (ingest + process)
        print("Running full pipeline (ingest + process)...")
        args.dir = '.'
        args.db = args.db
        args.batch = 500
        args.window = 72
        cmd_ingest(args)
        print()
        cmd_process(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
