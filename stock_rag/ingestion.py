"""
Data Ingestion Pipeline - Adapts existing Apify scrapers to the database.
=========================================================================

This module bridges your existing scraper outputs (CSV/JSON from Apify)
and normalizes them into the unified RawPost schema for Level 1 DB.

It also supports live scraping via Apify API and direct ingestion.
"""

import os
import json
import re
import hashlib
from datetime import datetime
from typing import Dict
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from .database import Database, Platform

load_dotenv()

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN')
APIFY_BASE_URL = 'https://api.apify.com/v2'


# ──────────────────────────────────────────────────────────────────────# TELEGRAM HANDLE ↔ DISPLAY-NAME MAPPING
# Apify returns the Telegram handle/ID (e.g. "@DGPIndia") in the
# 'channel' field, whereas Telethon returns the human-readable title
# (e.g. "Wealthcreator").  This LUT keeps them consistent.
# Keys are normalised to lowercase, stripped of leading '@'.
# ──────────────────────────────────────────────────────────────────────
TELEGRAM_HANDLE_MAP: Dict[str, str] = {
    'dgpindia': 'Wealthcreator',
    'wealthcreator7': 'Wealthcreator',
    # Add more mappings as you scrape new channels:
    # 'channel_handle': 'Display Name',
}


def resolve_telegram_author(raw_author: str, fallback: str = '') -> str:
    """Map a Telegram handle / @-ID to its human-readable display name.

    Looks up *raw_author* (case-insensitive, stripped of leading '@') in
    ``TELEGRAM_HANDLE_MAP``.  Returns the mapped name, or *raw_author*
    itself if no mapping exists, or *fallback* as a last resort.
    """
    if not raw_author:
        return fallback or ''
    key = raw_author.lstrip('@').lower()
    mapped = TELEGRAM_HANDLE_MAP.get(key)
    if mapped:
        return mapped
    # If raw_author looks like a Telegram @handle, strip the '@'
    if raw_author.startswith('@'):
        return raw_author.lstrip('@')
    return raw_author or fallback


# ──────────────────────────────────────────────────────────────────────# PLATFORM NORMALIZERS
# ──────────────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Clean and normalize text content."""
    if not text:
        return ""
    # Remove URLs for clean version
    text_clean = re.sub(r'https?://\S+', '', text)
    # Remove excessive whitespace
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    return text_clean


def _generate_external_id(platform: str, data: dict) -> str:
    """Generate a stable external ID for deduplication."""
    # Try platform-specific IDs first
    for key in ['id', 'postId', 'tweet_id', 'tweetId', 'message_id', 'urn']:
        if key in data and data[key]:
            return str(data[key])

    # Fallback: hash of content + author + timestamp
    content = str(data.get('text', data.get('full_text', '')))
    author = str(data.get('author', data.get('username', '')))
    ts = str(data.get('date', data.get('timestamp', '')))
    return hashlib.md5(f"{platform}:{author}:{ts}:{content[:100]}".encode()).hexdigest()


