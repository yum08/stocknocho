"""X.com (Twitter) scraper using Apify REST API.

Features:
- Cloud-based scraping via Apify actors (no Twitter API keys needed)
- Scrape tweets by Twitter handles, search terms, or URLs
- Multiple actor backends: ppr (pay-per-result), full (V2), lite
- Configurable max tweets per handle
- Export to CSV, JSON, and Excel
- SSL fix for corporate/proxy environments
- Easy handle list — add handles to HANDLES list or via CLI

Usage:
  python apify_x_scraper.py --handles stockstix Derzuschauer7 adi408b --max-tweets 3
  python apify_x_scraper.py --handles elonmusk --actor full --max-tweets 10
  python apify_x_scraper.py --search "web scraping" --max-tweets 20
  python apify_x_scraper.py  # uses default HANDLES list below

Set APIFY_API_TOKEN in .env or environment variables.
Get your token from: https://console.apify.com/account/integrations
"""

import argparse
import os
import json
import sys
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

import requests
import pandas as pd
from dotenv import load_dotenv

# Fix SSL certificate issues on Windows (corporate proxies, etc.)
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

load_dotenv()

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN')
APIFY_BASE_URL = 'https://api.apify.com/v2'

# ─── DEFAULT HANDLES ────────────────────────────────────────────────
# Add or remove handles here for easy batch scraping.
# These are used when no --handles flag is provided on the CLI.
DEFAULT_HANDLES = [
    'stockstix',
    'Derzuschauer7',
    'adi408b',
    'rahul_saggi',
    'Suchitpatel',
    'vivekthebaria',
]
# ────────────────────────────────────────────────────────────────────

# Available X/Twitter scraper actors on Apify
ACTORS = {
    # danek/twitter-scraper-ppr: works reliably, one handle per run
    'ppr': {
        'id': 'ghSpYIW3L1RvT57NT',
        'name': 'danek/twitter-scraper-ppr',
        'description': 'Twitter Scraper PPR — reliable, one handle per run',
        'multi_handle': False,  # needs separate run per handle
    },
    # kaitoeasyapi: pay-per-result, supports search with "from:user"
    'search': {
        'id': 'CJdippxWmn9uRfooo',
        'name': 'kaitoeasyapi/tweet-scraper',
        'description': 'Tweet Scraper — search based, pay-per-result',
        'multi_handle': False,
    },
    # apidojo/tweet-scraper: full-featured V2 (may return demo data on free plan)
    'full': {
        'id': '61RPP7dywgiy0JPD0',
        'name': 'apidojo/tweet-scraper',
        'description': 'Tweet Scraper V2 — full featured (may need paid plan)',
        'multi_handle': True,
    },
}

DEFAULT_ACTOR = 'ppr'


def parse_args():
    p = argparse.ArgumentParser(
        description='Scrape X.com (Twitter) posts using Apify cloud infrastructure'
    )
    p.add_argument(
        '--handles', '-H',
        nargs='+',
        default=None,
        help='Twitter handles to scrape (without @). If omitted, uses DEFAULT_HANDLES list in script.'
    )
    p.add_argument(
        '--search', '-s',
        nargs='+',
        default=None,
        help='Search terms to scrape tweets for'
    )
    p.add_argument(
        '--urls', '-u',
        nargs='+',
        default=None,
        help='Direct Twitter/X URLs to scrape'
    )
    p.add_argument(
        '--actor', '-a',
        choices=list(ACTORS.keys()),
        default=DEFAULT_ACTOR,
        help=f'Apify actor to use (default: {DEFAULT_ACTOR})'
    )
    p.add_argument(
        '--max-tweets', '-n',
        type=int,
        default=3,
        help='Max tweets per handle/search (default: 3)'
    )
    p.add_argument(
        '--sort',
        choices=['Top', 'Latest'],
        default='Latest',
        help='Sort order for search results (default: Latest)'
    )
    p.add_argument(
        '--lang',
        default=None,
        help='Restrict tweets to language (ISO 639-1 code, e.g. en, hi)'
    )
    p.add_argument(
        '--out', '-o',
        default='x_posts.csv',
        help='Output CSV file path (default: x_posts.csv)'
    )
    p.add_argument(
        '--out-json',
        default=None,
        help='Optional JSON output file'
    )
    p.add_argument(
        '--out-excel',
        default=None,
        help='Optional Excel output file'
    )
    p.add_argument(
        '--wait-timeout',
        type=int,
        default=300,
        help='Max seconds to wait for actor run (default: 300)'
    )
    p.add_argument(
        '--memory-mb',
        type=int,
        default=256,
        help='Actor memory in MB (default: 256)'
    )
    return p.parse_args()


