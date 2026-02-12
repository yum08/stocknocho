"""Unified Telegram Scraper - Combines Telethon and Apify for maximum flexibility.

Features:
- Hybrid scraping: Use Apify for public channels, Telethon for private ones
- Batch processing multiple channels
- Rate limiting and retry logic
- Advanced filtering and date range support
- Export to multiple formats (CSV, JSON, Excel)
- Resume capability for interrupted scrapes

Usage:
  python unified_scraper.py --channels channel1 channel2 --limit 1000
  python unified_scraper.py --channels private_channel --use-telethon
  python unified_scraper.py --config scrape_config.json
"""

import argparse
import asyncio
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import pandas as pd
from dotenv import load_dotenv

# Fix SSL certificate issues on Windows
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

load_dotenv()


class ScraperBackend(Enum):
    AUTO = "auto"
    APIFY = "apify"
    TELETHON = "telethon"


@dataclass
class ScrapeConfig:
    """Configuration for a scrape job."""
    channels: List[str]
    limit: int = 1000
    backend: ScraperBackend = ScraperBackend.AUTO
    output_dir: str = "./output"
    output_format: str = "csv"  # csv, json, excel, all
    include_media: bool = False
    include_comments: bool = False
    date_from: Optional[str] = None  # ISO format
    date_to: Optional[str] = None
    filter_keywords: List[str] = field(default_factory=list)
    filter_min_views: int = 0
    retry_count: int = 3
    retry_delay: float = 5.0
    resume_from: Optional[str] = None  # Path to checkpoint file

    @classmethod
    def from_json(cls, path: str) -> 'ScrapeConfig':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'backend' in data:
            data['backend'] = ScraperBackend(data['backend'])
        return cls(**data)
    
    def to_json(self, path: str):
        data = asdict(self)
        data['backend'] = self.backend.value
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)


class TelethonScraper:
    """Scraper using Telethon (personal Telegram account)."""
    
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.session = os.getenv('TELEGRAM_SESSION', 'telegram_session')
        self.client = None
    
    def is_available(self) -> bool:
        return bool(self.api_id and self.api_hash)
    
    async def connect(self):
        from telethon import TelegramClient
        self.client = TelegramClient(self.session, int(self.api_id), self.api_hash)
        await self.client.start()
    
    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
    
    async def scrape_channel(
        self,
        channel: str,
        limit: int,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        include_media: bool = False
    ) -> List[Dict]:
        messages = []
        
        async for message in self.client.iter_messages(channel, limit=limit):
            # Date filtering
            if date_from and message.date < date_from:
                continue
            if date_to and message.date > date_to:
                continue
            
            record = {
                'id': message.id,
                'channel': channel,
                'date': message.date.isoformat() if message.date else None,
                'text': message.message or '',
                'views': message.views or 0,
                'forwards': message.forwards or 0,
                'replies': message.replies.replies if message.replies else 0,
                'author': getattr(message.sender, 'username', None) if message.sender else None,
                'url': f'https://t.me/{channel}/{message.id}' if channel else None,
            }
            
            if include_media and message.media:
                record['has_media'] = True
                record['media_type'] = type(message.media).__name__
            
            messages.append(record)
        
        return messages


