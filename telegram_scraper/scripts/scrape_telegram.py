"""Simple Telethon-based Telegram channel scraper.

Usage:
  python scrape_telegram.py --channel <channel_username_or_id> --limit 1000 --out messages.csv

You need to set TELEGRAM_API_ID and TELEGRAM_API_HASH in a .env file or environment variables.
"""
import argparse
import asyncio
import os
from telethon import TelegramClient
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION = os.getenv('TELEGRAM_SESSION', 'telegram_session')

DEFAULT_LIMIT = 1000


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--channel', '-c', required=True, help='Channel username or id')
    p.add_argument('--limit', '-n', type=int, default=DEFAULT_LIMIT)
    p.add_argument('--out', '-o', default='messages.csv')
    return p.parse_args()


async def main(channel, limit, out):
    if not API_ID or not API_HASH:
        print('Set TELEGRAM_API_ID and TELEGRAM_API_HASH in environment or .env')
        return
    client = TelegramClient(SESSION, int(API_ID), API_HASH)
    await client.start()
    msgs = []
    async for message in client.iter_messages(channel, limit=limit):
        msgs.append({
            'id': message.id,
            'date': message.date,
            'sender_id': getattr(message.sender, 'id', None),
            'text': message.message,
            'raw': repr(message)
        })
    df = pd.DataFrame(msgs)
    df.to_csv(out, index=False)
    print(f'Wrote {out} with {len(df)} messages')
    await client.disconnect()


if __name__ == '__main__':
    args = parse_args()
    asyncio.run(main(args.channel, args.limit, args.out))
