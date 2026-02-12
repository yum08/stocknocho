"""
StockRAG Web Application
=========================
Local web dashboard for the full StockRAG pipeline.
Run:  python -m stock_rag.webapp
Then visit http://localhost:5000
"""

import os
import sys
import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Load .env before anything reads env vars
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell env

import requests as http_requests
from flask import Flask, request, jsonify, render_template, send_from_directory

# Suppress SSL warnings for corporate proxy environments
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add parent dir so stock_rag imports work when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import extract, func, distinct
from stock_rag.database import Database, Platform, RawPost, Stock
from stock_rag.ingestion import DataIngestionPipeline
from stock_rag.stock_identifier import StockIdentifier
from stock_rag.sentiment import SentimentAnalyzer, SignalAggregator
from stock_rag.vector_store import VectorStore

# --------------- lazy RAG (requires API keys) -----------------
_rag_pipeline = None


def _get_rag():
    """Lazily initialise the RAG pipeline only when actually called."""
    global _rag_pipeline
    if _rag_pipeline is not None:
        return _rag_pipeline

    from stock_rag.rag_pipeline import (
        RAGPipeline, GeminiProvider, OpenAIProvider, OllamaProvider
    )

    provider_name = os.getenv("STOCKRAG_LLM_PROVIDER", "gemini").lower()
    try:
        if provider_name == "openai":
            llm = OpenAIProvider()
        elif provider_name == "ollama":
            llm = OllamaProvider()
        else:
            llm = GeminiProvider()
    except ValueError:
        return None  # key not set

    _rag_pipeline = RAGPipeline(db=db, vector_store=vs, llm_provider=llm)
    return _rag_pipeline


# --------------- globals initialised at startup ----------------
DB_PATH = os.getenv("STOCKRAG_DB", "stock_rag.db")
CHROMA_DIR = os.getenv("STOCKRAG_CHROMA", "./chroma_db")

db = Database(DB_PATH)
vs = VectorStore(CHROMA_DIR)
ingestion = DataIngestionPipeline(db)
identifier = StockIdentifier(db)
sentiment = SentimentAnalyzer()
aggregator = SignalAggregator(db)

# Apify actor configs for live scraping
APIFY_TOKEN = os.getenv('APIFY_API_TOKEN')
APIFY_BASE_URL = 'https://api.apify.com/v2'
ACTOR_IDS = {
    'x':        'ghSpYIW3L1RvT57NT',   # danek/twitter-scraper-ppr
    'telegram':  'TpLqaxMYSJzwVnXoj',   # cheapget/telegram-channel-message
    'linkedin':  'LQQIXN9Othf8f7R5n',   # apimaestro/linkedin-profile-posts
}

# Seed stock master on first run (idempotent)
identifier.initialize(seed_stocks=True)

# --------------- Flask app ------------------------------------
app = Flask(
    __name__,
    static_folder=str(Path(__file__).resolve().parent / "webapp_static"),
    template_folder=str(Path(__file__).resolve().parent / "webapp_templates"),
)


# ══════════════════════════════════════════════════════════════
#  PAGES
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
#  API: DASHBOARD STATS
# ══════════════════════════════════════════════════════════════