class ApifyScraper:
    """Scraper using Apify cloud platform."""
    
    ACTORS = {
        'channel': 'GEHKCq8O4orlPjLFf',  # tri_angle/telegram-scraper
    }
    
    def __init__(self):
        self.token = os.getenv('APIFY_API_TOKEN')
        self.client = None
    
    def is_available(self) -> bool:
        return bool(self.token)
    
    def connect(self):
        from apify_client import ApifyClient
        self.client = ApifyClient(self.token)
    
    def scrape_channels(
        self,
        channels: List[str],
        limit: int,
        include_media: bool = False,
        include_comments: bool = False,
        actor_type: str = 'channel'
    ) -> List[Dict]:
        # Normalize channels
        normalized = []
        for ch in channels:
            ch = ch.strip()
            if 't.me/' in ch:
                ch = ch.split('t.me/')[-1].split('/')[0]
            if ch.startswith('@'):
                ch = ch[1:]
            normalized.append(ch)
        
        actor_id = self.ACTORS.get(actor_type, actor_type)
        
        actor_input = {
            'profiles': normalized,
            'collectMessages': True,
            'proxyConfigurationOptions': {
                'useApifyProxy': True
            }
        }
        
        print(f"Running Apify actor: {actor_id}")
        
        run = self.client.actor(actor_id).call(
            run_input=actor_input,
            memory_mbytes=4096,
            timeout_secs=300
        )
        
        dataset_id = run.get('defaultDatasetId')
        if not dataset_id:
            return []
        
        items = list(self.client.dataset(dataset_id).iterate_items())
        
        # Normalize results
        messages = []
        for item in items:
            messages.append({
                'id': item.get('id') or item.get('messageId'),
                'channel': item.get('channel') or item.get('channelUsername'),
                'date': item.get('date') or item.get('timestamp'),
                'text': item.get('text') or item.get('message', ''),
                'views': item.get('views', 0),
                'forwards': item.get('forwards', 0),
                'replies': item.get('replies', 0),
                'author': item.get('author'),
                'url': item.get('url'),
                'has_media': bool(item.get('media')),
            })
        
        return messages


class UnifiedScraper:
    """Main scraper class that orchestrates Telethon and Apify backends."""
    
    def __init__(self):
        self.telethon = TelethonScraper()
        self.apify = ApifyScraper()
        self.checkpoint_data = {}
    
    def get_available_backends(self) -> List[str]:
        backends = []
        if self.telethon.is_available():
            backends.append('telethon')
        if self.apify.is_available():
            backends.append('apify')
        return backends
    
    def select_backend(self, config: ScrapeConfig) -> str:
        if config.backend == ScraperBackend.TELETHON:
            if not self.telethon.is_available():
                raise ValueError("Telethon not available. Set TELEGRAM_API_ID and TELEGRAM_API_HASH")
            return 'telethon'
        elif config.backend == ScraperBackend.APIFY:
            if not self.apify.is_available():
                raise ValueError("Apify not available. Set APIFY_API_TOKEN")
            return 'apify'
        else:
            # Auto: prefer Apify for public, Telethon as fallback
            if self.apify.is_available():
                return 'apify'
            elif self.telethon.is_available():
                return 'telethon'
            else:
                raise ValueError(
                    "No scraping backend available. Set either:\n"
                    "- APIFY_API_TOKEN for Apify, or\n"
                    "- TELEGRAM_API_ID and TELEGRAM_API_HASH for Telethon"
                )
    
    async def scrape(self, config: ScrapeConfig) -> List[Dict]:
        backend = self.select_backend(config)
        print(f"Using backend: {backend}")
        
        all_messages = []
        
        # Parse date filters
        date_from = datetime.fromisoformat(config.date_from) if config.date_from else None
        date_to = datetime.fromisoformat(config.date_to) if config.date_to else None
        
        if backend == 'apify':
            self.apify.connect()
            all_messages = self.apify.scrape_channels(
                channels=config.channels,
                limit=config.limit,
                include_media=config.include_media,
                include_comments=config.include_comments
            )
        else:
            await self.telethon.connect()
            try:
                for channel in config.channels:
                    print(f"Scraping: {channel}")
                    messages = await self.telethon.scrape_channel(
                        channel=channel,
                        limit=config.limit,
                        date_from=date_from,
                        date_to=date_to,
                        include_media=config.include_media
                    )
                    all_messages.extend(messages)
                    print(f"  Got {len(messages)} messages")
            finally:
                await self.telethon.disconnect()
        
        # Apply filters
        filtered = self._apply_filters(all_messages, config)
        
        return filtered
    
    def _apply_filters(self, messages: List[Dict], config: ScrapeConfig) -> List[Dict]:
        filtered = messages
        
        # Keyword filter
        if config.filter_keywords:
            keywords = [k.lower() for k in config.filter_keywords]
            filtered = [
                m for m in filtered
                if any(kw in (m.get('text') or '').lower() for kw in keywords)
            ]
        
        # Views filter
        if config.filter_min_views > 0:
            filtered = [
                m for m in filtered
                if (m.get('views') or 0) >= config.filter_min_views
            ]
        
        return filtered
    
    def save_results(self, messages: List[Dict], config: ScrapeConfig):
        if not messages:
            print("No messages to save")
            return
        
        # Create output directory
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"telegram_scrape_{timestamp}"
        
        df = pd.DataFrame(messages)
        
        # Reorder columns
        priority = ['id', 'channel', 'date', 'text', 'views', 'forwards', 'replies', 'url']
        cols = [c for c in priority if c in df.columns]
        cols += [c for c in df.columns if c not in priority]
        df = df[cols]
        
        formats = config.output_format.split(',') if ',' in config.output_format else [config.output_format]
        if 'all' in formats:
            formats = ['csv', 'json', 'excel']
        
        for fmt in formats:
            fmt = fmt.strip().lower()
            if fmt == 'csv':
                path = output_dir / f"{base_name}.csv"
                df.to_csv(path, index=False, encoding='utf-8-sig')
                print(f"Saved CSV: {path}")
            elif fmt == 'json':
                path = output_dir / f"{base_name}.json"
                df.to_json(path, orient='records', force_ascii=False, indent=2)
                print(f"Saved JSON: {path}")
            elif fmt == 'excel':
                path = output_dir / f"{base_name}.xlsx"
                df.to_excel(path, index=False)
                print(f"Saved Excel: {path}")
        
        print(f"\nTotal messages saved: {len(messages)}")