def normalize_handle(handle: str) -> str:
    """Normalize handle input — strip @, extract from URLs."""
    handle = handle.strip()
    for prefix in ('https://x.com/', 'https://twitter.com/', 'http://x.com/', 'http://twitter.com/',
                    'x.com/', 'twitter.com/'):
        if handle.lower().startswith(prefix.lower()):
            handle = handle[len(prefix):].split('/')[0].split('?')[0]
            break
    if handle.startswith('@'):
        handle = handle[1:]
    return handle


def apify_request(method: str, path: str, **kwargs) -> requests.Response:
    """Make an authenticated request to the Apify API."""
    url = f'{APIFY_BASE_URL}/{path}'
    params = kwargs.pop('params', {})
    params['token'] = APIFY_TOKEN
    resp = requests.request(method, url, params=params, **kwargs)
    if resp.status_code >= 400:
        print(f'API Error {resp.status_code}: {resp.text[:500]}')
    resp.raise_for_status()
    return resp


def build_actor_input(
    actor_type: str,
    handle: Optional[str] = None,
    handles: Optional[List[str]] = None,
    search_terms: Optional[List[str]] = None,
    urls: Optional[List[str]] = None,
    max_tweets: int = 3,
    sort: str = 'Latest',
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """Build input for the selected actor."""

    if actor_type == 'ppr':
        # danek actor: single username per run
        inp: Dict[str, Any] = {'max_posts': max_tweets}
        if handle:
            inp['username'] = handle
        elif search_terms:
            inp['query'] = ' '.join(search_terms)
            inp['search_type'] = sort.lower()
        return inp

    elif actor_type == 'search':
        # kaitoeasyapi actor: search-based, use "from:user" for handle
        inp = {'maxItems': max_tweets, 'queryType': sort}
        if handle:
            inp['twitterContent'] = f'from:{handle}'
        elif search_terms:
            inp['twitterContent'] = ' '.join(search_terms)
        if lang:
            inp['lang'] = lang
        return inp

    elif actor_type == 'full':
        # apidojo actor: multi-handle support
        normalized = [normalize_handle(h) for h in handles] if handles else []
        inp = {
            'maxItems': max_tweets * max(len(normalized), len(search_terms or []), 1),
            'sort': sort,
        }
        if normalized:
            inp['twitterHandles'] = normalized
            inp['startUrls'] = [f'https://x.com/{h}' for h in normalized]
        if search_terms:
            inp['searchTerms'] = search_terms
        if urls:
            inp['startUrls'] = inp.get('startUrls', []) + urls
        if lang:
            inp['tweetLanguage'] = lang
        return inp

    return {}


def start_actor_run(actor_id: str, actor_input: Dict, memory_mb: int = 256) -> Dict:
    """Start an actor run and return the run info."""
    resp = apify_request(
        'POST',
        f'acts/{actor_id}/runs',
        json=actor_input,
        params={'memory': memory_mb},
    )
    return resp.json().get('data', {})


def wait_for_run(run_id: str, timeout: int = 300, poll_interval: int = 5) -> Dict:
    """Poll the run status until it finishes or times out."""
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f'Timeout after {timeout}s. The run may still be running on Apify.')
            break

        resp = apify_request('GET', f'actor-runs/{run_id}')
        run_data = resp.json().get('data', {})
        status = run_data.get('status')

        if status in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
            return run_data

        remaining = int(timeout - elapsed)
        print(f'  Status: {status} | Elapsed: {int(elapsed)}s | Remaining: {remaining}s')
        time.sleep(poll_interval)

    resp = apify_request('GET', f'actor-runs/{run_id}')
    return resp.json().get('data', {})


def get_dataset_items(dataset_id: str) -> List[Dict]:
    """Fetch all items from a dataset."""
    items = []
    offset = 0
    limit = 1000
    while True:
        resp = apify_request(
            'GET',
            f'datasets/{dataset_id}/items',
            params={'offset': offset, 'limit': limit, 'format': 'json'},
        )
        batch = resp.json()
        if not batch:
            break
        items.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return items


