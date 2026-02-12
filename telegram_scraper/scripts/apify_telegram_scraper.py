"""Enhanced Telegram scraper using Apify REST API.

Features:
- Cloud-based scraping (no personal Telegram credentials needed)
- Automatic proxy rotation via Apify residential proxies
- Support for multiple channels in one run
- Date range filtering (days lookback)
- Media downloading support
- Fallback between multiple scraper actors
- Export to CSV, JSON, and Excel
- SSL fix for corporate/proxy environments

Usage:
  python apify_telegram_scraper.py --channels DGPIndia --days 7 --max-posts 50
  python apify_telegram_scraper.py --channels durov telegram --days 3 --out messages.csv
  python apify_telegram_scraper.py --channels myChannel --actor posts --posts-from 1 --posts-to 100

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

# Available Telegram scraper actors on Apify
ACTORS = {
    # webfinity: good for quick scrapes, max 200 posts/channel, days lookback
    'media': {
        'id': 'f9ah2tzQwzhF8OyfK',
        'name': 'webfinity/telegram-channel-content-media-scraper-v2',
        'description': 'Up to 200 posts/channel with media support',
    },
    # danielmilevski9: post range scraping, unlimited posts
    'posts': {
        'id': '73JZk4CeKcDsWoJQu',
        'name': 'danielmilevski9/telegram-channel-scraper',
        'description': 'Post range scraping, needs residential proxy',
    },
    # cheapget: message extraction with date filtering
    'messages': {
        'id': 'TpLqaxMYSJzwVnXoj',
        'name': 'cheapget/telegram-channel-message',
        'description': 'Message extraction with date filtering',
    },
}

DEFAULT_ACTOR = 'media'


def parse_args():
    p = argparse.ArgumentParser(
        description='Scrape Telegram channels using Apify cloud infrastructure'
    )
    p.add_argument(
        '--channels', '-c',
        nargs='+',
        required=True,
        help='Channel usernames (without @) or t.me URLs'
    )
    p.add_argument(
        '--actor', '-a',
        choices=list(ACTORS.keys()),
        default=DEFAULT_ACTOR,
        help=f'Apify actor to use (default: {DEFAULT_ACTOR})'
    )
    p.add_argument(
        '--max-posts',
        type=int,
        default=50,
        help='Max posts per channel (default: 50, max: 200 for "media" actor)'
    )
    p.add_argument(
        '--days',
        type=int,
        default=7,
        help='Days lookback for posts (default: 7, max: 30)'
    )
    p.add_argument(
        '--posts-from',
        type=int,
        default=None,
        help='Start post number (for "posts" actor only)'
    )
    p.add_argument(
        '--posts-to',
        type=int,
        default=None,
        help='End post number (for "posts" actor only)'
    )
    p.add_argument(
        '--download-media',
        action='store_true',
        help='Download media files (for "media" actor)'
    )
    p.add_argument(
        '--out', '-o',
        default='apify_messages.csv',
        help='Output CSV file path (default: apify_messages.csv)'
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
        default=4096,
        help='Actor memory in MB (default: 4096)'
    )
    return p.parse_args()


def normalize_channel(channel: str) -> str:
    """Normalize channel input to plain username."""
    channel = channel.strip()
    if 't.me/' in channel:
        channel = channel.split('t.me/')[-1].split('/')[0].split('?')[0]
    if channel.startswith('@'):
        channel = channel[1:]
    return channel


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
    channels: List[str],
    actor_type: str,
    max_posts: int = 50,
    days: int = 7,
    posts_from: Optional[int] = None,
    posts_to: Optional[int] = None,
    download_media: bool = False,
) -> Dict[str, Any]:
    """Build input for the selected actor."""
    normalized = [normalize_channel(c) for c in channels]

    if actor_type == 'media':
        # webfinity actor: comma-separated channels, maxPosts up to 200
        return {
            'channels': ', '.join(normalized),
            'maxPosts': min(max_posts, 200),
            'daysRange': min(days, 30),
            'includeText': True,
            'mediaOnly': False,
            'downloadMedia': download_media,
        }
    elif actor_type == 'posts':
        # danielmilevski9 actor: channel list, post range
        return {
            'channels': normalized,
            'postsFrom': posts_from or 1,
            'postsTo': posts_to or max_posts,
            'proxy': {
                'useApifyProxy': True,
                'apifyProxyGroups': ['RESIDENTIAL'],
            },
        }
    elif actor_type == 'messages':
        # cheapget actor: single channel URL, max_results, date filter
        return {
            'telegram_url': f'https://t.me/{normalized[0]}',
            'max_results': max_posts,
            'download_medias': 'text',
            'start_date': f'{days} days',
        }

    return {}


def start_actor_run(actor_id: str, actor_input: Dict, memory_mb: int = 4096) -> Dict:
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


def process_results(items: List[Dict]) -> List[Dict]:
    """Normalize results from any actor into a consistent schema."""
    processed = []
    for item in items:
        record = {
            'id': item.get('id') or item.get('messageId') or item.get('postId') or item.get('post_id'),
            'channel': (
                item.get('channel') or item.get('channelUsername') or
                item.get('channelName') or item.get('source') or
                item.get('profileName')
            ),
            'date': (
                item.get('date') or item.get('timestamp') or
                item.get('datetime') or item.get('postDate') or
                item.get('created_at')
            ),
            'text': (
                item.get('text') or item.get('message') or
                item.get('content') or item.get('postText') or ''
            ),
            'views': item.get('views') or item.get('viewCount') or item.get('view_count') or 0,
            'forwards': item.get('forwards') or item.get('forwardCount') or item.get('share_count') or 0,
            'replies': item.get('replies') or item.get('replyCount') or item.get('comment_count') or 0,
            'url': item.get('url') or item.get('postUrl') or item.get('link') or item.get('post_url'),
            'has_media': bool(
                item.get('media') or item.get('photo') or
                item.get('images') or item.get('mediaUrl') or
                item.get('imageUrl') or item.get('media_urls')
            ),
        }

        # Extract media URLs if available
        media_urls = []
        for key in ('mediaUrl', 'imageUrl', 'media_urls', 'photo', 'images'):
            val = item.get(key)
            if val:
                if isinstance(val, list):
                    media_urls.extend(str(v) for v in val)
                else:
                    media_urls.append(str(val))
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

    priority = ['id', 'channel', 'date', 'text', 'views', 'forwards', 'replies', 'url', 'has_media', 'media_urls']
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


def main():
    args = parse_args()

    if not APIFY_TOKEN:
        print('ERROR: APIFY_API_TOKEN not set.')
        print('Get your token from: https://console.apify.com/account/integrations')
        sys.exit(1)

    actor_info = ACTORS[args.actor]
    actor_id = actor_info['id']
    actor_name = actor_info['name']

    channels = args.channels
    normalized = [normalize_channel(c) for c in channels]

    actor_input = build_actor_input(
        channels=channels,
        actor_type=args.actor,
        max_posts=args.max_posts,
        days=args.days,
        posts_from=args.posts_from,
        posts_to=args.posts_to,
        download_media=args.download_media,
    )

    print('=' * 60)
    print('Apify Telegram Scraper')
    print('=' * 60)
    print(f'Channels   : {normalized}')
    print(f'Actor      : {actor_name}')
    print(f'Description: {actor_info["description"]}')
    print(f'Max posts  : {args.max_posts}')
    print(f'Days       : {args.days}')
    print(f'Actor input:\n{json.dumps(actor_input, indent=2)}')
    print('=' * 60)

    # Start the actor run
    print(f'\nStarting actor run...')
    run_info = start_actor_run(actor_id, actor_input, memory_mb=args.memory_mb)
    run_id = run_info.get('id')
    print(f'Run started: {run_id}')
    print(f'View on Apify: https://console.apify.com/actors/runs/{run_id}')

    # Wait for completion
    print('Waiting for actor to finish (this may take a few minutes)...')
    final_run = wait_for_run(run_id, timeout=args.wait_timeout)
    status = final_run.get('status')
    print(f'\nActor run finished. Status: {status}')

    if status != 'SUCCEEDED':
        print(f'WARNING: Run status is {status}.')
        stats = final_run.get('stats', {})
        if stats:
            print(f'Stats: {json.dumps(stats, indent=2, default=str)}')
        if status in ('FAILED', 'ABORTED'):
            print('The run failed. Check Apify console for details.')
            sys.exit(1)

    # Fetch results
    dataset_id = final_run.get('defaultDatasetId')
    if not dataset_id:
        print('No dataset found.')
        sys.exit(1)

    print(f'Fetching results from dataset {dataset_id}...')
    raw_items = get_dataset_items(dataset_id)
    print(f'Retrieved {len(raw_items)} raw items')

    # Process and save
    processed = process_results(raw_items)
    save_results(
        processed,
        csv_path=args.out,
        json_path=args.out_json,
        excel_path=args.out_excel,
    )

    print('\nDone!')


if __name__ == '__main__':
    main()
