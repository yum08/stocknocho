"""LinkedIn profile posts scraper using Apify REST API.

Features:
- Cloud-based scraping via Apify actors (no LinkedIn cookies needed)
- Scrape posts by LinkedIn profile username or URL
- Returns post text, reactions, comments count, media/images
- Configurable max posts per profile
- Export to CSV, JSON, and Excel
- SSL fix for corporate/proxy environments
- Easy profile list — add profiles to DEFAULT_PROFILES or via CLI

Usage:
  python apify_linkedin_scraper.py --profiles kavishka-abeywardana-01b891214 --max-posts 3
  python apify_linkedin_scraper.py --profiles satyanadella billgates --max-posts 5
  python apify_linkedin_scraper.py  # uses DEFAULT_PROFILES list below

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

# ─── DEFAULT PROFILES ───────────────────────────────────────────────
# Add or remove LinkedIn profile usernames here for batch scraping.
# These are used when no --profiles flag is provided on the CLI.
DEFAULT_PROFILES = [
    'kavishka-abeywardana-01b891214',
]
# ────────────────────────────────────────────────────────────────────

# Available LinkedIn post scraper actors on Apify
ACTORS = {
    # apimaestro/linkedin-profile-posts: reliable, no cookies needed
    'profile_posts': {
        'id': 'LQQIXN9Othf8f7R5n',
        'name': 'apimaestro/linkedin-profile-posts',
        'description': 'Profile Posts Scraper for LinkedIn [No Cookies]',
    },
}

DEFAULT_ACTOR = 'profile_posts'


def parse_args():
    p = argparse.ArgumentParser(
        description='Scrape LinkedIn profile posts using Apify cloud infrastructure'
    )
    p.add_argument(
        '--profiles', '-P',
        nargs='+',
        default=None,
        help='LinkedIn profile usernames or URLs. If omitted, uses DEFAULT_PROFILES list in script.'
    )
    p.add_argument(
        '--actor', '-a',
        choices=list(ACTORS.keys()),
        default=DEFAULT_ACTOR,
        help=f'Apify actor to use (default: {DEFAULT_ACTOR})'
    )
    p.add_argument(
        '--max-posts', '-n',
        type=int,
        default=10,
        help='Max posts per profile (default: 10)'
    )
    p.add_argument(
        '--out', '-o',
        default='linkedin_posts.csv',
        help='Output CSV file path (default: linkedin_posts.csv)'
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


# ─── HELPERS ─────────────────────────────────────────────────────────

def normalize_profile(profile: str) -> str:
    """Extract LinkedIn username from URL or handle string."""
    profile = profile.strip().rstrip('/')
    # Handle full URLs like https://www.linkedin.com/in/username/
    for prefix in (
        'https://www.linkedin.com/in/',
        'https://linkedin.com/in/',
        'http://www.linkedin.com/in/',
        'http://linkedin.com/in/',
        'www.linkedin.com/in/',
        'linkedin.com/in/',
    ):
        if profile.lower().startswith(prefix.lower()):
            profile = profile[len(prefix):].split('/')[0].split('?')[0]
            break
    return profile


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


def start_actor_run(actor_id: str, run_input: Dict, memory_mb: int = 256) -> Dict:
    """Start an Apify actor run and return run data."""
    resp = apify_request(
        'POST',
        f'acts/{actor_id}/runs',
        params={'memory': memory_mb},
        json=run_input,
        headers={'Content-Type': 'application/json'},
    )
    return resp.json().get('data', {})


def wait_for_run(run_id: str, timeout: int = 300) -> Dict:
    """Poll until actor run completes or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        resp = apify_request('GET', f'actor-runs/{run_id}')
        data = resp.json().get('data', {})
        status = data.get('status', '')
        if status in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
            return data
        elapsed = int(time.time() - start)
        print(f'  [{elapsed}s] Waiting… status={status}')
        time.sleep(5)
    print(f'  Timeout after {timeout}s')
    return {}