def process_results(items: List[Dict], source_handle: str = '') -> List[Dict]:
    """Normalize tweet results into a consistent schema."""
    processed = []
    for item in items:
        # Skip empty/demo/error items
        if item.get('noResults') or item.get('demo'):
            continue

        author = item.get('author', {}) or {}

        record = {
            'tweet_id': item.get('tweet_id') or item.get('id') or item.get('id_str') or '',
            'handle': (
                author.get('screen_name') or author.get('userName') or
                item.get('twitterHandle') or item.get('handle') or
                source_handle or ''
            ),
            'display_name': (
                author.get('name') or ''
            ),
            'date': (
                item.get('created_at') or item.get('createdAt') or
                item.get('date') or item.get('timestamp') or ''
            ),
            'text': (
                item.get('text') or item.get('full_text') or
                item.get('tweetText') or item.get('content') or ''
            ),
            'url': '',
            'likes': (
                item.get('favorites') or item.get('likeCount') or
                item.get('favorite_count') or item.get('likes') or 0
            ),
            'retweets': (
                item.get('retweets') or item.get('retweetCount') or
                item.get('retweet_count') or 0
            ),
            'replies': (
                item.get('replies') or item.get('replyCount') or
                item.get('reply_count') or 0
            ),
            'views': item.get('views') or item.get('viewCount') or 0,
            'bookmarks': item.get('bookmarks') or item.get('bookmarkCount') or 0,
            'quotes': item.get('quotes') or item.get('quoteCount') or 0,
            'lang': item.get('lang') or '',
        }

        # Build tweet URL
        tid = record['tweet_id']
        handle = record['handle']
        if tid and handle:
            record['url'] = f'https://x.com/{handle}/status/{tid}'

        # Detect RT
        text = record['text']
        record['is_retweet'] = text.startswith('RT @') if text else False

        # Media
        media = item.get('media', {}) or {}
        media_urls = []
        if isinstance(media, dict):
            for mtype in ('photo', 'video', 'animated_gif'):
                entries = media.get(mtype, [])
                if isinstance(entries, list):
                    for m in entries:
                        if isinstance(m, dict):
                            u = m.get('media_url_https') or m.get('url')
                            if u:
                                media_urls.append(u)
        elif isinstance(media, list):
            for m in media:
                if isinstance(m, dict):
                    u = m.get('media_url_https') or m.get('url')
                    if u:
                        media_urls.append(u)

        record['has_media'] = bool(media_urls)
        if media_urls:
            record['media_urls'] = ' | '.join(media_urls)

        record['raw_json'] = json.dumps(item, default=str, ensure_ascii=False)
        processed.append(record)

    return processed


def save_results(
    data: List[Dict],
    csv_path: str,
    json_path: Optional[str] = None,
    excel_path: Optional[str] = None,
):
    """Save processed data to CSV and optionally JSON/Excel."""
    if not data:
        print('No data to save.')
        return

    df = pd.DataFrame(data)

    priority = [
        'tweet_id', 'handle', 'display_name', 'date', 'text', 'url',
        'likes', 'retweets', 'replies', 'views', 'bookmarks', 'quotes',
        'lang', 'is_retweet', 'has_media', 'media_urls',
    ]
    cols = [c for c in priority if c in df.columns]
    cols += [c for c in df.columns if c not in cols]
    df = df[cols]

    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'Saved {len(df)} records to {csv_path}')

    if json_path:
        df.to_json(json_path, orient='records', force_ascii=False, indent=2)
        print(f'Saved JSON to {json_path}')

    if excel_path:
        df_excel = df.drop(columns=['raw_json'], errors='ignore')
        df_excel.to_excel(excel_path, index=False)
        print(f'Saved Excel to {excel_path}')


def scrape_single_handle(
    handle: str,
    actor_info: Dict,
    actor_type: str,
    max_tweets: int,
    sort: str,
    lang: Optional[str],
    memory_mb: int,
    wait_timeout: int,
) -> List[Dict]:
    """Run the scraper for a single handle and return processed results."""
    actor_id = actor_info['id']
    normalized = normalize_handle(handle)

    actor_input = build_actor_input(
        actor_type=actor_type,
        handle=normalized,
        max_tweets=max_tweets,
        sort=sort,
        lang=lang,
    )

    print(f'\n  Starting run for @{normalized}...')
    run_info = start_actor_run(actor_id, actor_input, memory_mb=memory_mb)
    run_id = run_info.get('id')
    if not run_id:
        print(f'  ERROR: Failed to start run for @{normalized}')
        return []
    print(f'  Run: {run_id}')

    final_run = wait_for_run(run_id, timeout=wait_timeout)
    status = final_run.get('status')

    if status != 'SUCCEEDED':
        print(f'  WARNING: @{normalized} run status: {status}')
        return []

    dataset_id = final_run.get('defaultDatasetId')
    if not dataset_id:
        print(f'  No dataset for @{normalized}')
        return []

    raw_items = get_dataset_items(dataset_id)
    processed = process_results(raw_items, source_handle=normalized)
    print(f'  @{normalized}: {len(processed)} tweets scraped')
    return processed