@app.route("/api/stats")
def api_stats():
    """Return overall system statistics."""
    try:
        db_stats = db.get_stats()
        vs_stats = vs.get_stats()
        return jsonify({"ok": True, "db": db_stats, "vector": vs_stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/pipeline/status")
def api_pipeline_status():
    """Return pending / done counts for each pipeline stage.

    This gives the user a clear view of where data sits at each step.
    """
    try:
        session = db.get_session()
        from stock_rag.database import RawPost, StockMention, StockSignal, Source

        total_posts = session.query(RawPost).count()
        unprocessed   = session.query(RawPost).filter(RawPost.is_processed == False).count()
        processed     = session.query(RawPost).filter(RawPost.is_processed == True).count()
        stock_relevant = session.query(RawPost).filter(RawPost.is_stock_relevant == True).count()

        total_mentions = session.query(StockMention).count()
        unscored = session.query(StockMention).filter(StockMention.sentiment_score == None).count()
        scored   = total_mentions - unscored

        total_signals = session.query(StockSignal).count()
        vs_stats = vs.get_stats()
        total_vectors = vs_stats.get("total_documents", 0)

        # Recent activity: last 5 posts
        recent_posts = session.query(RawPost).order_by(RawPost.scraped_at.desc()).limit(5).all()
        recent = []
        for p in recent_posts:
            recent.append({
                "id": p.id,
                "platform": p.platform.value if p.platform else None,
                "author": p.author,
                "text": (p.text or "")[:120],
                "posted_at": str(p.posted_at) if p.posted_at else None,
                "is_processed": p.is_processed,
                "is_stock_relevant": p.is_stock_relevant,
            })

        session.close()

        return jsonify({
            "ok": True,
            "stages": {
                "ingest":    {"label": "Ingested Posts",     "total": total_posts,   "done": total_posts,   "pending": 0},
                "identify":  {"label": "Stock Identification","total": total_posts,   "done": processed,     "pending": unprocessed},
                "sentiment": {"label": "Sentiment Analysis", "total": total_mentions, "done": scored,        "pending": unscored},
                "signals":   {"label": "Signal Generation",  "total": total_signals,  "done": total_signals, "pending": 0},
                "vectors":   {"label": "Vector Sync",        "total": total_vectors,  "done": total_vectors, "pending": stock_relevant - total_vectors if stock_relevant > total_vectors else 0},
            },
            "summary": {
                "total_posts": total_posts,
                "stock_relevant": stock_relevant,
                "mentions": total_mentions,
                "signals": total_signals,
                "vectors": total_vectors,
            },
            "recent_posts": recent,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: DATA INGESTION
# ══════════════════════════════════════════════════════════════

@app.route("/api/ingest/auto", methods=["POST"])
def api_ingest_auto():
    """Auto-discover and ingest CSV/JSON files from workspace."""
    try:
        base_dir = request.json.get("base_dir", ".") if request.json else "."
        result = ingestion.ingest_existing_files(base_dir)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ingest/file", methods=["POST"])
def api_ingest_file():
    """Ingest a specific CSV or JSON file."""
    try:
        data = request.json
        file_path = data["file_path"]
        platform = Platform[data["platform"].upper()]
        handle = data.get("handle", Path(file_path).stem)

        if file_path.lower().endswith(".json"):
            result = ingestion.ingest_from_json(file_path, platform, handle)
        elif file_path.lower().endswith(".csv"):
            result = ingestion.ingest_from_csv(file_path, platform, handle)
        else:
            return jsonify({"ok": False, "error": "Unsupported file type. Use .csv or .json"}), 400

        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ingest/live", methods=["POST"])
def api_ingest_live():
    """Live scrape from a social media handle using Apify."""
    import time as _time
    try:
        data = request.json
        platform_str = data.get("platform", "x").lower()
        handle = data.get("handle", "").strip().lstrip("@")
        max_posts = int(data.get("max_posts", 200))
        date_range = data.get("date_range", "")  # e.g. "30 days", "365 days", or ""
        # Budget in USD for pay-per-event actors (Telegram). Minimum $1.
        budget_usd = float(data.get("budget_usd", 1.0))
        budget_usd = max(1.0, min(budget_usd, 50.0))  # clamp $1-$50

        if not handle:
            return jsonify({"ok": False, "error": "Handle is required"}), 400
        if not APIFY_TOKEN:
            return jsonify({"ok": False,
                            "error": "APIFY_API_TOKEN not set. "
                                     "Add it to your .env file. "
                                     "Get a token at https://console.apify.com/account/integrations"}), 400

        actor_id = ACTOR_IDS.get(platform_str)
        if not actor_id:
            return jsonify({"ok": False, "error": f"No actor for platform '{platform_str}'"}), 400

        # Build actor input per platform
        if platform_str == "x":
            actor_input = {"username": handle, "max_posts": max_posts}
        elif platform_str == "telegram":
            tg_url = handle if handle.startswith("http") else f"https://t.me/{handle}"
            actor_input = {"telegram_url": tg_url, "max_results": max_posts,
                           "download_medias": "text"}
            # Apply date filter only if user specified one, or for small scrapes
            if date_range:
                actor_input["start_date"] = date_range
            elif max_posts <= 200:
                actor_input["start_date"] = "90 days"
        elif platform_str == "linkedin":
            actor_input = {"username": handle, "limit": min(max_posts, 100),
                           "total_posts": max_posts}
        else:
            return jsonify({"ok": False, "error": "Unsupported platform"}), 400

        headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

        # Start the actor run  (verify=False for corporate proxy / self-signed certs)
        # maxTotalChargeUsd unlocks pay-per-event actors beyond free-tier cap (10 items)
        run_url = f"{APIFY_BASE_URL}/acts/{actor_id}/runs"
        run_params = {}
        if platform_str == "telegram":
            run_params["maxTotalChargeUsd"] = budget_usd
        run_resp = http_requests.post(
            run_url, json=actor_input, headers=headers,
            params=run_params, timeout=30, verify=False
        )
        run_resp.raise_for_status()
        run_data = run_resp.json()["data"]
        run_id = run_data["id"]

        # Poll until done — scale timeout with request size
        # Small scrapes: 3 min, large scrapes: up to 15 min
        poll_seconds = max(180, min(900, max_posts // 10))
        poll_iterations = poll_seconds // 5
        for _ in range(poll_iterations):
            _time.sleep(5)
            status_resp = http_requests.get(
                f"{APIFY_BASE_URL}/actor-runs/{run_id}",
                headers=headers, timeout=15, verify=False
            )
            status = status_resp.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            return jsonify({"ok": False, "error": f"Apify run ended: {status}"}), 500

        # Fetch results
        dataset_id = run_data.get("defaultDatasetId")
        items_resp = http_requests.get(
            f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
            headers=headers, timeout=120, verify=False
        )
        items = items_resp.json()

        # Ingest the items we fetched
        platform_enum = Platform[platform_str.upper()]
        from stock_rag.ingestion import NORMALIZERS
        source = db.upsert_source(platform_enum, handle,
                                  display_name=handle, category="live_scrape")
        normalizer = NORMALIZERS.get(platform_enum)
        if not normalizer:
            return jsonify({"ok": False, "error": "No normalizer for this platform"}), 400

        posts = [normalizer(raw, source.id) for raw in items]

        # For Telegram Apify scrapes, apply handle→display-name mapping
        # so author stays consistent with Telethon-sourced posts.
        if platform_str == 'telegram':
            from stock_rag.ingestion import resolve_telegram_author
            display_author = resolve_telegram_author(handle, fallback=handle)
            for p in posts:
                a = str(p.get('author', ''))
                if not a or a.replace(' ', '').isdigit() or a.startswith('@'):
                    p['author'] = display_author

        result = db.bulk_insert_raw_posts(posts)

        return jsonify({"ok": True, "handle": handle, "platform": platform_str,
                        "scraped_items": len(items), **result})
    except http_requests.exceptions.RequestException as e:
        return jsonify({"ok": False, "error": f"Apify API error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


# ══════════════════════════════════════════════════════════════
#  API: TELEGRAM HANDLE ↔ DISPLAY-NAME MAPPING
# ══════════════════════════════════════════════════════════════
@app.route("/api/telegram/handle-map", methods=["GET"])
def api_handle_map_get():
    """Return the current Telegram handle → display-name mapping."""
    from stock_rag.ingestion import TELEGRAM_HANDLE_MAP
    return jsonify({"ok": True, "mappings": dict(TELEGRAM_HANDLE_MAP)})


@app.route("/api/telegram/handle-map", methods=["POST"])
def api_handle_map_add():
    """Add or update a handle → display-name mapping (runtime + persisted to .env)."""
    from stock_rag.ingestion import TELEGRAM_HANDLE_MAP
    data = request.json or {}
    handle = data.get("handle", "").strip().lstrip("@").lower()
    display_name = data.get("display_name", "").strip()
    if not handle or not display_name:
        return jsonify({"ok": False, "error": "Both handle and display_name are required"}), 400
    TELEGRAM_HANDLE_MAP[handle] = display_name
    _persist_handle_map(TELEGRAM_HANDLE_MAP)
    return jsonify({"ok": True, "handle": handle, "display_name": display_name})


@app.route("/api/telegram/handle-map", methods=["DELETE"])
def api_handle_map_delete():
    """Remove a handle mapping."""
    from stock_rag.ingestion import TELEGRAM_HANDLE_MAP
    data = request.json or {}
    handle = data.get("handle", "").strip().lstrip("@").lower()
    if handle in TELEGRAM_HANDLE_MAP:
        del TELEGRAM_HANDLE_MAP[handle]
        _persist_handle_map(TELEGRAM_HANDLE_MAP)
    return jsonify({"ok": True})


def _persist_handle_map(mapping: dict):
    """Save the handle mapping to a JSON file so it survives restarts."""
    import json as _json
    map_path = os.path.join(os.path.dirname(__file__), 'telegram_handle_map.json')
    with open(map_path, 'w', encoding='utf-8') as f:
        _json.dump(mapping, f, indent=2, ensure_ascii=False)


def _load_persisted_handle_map():
    """Load persisted handle mapping from JSON file into TELEGRAM_HANDLE_MAP."""
    import json as _json
    map_path = os.path.join(os.path.dirname(__file__), 'telegram_handle_map.json')
    if os.path.exists(map_path):
        try:
            from stock_rag.ingestion import TELEGRAM_HANDLE_MAP
            with open(map_path, 'r', encoding='utf-8') as f:
                saved = _json.load(f)
            TELEGRAM_HANDLE_MAP.update(saved)
        except Exception:
            pass


# Load persisted mappings on startup
_load_persisted_handle_map()


@app.route("/api/telegram/status")
def api_telegram_status():
    """Check if Telethon (free Telegram scraping) is available."""
    try:
        from stock_rag.telethon_scraper import is_authenticated
        api_id = os.getenv('TELEGRAM_API_ID')
        api_hash = os.getenv('TELEGRAM_API_HASH')
        has_creds = bool(api_id and api_hash)
        authed = is_authenticated() if has_creds else False
        return jsonify({
            "ok": True,
            "has_credentials": has_creds,
            "is_authenticated": authed,
            "ready": has_creds and authed,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ingest/telegram-free", methods=["POST"])
def api_ingest_telegram_free():
    """Scrape Telegram channel for FREE using Telethon (Telegram API).

    Requires TELEGRAM_API_ID + TELEGRAM_API_HASH in .env and
    one-time auth via: python -m stock_rag.telegram_auth
    """
    try:
        from stock_rag.telethon_scraper import scrape_channel, is_authenticated
        from stock_rag.ingestion import NORMALIZERS

        data = request.json
        handle = data.get("handle", "").strip().lstrip("@")
        max_posts = int(data.get("max_posts", 1000))

        if not handle:
            return jsonify({"ok": False, "error": "Handle is required"}), 400

        api_id = os.getenv('TELEGRAM_API_ID')
        api_hash = os.getenv('TELEGRAM_API_HASH')

        if not api_id or not api_hash:
            return jsonify({"ok": False,
                            "error": "TELEGRAM_API_ID and TELEGRAM_API_HASH not set in .env. "
                                     "Get them free at https://my.telegram.org/auth"}), 400

        if not is_authenticated():
            return jsonify({"ok": False,
                            "error": "Telegram not authenticated. Run this in terminal first:\n"
                                     "python -m stock_rag.telegram_auth"}), 400

        # Parse optional date filter
        date_range = data.get("date_range", "")
        offset_date = None
        if date_range:
            import re as _re
            m = _re.match(r'(\d+)\s*days?', date_range)
            if m:
                offset_date = datetime.utcnow() - timedelta(days=int(m.group(1)))

        # OCR option: extract text from images (e.g. harmonic pattern charts)
        enable_ocr = bool(data.get("enable_ocr", False))

        # Scrape!
        items = scrape_channel(
            api_id=int(api_id),
            api_hash=api_hash,
            channel_username=handle,
            max_messages=max_posts,
            offset_date=offset_date,
            enable_ocr=enable_ocr,
        )

        if not items:
            return jsonify({"ok": True, "handle": handle, "scraped_items": 0,
                            "inserted": 0, "skipped": 0,
                            "message": "No messages found. Channel may be empty or private."})

        # Ingest using existing normalizer
        platform_enum = Platform.TELEGRAM
        normalizer = NORMALIZERS.get(platform_enum)
        source = db.upsert_source(platform_enum, handle,
                                  display_name=handle, category="telethon_free")
        posts = [normalizer(raw, source.id) for raw in items]

        # Guard: if normalizer produced a numeric-only author (raw channel ID),
        # override with the human-readable handle the user provided.
        display_author = handle.lstrip('@')
        for p in posts:
            a = str(p.get('author', ''))
            if not a or a.replace(' ', '').isdigit():
                p['author'] = display_author

        result = db.bulk_insert_raw_posts(posts)

        return jsonify({
            "ok": True, "handle": handle, "platform": "telegram",
            "method": "telethon_free",
            "scraped_items": len(items), **result
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


# ══════════════════════════════════════════════════════════════
#  API: STOCK PROCESSING PIPELINE
# ══════════════════════════════════════════════════════════════

@app.route("/api/purge/posts", methods=["POST"])
def api_purge_posts():
    """Purge ALL posts, mentions, signals, and sources from the database."""
    try:
        result = db.purge_all_posts()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/purge/source/<int:source_id>", methods=["POST"])
def api_purge_source(source_id):
    """Purge all posts for a specific source."""
    try:
        result = db.purge_posts_by_source(source_id)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/process/identify", methods=["POST"])
def api_process_identify():
    """Run stock identification on unprocessed posts."""
    try:
        batch = request.json.get("batch_size", 200) if request.json else 200
        stats = identifier.process_unprocessed_posts(batch_size=batch)
        return jsonify({"ok": True, **stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/process/sentiment", methods=["POST"])
def api_process_sentiment():
    """Run sentiment analysis on un-analyzed mentions."""
    try:
        batch = request.json.get("batch_size", 500) if request.json else 500
        count = aggregator.analyze_mentions(batch_size=batch)
        return jsonify({"ok": True, "analyzed": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/process/signals", methods=["POST"])
def api_process_signals():
    """Generate aggregated signals for all stocks."""
    try:
        hours = request.json.get("window_hours", 24) if request.json else 24
        signals = aggregator.generate_signals(window_hours=hours)
        result = []
        for s in signals:
            result.append({
                "stock_id": s.stock_id,
                "signal": s.signal_strength.value if s.signal_strength else None,
                "avg_sentiment": s.avg_sentiment,
                "total_mentions": s.total_mentions,
                "predicted_direction": s.predicted_direction,
                "confidence": s.confidence,
            })
        return jsonify({"ok": True, "signals": result, "count": len(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/process/vectorsync", methods=["POST"])
def api_process_vectorsync():
    """Sync processed posts into ChromaDB."""
    try:
        added = vs.sync_from_db(db)
        return jsonify({"ok": True, "vectors_added": added})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/process/full", methods=["POST"])
def api_process_full():
    """Run the full pipeline: ingest → identify → sentiment → signals → vector sync."""
    try:
        steps = {}

        # 1) Auto-ingest
        base_dir = request.json.get("base_dir", ".") if request.json else "."
        steps["ingest"] = ingestion.ingest_existing_files(base_dir)

        # 2) Identify stocks
        steps["identify"] = identifier.process_unprocessed_posts(batch_size=500)

        # 3) Sentiment
        steps["sentiment"] = {"analyzed": aggregator.analyze_mentions(batch_size=1000)}

        # 4) Signals
        signals = aggregator.generate_signals(window_hours=72)
        steps["signals"] = {"count": len(signals)}

        # 5) Vector sync
        added = vs.sync_from_db(db)
        steps["vector_sync"] = {"vectors_added": added}

        return jsonify({"ok": True, "steps": steps})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


# ══════════════════════════════════════════════════════════════
#  API: STOCKS  &  MENTIONS
# ══════════════════════════════════════════════════════════════

@app.route("/api/stocks")
def api_stocks():
    """List all stocks (with optional search and filters)."""
    try:
        q = request.args.get("q", "").strip()
        sector_filter = request.args.get("sector", "").strip()
        exchange_filter = request.args.get("exchange", "").strip()
        cap_filter = request.args.get("market_cap", "").strip()

        if q:
            stocks = db.search_stock(q)
        else:
            stocks = db.get_all_stocks()

        result = []
        for s in stocks:
            if sector_filter and (s.sector or '') != sector_filter:
                continue
            if exchange_filter and (s.exchange or '') != exchange_filter:
                continue
            if cap_filter and (s.market_cap or '') != cap_filter:
                continue
            result.append({
                "id": s.id, "symbol": s.symbol, "name": s.name,
                "exchange": s.exchange, "sector": s.sector,
                "market_cap": s.market_cap,
                "aliases": s.aliases or [],
            })
        return jsonify({"ok": True, "stocks": result, "count": len(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stocks/filters")
def api_stocks_filters():
    """Return distinct sectors, exchanges, market_caps for filter dropdowns."""
    try:
        all_stocks = db.get_all_stocks()
        sectors = sorted(set(s.sector for s in all_stocks if s.sector))
        exchanges = sorted(set(s.exchange for s in all_stocks if s.exchange))
        caps = []
        cap_order = {'large': 1, 'mid': 2, 'small': 3}
        raw_caps = set(s.market_cap for s in all_stocks if s.market_cap)
        caps = sorted(raw_caps, key=lambda c: cap_order.get(c.lower(), 99))
        symbols = sorted(set(s.symbol for s in all_stocks if s.symbol))
        return jsonify({"ok": True, "sectors": sectors, "exchanges": exchanges,
                        "market_caps": caps, "symbols": symbols})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stocks/<int:stock_id>/mentions")
def api_stock_mentions(stock_id):
    """Get recent mentions for a stock."""
    try:
        hours = int(request.args.get("hours", 168))
        limit = int(request.args.get("limit", 50))
        since = datetime.utcnow() - timedelta(hours=hours)
        mentions = db.get_mentions_for_stock(stock_id, since=since, limit=limit)

        result = []
        for m in mentions:
            result.append({
                "id": m.id,
                "raw_post_id": m.raw_post_id,
                "matched_text": m.matched_text,
                "match_method": m.match_method,
                "confidence": m.confidence,
                "sentiment_score": m.sentiment_score,
                "sentiment_label": m.sentiment_label.value if m.sentiment_label else None,
                "analysis_type": m.analysis_type.value if m.analysis_type else None,
                "target_price": m.target_price,
                "stop_loss": m.stop_loss,
                "time_horizon": m.time_horizon,
                "action_suggested": m.action_suggested,
                "created_at": str(m.created_at) if m.created_at else None,
            })
        return jsonify({"ok": True, "mentions": result, "count": len(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stocks/<int:stock_id>/signal")
def api_stock_signal(stock_id):
    """Get latest signal for a stock."""
    try:
        sig = db.get_latest_signal(stock_id)
        if not sig:
            return jsonify({"ok": True, "signal": None})
        return jsonify({"ok": True, "signal": {
            "signal_strength": sig.signal_strength.value if sig.signal_strength else None,
            "avg_sentiment": sig.avg_sentiment,
            "total_mentions": sig.total_mentions,
            "bullish_count": sig.bullish_count,
            "bearish_count": sig.bearish_count,
            "neutral_count": sig.neutral_count,
            "predicted_direction": sig.predicted_direction,
            "confidence": sig.confidence,
            "window_start": str(sig.window_start),
            "window_end": str(sig.window_end),
        }})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: RAW POSTS
# ══════════════════════════════════════════════════════════════

@app.route("/api/posts/dates")
def api_posts_dates():
    """Return distinct years, months, days available in raw_posts (for filter dropdowns)."""
    try:
        platform_filter = request.args.get("platform", "").strip()
        year_filter = request.args.get("year", "").strip()
        month_filter = request.args.get("month", "").strip()
        author_filter = request.args.get("author", "").strip()

        session = db.get_session()
        try:
            # Build a common base filter so all dropdown queries respect
            # platform and author selections.
            base_filters = [RawPost.posted_at.isnot(None)]
            if platform_filter:
                base_filters.append(RawPost.platform == Platform[platform_filter.upper()])
            if author_filter:
                base_filters.append(RawPost.author == author_filter)

            # Years
            years = sorted(set(
                int(r[0]) for r in
                session.query(distinct(extract('year', RawPost.posted_at)))
                .filter(*base_filters)
                .all() if r[0] is not None
            ), reverse=True)

            # Months — filtered by year if provided
            months = []
            if year_filter:
                months = sorted(set(
                    int(r[0]) for r in
                    session.query(distinct(extract('month', RawPost.posted_at)))
                    .filter(*base_filters,
                            extract('year', RawPost.posted_at) == int(year_filter))
                    .all() if r[0] is not None
                ))

            # Days — filtered by year+month if both provided
            days = []
            if year_filter and month_filter:
                days = sorted(set(
                    int(r[0]) for r in
                    session.query(distinct(extract('day', RawPost.posted_at)))
                    .filter(*base_filters,
                            extract('year', RawPost.posted_at) == int(year_filter),
                            extract('month', RawPost.posted_at) == int(month_filter))
                    .all() if r[0] is not None
                ))

            # Authors (handles) — distinct non-null authors
            author_filters = [RawPost.author.isnot(None), RawPost.author != '']
            if platform_filter:
                author_filters.append(RawPost.platform == Platform[platform_filter.upper()])
            authors = sorted(set(
                r[0] for r in
                session.query(distinct(RawPost.author))
                .filter(*author_filters)
                .all() if r[0]
            ))

            return jsonify({"ok": True, "years": years, "months": months,
                            "days": days, "authors": authors})
        finally:
            session.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/posts")
def api_posts():
    """Get recent raw posts (paginated, with optional date filters)."""
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 25))
        platform_filter = request.args.get("platform", "").strip()
        year_filter = request.args.get("year", "").strip()
        month_filter = request.args.get("month", "").strip()
        day_filter = request.args.get("day", "").strip()
        author_filter = request.args.get("author", "").strip()

        session = db.get_session()
        try:
            q = session.query(RawPost).order_by(RawPost.posted_at.desc())
            if platform_filter:
                q = q.filter(RawPost.platform == Platform[platform_filter.upper()])
            if year_filter:
                q = q.filter(extract('year', RawPost.posted_at) == int(year_filter))
            if month_filter:
                q = q.filter(extract('month', RawPost.posted_at) == int(month_filter))
            if day_filter:
                q = q.filter(extract('day', RawPost.posted_at) == int(day_filter))
            if author_filter:
                q = q.filter(RawPost.author == author_filter)
            total = q.count()
            posts = q.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            for p in posts:
                result.append({
                    "id": p.id,
                    "platform": p.platform.value if p.platform else None,
                    "author": p.author,
                    "text": (p.text_clean or p.text or "")[:300],
                    "posted_at": str(p.posted_at) if p.posted_at else None,
                    "views": p.views, "likes": p.likes, "shares": p.shares,
                    "is_processed": p.is_processed,
                    "is_stock_relevant": p.is_stock_relevant,
                    "url": p.url,
                })
            return jsonify({"ok": True, "posts": result, "total": total,
                            "page": page, "per_page": per_page})
        finally:
            session.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: VECTOR SEARCH
# ══════════════════════════════════════════════════════════════

@app.route("/api/search")
def api_search():
    """Semantic search across all posts."""
    try:
        q = request.args.get("q", "").strip()
        n = int(request.args.get("n", 10))
        platform = request.args.get("platform", None)
        if not q:
            return jsonify({"ok": False, "error": "Missing query param ?q="}), 400
        results = vs.search(query=q, n_results=n, platform=platform)
        return jsonify({"ok": True, "results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: SENTIMENT ANALYSIS (ad-hoc)
# ══════════════════════════════════════════════════════════════

@app.route("/api/sentiment/analyze", methods=["POST"])
def api_sentiment_analyze():
    """Analyze sentiment of arbitrary text."""
    try:
        text = request.json.get("text", "")
        result = sentiment.analyze(text)
        result["label"] = result["label"].value if hasattr(result["label"], "value") else str(result["label"])
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: STOCK IDENTIFICATION (ad-hoc)
# ══════════════════════════════════════════════════════════════

@app.route("/api/identify", methods=["POST"])
def api_identify():
    """Identify stocks mentioned in arbitrary text."""
    try:
        text = request.json.get("text", "")
        matches = identifier.identify_stocks(text)
        details = identifier.extract_trading_details(text)
        # resolve stock symbols
        for m in matches:
            stock = db.search_stock(str(m["stock_id"]))
            session = db.get_session()
            try:
                s = session.query(Stock).filter_by(id=m["stock_id"]).first()
                if s:
                    m["symbol"] = s.symbol
                    m["name"] = s.name
            finally:
                session.close()
        details_clean = {k: (v.value if hasattr(v, "value") else v) for k, v in details.items()}
        return jsonify({"ok": True, "stocks": matches, "details": details_clean})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: RAG PREDICTION
# ══════════════════════════════════════════════════════════════

@app.route("/api/predict", methods=["POST"])
def api_predict():
    """Generate AI-powered stock prediction via RAG."""
    try:
        rag = _get_rag()
        if rag is None:
            return jsonify({"ok": False,
                            "error": "LLM provider not configured. "
                                     "Set GEMINI_API_KEY / OPENAI_API_KEY / "
                                     "STOCKRAG_LLM_PROVIDER in .env"}), 400

        data = request.json
        symbol = data.get("symbol", "")
        hours = data.get("lookback_hours", 72)
        max_posts = data.get("max_posts", 20)

        prediction = rag.predict(symbol, lookback_hours=hours, max_posts=max_posts)
        return jsonify({"ok": True, "prediction": prediction})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/query", methods=["POST"])
def api_query():
    """General RAG question answering."""
    try:
        rag = _get_rag()
        if rag is None:
            return jsonify({"ok": False,
                            "error": "LLM provider not configured. "
                                     "Set GEMINI_API_KEY / OPENAI_API_KEY in .env"}), 400

        question = request.json.get("question", "")
        answer = rag.query(question)
        return jsonify({"ok": True, "answer": answer})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  API: SOURCES
# ══════════════════════════════════════════════════════════════

@app.route("/api/sources")
def api_sources():
    """List all data sources."""
    try:
        sources = db.get_sources()
        result = []
        for s in sources:
            result.append({
                "id": s.id,
                "platform": s.platform.value if s.platform else None,
                "handle": s.handle,
                "display_name": s.display_name,
                "category": s.category,
                "reliability_score": s.reliability_score,
                "created_at": str(s.created_at) if s.created_at else None,
            })
        return jsonify({"ok": True, "sources": result, "count": len(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    port = int(os.getenv("STOCKRAG_PORT", 5000))
    debug = os.getenv("STOCKRAG_DEBUG", "1") == "1"
    print(f"\n{'='*60}")
    print(f"  📈 StockRAG Web Dashboard")
    print(f"  http://localhost:{port}")
    print(f"  DB: {DB_PATH}  |  ChromaDB: {CHROMA_DIR}")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