def get_dataset_items(dataset_id: str) -> List[Dict]:
    """Retrieve all items from an Apify dataset."""
    resp = apify_request('GET', f'datasets/{dataset_id}/items')
    return resp.json() if resp.status_code == 200 else []


# ─── PROCESSING ──────────────────────────────────────────────────────

def process_post(post: Dict) -> Dict:
    """Normalize a single LinkedIn post into a flat dictionary."""
    # Author info
    author = post.get('author', {})
    author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip()
    username = author.get('username', '')
    profile_url = author.get('profile_url', '')
    profile_picture = author.get('profile_picture', '')

    # Post timing
    posted_at = post.get('posted_at', {})
    date_str = posted_at.get('date', '')
    relative_str = posted_at.get('relative', '')

    # Stats
    stats = post.get('stats', {})
    total_reactions = stats.get('total_reactions', 0)
    likes = stats.get('like', 0)
    love = stats.get('love', 0)
    insight = stats.get('insight', 0)
    support = stats.get('support', 0)
    celebrate = stats.get('celebrate', 0)
    funny = stats.get('funny', 0)
    comments = stats.get('comments', 0)
    reposts = stats.get('reposts', 0)

    # Media
    media = post.get('media', {})
    media_type = media.get('type', '')
    media_url = media.get('url', '')
    images = media.get('images', [])
    image_urls = [img.get('url', '') for img in images if img.get('url')]

    # URN / ID
    urn = post.get('urn', {})
    activity_urn = urn.get('activity_urn', '')

    return {
        'activity_id': activity_urn,
        'author': author_name,
        'username': username,
        'headline': author.get('headline', ''),
        'profile_url': profile_url,
        'profile_picture': profile_picture,
        'date': date_str,
        'relative_time': relative_str,
        'text': (post.get('text') or '')[:500],
        'full_text': post.get('text', ''),
        'post_url': post.get('url', ''),
        'post_type': post.get('post_type', ''),
        'total_reactions': total_reactions,
        'likes': likes,
        'love': love,
        'insight': insight,
        'support': support,
        'celebrate': celebrate,
        'funny': funny,
        'comments': comments,
        'reposts': reposts,
        'media_type': media_type,
        'media_url': media_url,
        'image_urls': '; '.join(image_urls),
    }


def scrape_profile(
    profile: str,
    actor_type: str,
    max_posts: int,
    memory_mb: int,
    timeout: int,
) -> List[Dict]:
    """Scrape posts from a single LinkedIn profile."""
    actor = ACTORS[actor_type]
    actor_id = actor['id']
    username = normalize_profile(profile)

    print(f'\n{"="*60}')
    print(f'Scraping LinkedIn posts for: {username}')
    print(f'Actor: {actor["name"]}  |  Max posts: {max_posts}')
    print(f'{"="*60}')

    run_input = {
        'username': username,
        'limit': min(max_posts, 100),
        'total_posts': max_posts,
    }

    # Start actor run
    print(f'Starting actor run…')
    run_data = start_actor_run(actor_id, run_input, memory_mb)
    run_id = run_data.get('id')
    if not run_id:
        print(f'ERROR: Failed to start run. Response: {run_data}')
        return []
    print(f'Run ID: {run_id}  |  Status: {run_data.get("status")}')

    # Wait for completion
    final = wait_for_run(run_id, timeout)
    status = final.get('status', 'UNKNOWN')
    if status != 'SUCCEEDED':
        print(f'Run ended with status: {status}')
        # Print log snippet for debugging
        try:
            log = apify_request('GET', f'actor-runs/{run_id}/log')
            print(f'Log (last 500 chars): …{log.text[-500:]}')
        except Exception:
            pass
        return []

    # Fetch results
    dataset_id = final.get('defaultDatasetId')
    if not dataset_id:
        print('No dataset found.')
        return []

    raw_items = get_dataset_items(dataset_id)
    print(f'Retrieved {len(raw_items)} posts from API')

    # Process
    processed = [process_post(item) for item in raw_items]
    for p in processed:
        p['scraped_profile'] = username
    return processed