def main():
    args = parse_args()

    if not APIFY_TOKEN:
        print('ERROR: APIFY_API_TOKEN not set.')
        print('Get your token from: https://console.apify.com/account/integrations')
        sys.exit(1)

    # Use default handles if none specified and no search/urls
    handles = args.handles
    if not handles and not args.search and not args.urls:
        handles = DEFAULT_HANDLES
        print(f'Using default handles: {handles}')
        print('(Edit DEFAULT_HANDLES in script or use --handles to override)\n')

    actor_info = ACTORS[args.actor]
    actor_name = actor_info['name']

    normalized = [normalize_handle(h) for h in handles] if handles else []

    print('=' * 60)
    print('Apify X.com (Twitter) Scraper')
    print('=' * 60)
    if normalized:
        print(f'Handles    : {["@" + h for h in normalized]}')
    if args.search:
        print(f'Search     : {args.search}')
    print(f'Actor      : {actor_name}')
    print(f'Description: {actor_info["description"]}')
    print(f'Max tweets : {args.max_tweets} per handle')
    print(f'Sort       : {args.sort}')
    print('=' * 60)

    all_results: List[Dict] = []

    if actor_info.get('multi_handle') and normalized:
        # Multi-handle actors: single run for all handles
        actor_input = build_actor_input(
            actor_type=args.actor,
            handles=handles,
            search_terms=args.search,
            urls=args.urls,
            max_tweets=args.max_tweets,
            sort=args.sort,
            lang=args.lang,
        )
        print(f'\nStarting actor run for all handles...')
        print(f'Input: {json.dumps(actor_input, indent=2)}')
        run_info = start_actor_run(actor_info['id'], actor_input, memory_mb=args.memory_mb)
        run_id = run_info.get('id')
        if not run_id:
            print('ERROR: Failed to start actor run.')
            sys.exit(1)
        print(f'Run: {run_id}')
        print(f'View on Apify: https://console.apify.com/actors/runs/{run_id}')

        print('Waiting for actor to finish...')
        final_run = wait_for_run(run_id, timeout=args.wait_timeout)
        status = final_run.get('status')
        print(f'Status: {status}')

        if status == 'SUCCEEDED':
            dataset_id = final_run.get('defaultDatasetId')
            if dataset_id:
                raw_items = get_dataset_items(dataset_id)
                all_results = process_results(raw_items)
    else:
        # Single-handle actors: run one per handle
        if normalized:
            total = len(normalized)
            for i, handle in enumerate(normalized, 1):
                print(f'\n[{i}/{total}] Scraping @{handle}...')
                results = scrape_single_handle(
                    handle=handle,
                    actor_info=actor_info,
                    actor_type=args.actor,
                    max_tweets=args.max_tweets,
                    sort=args.sort,
                    lang=args.lang,
                    memory_mb=args.memory_mb,
                    wait_timeout=args.wait_timeout,
                )
                all_results.extend(results)

        # Search terms
        if args.search:
            for term in args.search:
                print(f'\nSearching: "{term}"...')
                actor_input = build_actor_input(
                    actor_type=args.actor,
                    search_terms=[term],
                    max_tweets=args.max_tweets,
                    sort=args.sort,
                    lang=args.lang,
                )
                run_info = start_actor_run(actor_info['id'], actor_input, memory_mb=args.memory_mb)
                run_id = run_info.get('id')
                if run_id:
                    final_run = wait_for_run(run_id, timeout=args.wait_timeout)
                    if final_run.get('status') == 'SUCCEEDED':
                        dataset_id = final_run.get('defaultDatasetId')
                        if dataset_id:
                            raw_items = get_dataset_items(dataset_id)
                            all_results.extend(process_results(raw_items))

    print(f'\n{"="*60}')
    print(f'Total tweets collected: {len(all_results)}')
    print(f'{"="*60}')

    # Save results
    save_results(
        all_results,
        csv_path=args.out,
        json_path=args.out_json,
        excel_path=args.out_excel,
    )

    # Summary
    if all_results:
        print(f'\n{"="*60}')
        print('SUMMARY')
        print(f'{"="*60}')
        df = pd.DataFrame(all_results)
        for handle in df['handle'].unique():
            hdf = df[df['handle'] == handle]
            print(f'\n@{handle} ({len(hdf)} tweets):')
            for _, row in hdf.iterrows():
                text = str(row.get('text', '')).replace('\n', ' ')[:120]
                date = str(row.get('date', ''))
                likes = row.get('likes', 0)
                rt = row.get('retweets', 0)
                views = row.get('views', 0)
                url = row.get('url', '')
                is_rt = ' [RT]' if row.get('is_retweet') else ''
                print(f'  [{date}]{is_rt}')
                print(f'    {text}')
                print(f'    Likes: {likes} | RT: {rt} | Views: {views} | {url}')

    print('\nDone!')


if __name__ == '__main__':
    main()
