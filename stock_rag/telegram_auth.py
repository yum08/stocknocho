"""One-time Telegram authentication for StockRAG.

Run this script once to authenticate your Telegram account.
After that, the webapp can scrape channels without any prompts.

Usage:
    python -m stock_rag.telegram_auth

You need TELEGRAM_API_ID and TELEGRAM_API_HASH in your .env file.
Get them free at: https://my.telegram.org/auth
"""

import os
import sys
import asyncio

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# Session stored in project root
SESSION_DIR = os.path.join(os.path.dirname(__file__), '..', '.telegram_sessions')
SESSION_NAME = 'stockrag_session'


def get_session_path():
    os.makedirs(SESSION_DIR, exist_ok=True)
    return os.path.join(SESSION_DIR, SESSION_NAME)


async def main():
    print()
    print("=" * 55)
    print("  StockRAG — Telegram Authentication (one-time setup)")
    print("=" * 55)
    print()

    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH not found in .env")
        print()
        print("Steps to get them (FREE):")
        print("  1. Go to https://my.telegram.org/auth")
        print("  2. Log in with your phone number")
        print("  3. Click 'API development tools'")
        print("  4. Create an app (any name/description)")
        print("  5. Copy api_id and api_hash")
        print("  6. Add to your .env file:")
        print("     TELEGRAM_API_ID=12345678")
        print("     TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890")
        print()
        sys.exit(1)

    session_path = get_session_path()
    client = TelegramClient(session_path, int(API_ID), API_HASH)

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Already authenticated as: {me.first_name} "
                  f"(@{me.username or 'no username'})")
            print(f"Phone: +{me.phone}")
            print(f"Session file: {session_path}.session")
            print()
            print("You're all set! The webapp can now scrape Telegram channels.")
            return

        print("Choose authentication method:")
        print("  [1] Phone number (SMS/call code)")
        print("  [2] QR Code (scan with Telegram mobile app)")
        print()

        choice = input("Enter 1 or 2: ").strip()

        if choice == '2':
            # QR Code auth
            print()
            print("QR Code authentication is interactive.")
            print("Opening Telethon QR auth flow...")
            print()

            # For QR, we use start() which handles it
            await client.start()
        else:
            # Phone auth
            phone = input("Enter your phone number (with country code, e.g. +91...): ").strip()
            await client.send_code_request(phone)
            print()
            print("A code has been sent to your Telegram app (or via SMS).")
            code = input("Enter the code: ").strip()

            try:
                await client.sign_in(phone, code)
            except Exception as e:
                if 'Two-step verification' in str(e) or 'password' in str(e).lower():
                    password = input("Enter your 2FA password: ").strip()
                    await client.sign_in(password=password)
                else:
                    raise

        me = await client.get_me()
        print()
        print(f"Successfully authenticated as: {me.first_name} "
              f"(@{me.username or 'no username'})")
        print(f"Session saved to: {session_path}.session")
        print()
        print("You're all set! The webapp can now scrape Telegram channels for FREE.")
        print("No Apify charges — unlimited messages!")

    except Exception as e:
        print(f"\nAuthentication failed: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