def save_results(all_posts: List[Dict], args):
    """Save scraped posts to CSV, JSON, and optionally Excel."""
    if not all_posts:
        print('\nNo posts to save.')
        return

    # Determine columns for CSV (exclude full_text to keep CSV compact)
    csv_columns = [
        'scraped_profile', 'activity_id', 'author', 'username', 'headline',
        'date', 'relative_time', 'text', 'post_url', 'post_type',
        'total_reactions', 'likes', 'love', 'insight', 'support',
        'celebrate', 'funny', 'comments', 'reposts',
        'media_type', 'media_url', 'image_urls',
    ]
    df = pd.DataFrame(all_posts)
    csv_cols = [c for c in csv_columns if c in df.columns]

    # CSV
    csv_path = args.out
    df[csv_cols].to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'\nSaved {len(df)} posts to {csv_path}')

    # JSON — always save alongside CSV
    json_path = args.out_json or csv_path.rsplit('.', 1)[0] + '.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_posts, f, indent=2, ensure_ascii=False, default=str)
    print(f'Saved JSON to {json_path}')

    # Excel
    excel_path = args.out_excel or csv_path.rsplit('.', 1)[0] + '.xlsx'
    try:
        df[csv_cols].to_excel(excel_path, index=False, engine='openpyxl')
        print(f'Saved Excel to {excel_path}')
    except Exception as e:
        print(f'Excel save failed: {e}')


def print_summary(all_posts: List[Dict], max_display: int = 3):
    """Print a rich summary of scraped posts."""
    if not all_posts:
        return

    # Group by profile
    profiles = {}
    for post in all_posts:
        prof = post.get('scraped_profile', 'unknown')
        profiles.setdefault(prof, []).append(post)

    print(f'\n{"="*70}')
    print(f'LINKEDIN SCRAPE SUMMARY — {len(all_posts)} posts from {len(profiles)} profile(s)')
    print(f'{"="*70}')

    for prof, posts in profiles.items():
        # Sort by date descending
        posts.sort(key=lambda p: p.get('date', ''), reverse=True)
        print(f'\n▶ Profile: {prof} ({len(posts)} posts scraped)')
        if posts:
            print(f'  Author: {posts[0].get("author", "")}')
            print(f'  Headline: {posts[0].get("headline", "")}')
        print(f'  Latest {min(max_display, len(posts))} posts:')

        for i, post in enumerate(posts[:max_display]):
            text_preview = (post.get('text') or '')[:150].replace('\n', ' ')
            print(f'\n  [{i+1}] {post.get("date", "?")}  ({post.get("relative_time", "")})')
            print(f'      Text: {text_preview}…' if len(post.get('text', '')) > 150 else f'      Text: {text_preview}')
            print(f'      Reactions: {post.get("total_reactions", 0)}  |  Comments: {post.get("comments", 0)}  |  Reposts: {post.get("reposts", 0)}')
            if post.get('media_type'):
                print(f'      Media: {post["media_type"]} — {post.get("media_url", "")[:120]}')
            if post.get('image_urls'):
                imgs = post['image_urls'].split('; ')
                for j, img in enumerate(imgs[:3]):
                    print(f'      Image {j+1}: {img[:150]}')
            print(f'      Link: {post.get("post_url", "")[:150]}')


# ─── MAIN ────────────────────────────────────────────────────────────

def main():
    if not APIFY_TOKEN:
        print('ERROR: Set APIFY_API_TOKEN in .env or as environment variable.')
        sys.exit(1)

    args = parse_args()
    profiles = args.profiles or DEFAULT_PROFILES

    # Normalize profiles
    profiles = [normalize_profile(p) for p in profiles]
    print(f'Profiles to scrape: {profiles}')

    all_posts = []
    for profile in profiles:
        posts = scrape_profile(
            profile=profile,
            actor_type=args.actor,
            max_posts=args.max_posts,
            memory_mb=args.memory_mb,
            timeout=args.wait_timeout,
        )
        all_posts.extend(posts)

    # Save & display
    save_results(all_posts, args)
    print_summary(all_posts)

    return all_posts


if __name__ == '__main__':
    main()