def _safe_int(val, default=0):
    """Safely convert a value to int, handling dicts, lists, None, etc."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def normalize_telegram_post(raw: dict, source_id: int) -> dict:
    """Normalize a Telegram post from Apify output to RawPost schema."""
    text = raw.get('text', raw.get('message', raw.get('messageText', '')))

    posted_at = None
    for date_key in ['date', 'datetime', 'timestamp', 'messageDate']:
        if date_key in raw and raw[date_key]:
            try:
                if isinstance(raw[date_key], str):
                    posted_at = datetime.fromisoformat(raw[date_key].replace('Z', '+00:00'))
                elif isinstance(raw[date_key], (int, float)):
                    posted_at = datetime.utcfromtimestamp(raw[date_key])
                break
            except (ValueError, OSError):
                continue

    # Handle reactions: could be int, dict, list, or None
    reactions_raw = raw.get('reactions', raw.get('likes', 0))
    if isinstance(reactions_raw, dict):
        likes = sum(v for v in reactions_raw.values() if isinstance(v, (int, float)))
    elif isinstance(reactions_raw, list):
        likes = len(reactions_raw)
    else:
        likes = _safe_int(reactions_raw)

    # Resolve author: prefer 'channel', then 'channelName', then 'sender'.
    # Guard against purely-numeric values (raw channel IDs).
    author = ''
    for key in ('channel', 'channelName', 'sender'):
        candidate = raw.get(key, '')
        if candidate and not (str(candidate).replace(' ', '').isdigit()):
            author = str(candidate)
            break
    if not author:
        # All candidates were numeric/empty – keep first non-empty as last resort
        author = str(raw.get('channel', raw.get('channelName', raw.get('sender', ''))))
    # Apply handle → display-name mapping (e.g. @DGPIndia → Wealthcreator)
    author = resolve_telegram_author(author)

    return {
        'source_id': source_id,
        'platform': Platform.TELEGRAM,
        'external_id': _generate_external_id('telegram', raw),
        'url': raw.get('url', raw.get('messageUrl', '')),
        'text': text,
        'text_clean': _clean_text(text),
        'author': author,
        'author_url': raw.get('channelUrl', ''),
        'posted_at': posted_at,
        'views': _safe_int(raw.get('views', raw.get('viewCount', 0))),
        'likes': likes,
        'shares': _safe_int(raw.get('forwards', raw.get('shares', 0))),
        'comments_count': _safe_int(raw.get('comments', raw.get('repliesCount', 0))),
        'has_media': bool(raw.get('media', raw.get('hasMedia', False))),
        'media_urls': raw.get('mediaUrls', []),
        'reactions': raw.get('reactionsList', raw.get('reactions_detail', None)),
    }


def normalize_x_post(raw: dict, source_id: int) -> dict:
    """Normalize an X.com/Twitter post from Apify output to RawPost schema."""
    text = raw.get('full_text', raw.get('text', raw.get('tweetText', '')))

    posted_at = None
    for date_key in ['created_at', 'createdAt', 'date', 'timestamp']:
        if date_key in raw and raw[date_key]:
            try:
                if isinstance(raw[date_key], str):
                    # X.com format: "Wed Oct 10 20:19:24 +0000 2018"
                    try:
                        posted_at = datetime.strptime(raw[date_key], "%a %b %d %H:%M:%S %z %Y")
                    except ValueError:
                        posted_at = datetime.fromisoformat(raw[date_key].replace('Z', '+00:00'))
                break
            except (ValueError, OSError):
                continue

    return {
        'source_id': source_id,
        'platform': Platform.X,
        'external_id': _generate_external_id('x', raw),
        'url': raw.get('url', raw.get('tweetUrl', '')),
        'text': text,
        'text_clean': _clean_text(text),
        'author': raw.get('username', raw.get('user', {}).get('screen_name', '')),
        'author_url': raw.get('authorUrl', ''),
        'posted_at': posted_at,
        'views': _safe_int(raw.get('viewCount', raw.get('views', 0))),
        'likes': _safe_int(raw.get('favoriteCount', raw.get('likeCount', raw.get('likes', 0)))),
        'shares': _safe_int(raw.get('retweetCount', raw.get('retweets', 0))),
        'comments_count': _safe_int(raw.get('replyCount', raw.get('replies', 0))),
        'has_media': bool(raw.get('media', raw.get('hasMedia', raw.get('photos', [])))),
        'media_urls': raw.get('mediaUrls', raw.get('photos', [])),
    }


def normalize_linkedin_post(raw: dict, source_id: int) -> dict:
    """Normalize a LinkedIn post from Apify output to RawPost schema."""
    text = raw.get('text', raw.get('postText', raw.get('commentary', '')))

    posted_at = None
    for date_key in ['postedAt', 'date', 'publishedAt', 'timestamp']:
        if date_key in raw and raw[date_key]:
            try:
                if isinstance(raw[date_key], str):
                    posted_at = datetime.fromisoformat(raw[date_key].replace('Z', '+00:00'))
                elif isinstance(raw[date_key], (int, float)):
                    posted_at = datetime.utcfromtimestamp(raw[date_key] / 1000)  # LinkedIn uses ms
                break
            except (ValueError, OSError):
                continue

    return {
        'source_id': source_id,
        'platform': Platform.LINKEDIN,
        'external_id': _generate_external_id('linkedin', raw),
        'url': raw.get('url', raw.get('postUrl', '')),
        'text': text,
        'text_clean': _clean_text(text),
        'author': raw.get('author', raw.get('authorName', raw.get('profileName', ''))),
        'author_url': raw.get('authorUrl', raw.get('profileUrl', '')),
        'posted_at': posted_at,
        'views': _safe_int(raw.get('views', raw.get('numViews', 0))),
        'likes': _safe_int(raw.get('likes', raw.get('numLikes', raw.get('totalReactionCount', 0)))),
        'shares': _safe_int(raw.get('shares', raw.get('numShares', 0))),
        'comments_count': _safe_int(raw.get('comments', raw.get('numComments', 0))),
        'has_media': bool(raw.get('images', raw.get('media', []))),
        'media_urls': raw.get('images', raw.get('mediaUrls', [])),
    }


# Map platform to normalizer
NORMALIZERS = {
    Platform.TELEGRAM: normalize_telegram_post,
    Platform.X: normalize_x_post,
    Platform.LINKEDIN: normalize_linkedin_post,
}


# ──────────────────────────────────────────────────────────────────────
# INGESTION CLASS
# ──────────────────────────────────────────────────────────────────────

class DataIngestionPipeline:
    """
    Handles ingesting data from various sources into Level 1 DB.

    Supports:
    - Loading from existing CSV/JSON files (your current Apify output)
    - Live scraping via Apify API
    - Manual data insertion
    """

    def __init__(self, db: Database):
        self.db = db

    def ingest_from_json(self, file_path: str, platform: Platform,
                         handle: str, **source_kwargs) -> dict:
        """
        Ingest posts from a JSON file (Apify output format).
        Returns counts of inserted/skipped.
        """
        source = self.db.upsert_source(platform, handle, **source_kwargs)
        job = self.db.create_scrape_job(source.id, {"file": file_path})

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            data = [data]

        normalizer = NORMALIZERS.get(platform)
        if not normalizer:
            raise ValueError(f"No normalizer for platform: {platform}")

        posts = [normalizer(raw, source.id) for raw in data]
        result = self.db.bulk_insert_raw_posts(posts)

        self.db.complete_scrape_job(job.id, result['total'], result['inserted'])
        return result

    def ingest_from_csv(self, file_path: str, platform: Platform,
                        handle: str, **source_kwargs) -> dict:
        """Ingest posts from a CSV file."""
        source = self.db.upsert_source(platform, handle, **source_kwargs)
        job = self.db.create_scrape_job(source.id, {"file": file_path})

        df = pd.read_csv(file_path)
        data = df.to_dict(orient='records')

        normalizer = NORMALIZERS.get(platform)
        if not normalizer:
            raise ValueError(f"No normalizer for platform: {platform}")

        posts = [normalizer(raw, source.id) for raw in data]
        result = self.db.bulk_insert_raw_posts(posts)

        self.db.complete_scrape_job(job.id, result['total'], result['inserted'])
        return result

    def ingest_from_apify_live(self, platform: Platform, handle: str,
                               actor_id: str, actor_input: dict,
                               **source_kwargs) -> dict:
        """
        Run an Apify actor and ingest results directly.
        This wraps the Apify API call and normalizes output.
        """
        if not APIFY_TOKEN:
            raise ValueError("APIFY_API_TOKEN not set in environment")

        source = self.db.upsert_source(platform, handle, **source_kwargs)
        job = self.db.create_scrape_job(source.id, {
            "actor_id": actor_id, "input": actor_input
        })

        try:
            # Start the actor run
            url = f"{APIFY_BASE_URL}/acts/{actor_id}/runs"
            headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}
            resp = requests.post(url, json=actor_input, headers=headers, timeout=30)
            resp.raise_for_status()
            run_data = resp.json()['data']
            run_id = run_data['id']

            # Wait for completion
            status_url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
            while True:
                import time
                time.sleep(5)
                status_resp = requests.get(status_url, headers=headers, timeout=30)
                status = status_resp.json()['data']['status']
                if status in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                    break

            if status != 'SUCCEEDED':
                raise RuntimeError(f"Apify run {run_id} ended with status: {status}")

            # Fetch results
            dataset_id = run_data.get('defaultDatasetId')
            items_url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items"
            items_resp = requests.get(items_url, headers=headers, timeout=60)
            items = items_resp.json()

            normalizer = NORMALIZERS.get(platform)
            posts = [normalizer(raw, source.id) for raw in items]
            result = self.db.bulk_insert_raw_posts(posts)

            self.db.complete_scrape_job(job.id, result['total'], result['inserted'])
            return result

        except Exception as e:
            self.db.complete_scrape_job(job.id, 0, 0, error=str(e))
            raise

    def ingest_existing_files(self, base_dir: str = ".") -> dict:
        """
        Auto-discover and ingest existing CSV/JSON files from the workspace.
        Detects platform from filename patterns.
        """
        base = Path(base_dir)
        total_result = {"files_processed": 0, "total_inserted": 0, "total_skipped": 0}

        file_patterns = {
            Platform.TELEGRAM: ['telegram', 'apify_messages'],
            Platform.X: ['x_posts', 'tweets', 'twitter'],
            Platform.LINKEDIN: ['linkedin'],
        }

        for json_file in base.rglob("*.json"):
            fname = json_file.stem.lower()
            for platform, patterns in file_patterns.items():
                if any(p in fname for p in patterns):
                    try:
                        result = self.ingest_from_json(
                            str(json_file), platform, fname,
                            display_name=fname, category="auto_imported"
                        )
                        total_result["files_processed"] += 1
                        total_result["total_inserted"] += result["inserted"]
                        total_result["total_skipped"] += result["skipped"]
                        print(f"  ✓ {json_file.name}: {result['inserted']} new, {result['skipped']} dupes")
                    except Exception as e:
                        print(f"  ✗ {json_file.name}: {e}")
                    break

        for csv_file in base.rglob("*.csv"):
            fname = csv_file.stem.lower()
            for platform, patterns in file_patterns.items():
                if any(p in fname for p in patterns):
                    try:
                        result = self.ingest_from_csv(
                            str(csv_file), platform, fname,
                            display_name=fname, category="auto_imported"
                        )
                        total_result["files_processed"] += 1
                        total_result["total_inserted"] += result["inserted"]
                        total_result["total_skipped"] += result["skipped"]
                        print(f"  ✓ {csv_file.name}: {result['inserted']} new, {result['skipped']} dupes")
                    except Exception as e:
                        print(f"  ✗ {csv_file.name}: {e}")
                    break

        return total_result