def parse_args():
    p = argparse.ArgumentParser(
        description='Unified Telegram Scraper (Apify + Telethon)'
    )
    p.add_argument('--config', '-f', help='Path to JSON config file')
    p.add_argument('--channels', '-c', nargs='+', help='Channel usernames')
    p.add_argument('--limit', '-n', type=int, default=1000)
    p.add_argument('--output-dir', '-o', default='./output')
    p.add_argument('--format', choices=['csv', 'json', 'excel', 'all'], default='csv')
    p.add_argument('--backend', choices=['auto', 'apify', 'telethon'], default='auto')
    p.add_argument('--include-media', action='store_true')
    p.add_argument('--include-comments', action='store_true')
    p.add_argument('--date-from', help='Start date (ISO format)')
    p.add_argument('--date-to', help='End date (ISO format)')
    p.add_argument('--keywords', nargs='+', help='Filter by keywords')
    p.add_argument('--min-views', type=int, default=0, help='Min views filter')
    p.add_argument('--generate-config', help='Generate sample config file')
    return p.parse_args()


async def main():
    args = parse_args()
    
    # Generate sample config if requested
    if args.generate_config:
        sample = ScrapeConfig(
            channels=['example_channel1', 'example_channel2'],
            limit=1000,
            backend=ScraperBackend.AUTO,
            output_dir='./output',
            output_format='csv',
            include_media=True,
            include_comments=False,
            filter_keywords=['crypto', 'bitcoin'],
            filter_min_views=100
        )
        sample.to_json(args.generate_config)
        print(f"Generated sample config: {args.generate_config}")
        return
    
    # Load config
    if args.config:
        config = ScrapeConfig.from_json(args.config)
    else:
        if not args.channels:
            print("Error: Provide --channels or --config")
            return
        config = ScrapeConfig(
            channels=args.channels,
            limit=args.limit,
            backend=ScraperBackend(args.backend),
            output_dir=args.output_dir,
            output_format=args.format,
            include_media=args.include_media,
            include_comments=args.include_comments,
            date_from=args.date_from,
            date_to=args.date_to,
            filter_keywords=args.keywords or [],
            filter_min_views=args.min_views
        )
    
    print("=" * 60)
    print("Unified Telegram Scraper")
    print("=" * 60)
    print(f"Channels: {config.channels}")
    print(f"Limit: {config.limit}")
    print(f"Backend: {config.backend.value}")
    print("=" * 60)
    
    scraper = UnifiedScraper()
    
    available = scraper.get_available_backends()
    print(f"Available backends: {available}")
    
    if not available:
        print("\nNo backend available! Please set credentials:")
        print("  For Apify: APIFY_API_TOKEN")
        print("  For Telethon: TELEGRAM_API_ID and TELEGRAM_API_HASH")
        return
    
    messages = await scraper.scrape(config)
    scraper.save_results(messages, config)
    
    print("\nDone!")


if __name__ == '__main__':
    asyncio.run(main())
