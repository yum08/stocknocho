"""Free Telegram channel scraper using Telethon (Telegram API).

No Apify charges — uses Telegram's own API directly.
Requires:
  - TELEGRAM_API_ID and TELEGRAM_API_HASH in .env
  - One-time phone authentication (run telegram_auth.py first)
"""

import asyncio
import os
import logging
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional

from telethon import TelegramClient
from telethon.tl.types import (
    Channel, MessageMediaPhoto,
    MessageMediaWebPage, ReactionEmoji, ReactionCustomEmoji,
)
from telethon.errors import (
    ChannelPrivateError, UsernameNotOccupiedError,
    UsernameInvalidError, FloodWaitError,
)

logger = logging.getLogger(__name__)

# ── Tesseract OCR path (auto-detect on Windows) ──
TESSERACT_CMD = None
for _candidate in [
    os.path.expandvars(r'%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe'),
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    'tesseract',  # on PATH
]:
    if os.path.isfile(_candidate):
        TESSERACT_CMD = _candidate
        break


def _ocr_image(file_path: str) -> str:
    """Run Tesseract OCR on an image file. Returns extracted text or ''."""
    try:
        import pytesseract
        from PIL import Image
        if TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img).strip()
        return text
    except Exception as e:
        logger.debug(f"OCR failed for {file_path}: {e}")
        return ''


# Session file stored alongside the DB
SESSION_DIR = os.path.join(os.path.dirname(__file__), '..', '.telegram_sessions')
SESSION_NAME = 'stockrag_session'


def _get_session_path() -> str:
    """Return full path for the Telethon session file."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    return os.path.join(SESSION_DIR, SESSION_NAME)


def is_authenticated() -> bool:
    """Check if a Telegram session exists (user has authenticated)."""
    session_path = _get_session_path() + '.session'
    return os.path.isfile(session_path)


def _extract_reactions(message) -> dict:
    """Extract reaction counts from a Telethon message."""
    reactions_dict = {}
    if not message.reactions or not message.reactions.results:
        return reactions_dict
    for r in message.reactions.results:
        if isinstance(r.reaction, ReactionEmoji):
            emoji = r.reaction.emoticon
        elif isinstance(r.reaction, ReactionCustomEmoji):
            emoji = f'custom_{r.reaction.document_id}'
        else:
            emoji = str(r.reaction)
        reactions_dict[emoji] = r.count
    return reactions_dict


def _message_to_dict(msg, channel_username: str, channel_title: str,
                     ocr_text: str = '') -> Dict[str, Any]:
    """Convert a Telethon Message object to a dict matching our normalizer format."""
    # Text
    text = msg.message or ''

    # Append OCR text if image had readable content
    if ocr_text:
        if text:
            text = text + '\n\n[OCR from image]\n' + ocr_text
        else:
            text = '[OCR from image]\n' + ocr_text

    # Media detection
    has_media = False
    media_urls = []
    if msg.media:
        has_media = True
        if isinstance(msg.media, MessageMediaWebPage):
            if msg.media.webpage and hasattr(msg.media.webpage, 'url'):
                media_urls.append(msg.media.webpage.url)

    # Reactions
    reactions = _extract_reactions(msg)
    total_reactions = sum(reactions.values()) if reactions else 0

    # Build URL
    url = f'https://t.me/{channel_username}/{msg.id}' if channel_username else ''

    return {
        'id': msg.id,
        'text': text,
        'message': text,
        'date': msg.date.isoformat() if msg.date else None,
        'channel': channel_title,
        'channelName': channel_title,
        'channelUrl': f'https://t.me/{channel_username}' if channel_username else '',
        'url': url,
        'messageUrl': url,
        'views': msg.views or 0,
        'viewCount': msg.views or 0,
        'forwards': msg.forwards or 0,
        'shares': msg.forwards or 0,
        'reactions': total_reactions,
        'reactions_detail': reactions,
        'reactionsList': reactions,
        'likes': total_reactions,
        'comments': msg.replies.replies if msg.replies else 0,
        'repliesCount': msg.replies.replies if msg.replies else 0,
        'sender': channel_title,
        'hasMedia': has_media,
        'mediaUrls': media_urls,
        'post_author': msg.post_author or '',
    }


async def _scrape_channel_async(
    api_id: int,
    api_hash: str,
    channel_username: str,
    max_messages: int = 1000,
    offset_date: Optional[datetime] = None,
    progress_callback=None,
    enable_ocr: bool = False,
) -> List[Dict[str, Any]]:
    """Async: scrape messages from a Telegram channel using Telethon.

    Args:
        offset_date: If provided, only messages **after** this date are
            returned.  Internally we fetch from newest-first (no Telethon
            offset_date) and stop once we pass this cutoff, so recent
            messages are always included.
    """

    session_path = _get_session_path()
    client = TelegramClient(session_path, api_id, api_hash)

    messages = []
    try:
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session not authenticated. "
                "Run 'python -m stock_rag.telegram_auth' first to log in."
            )

        # Resolve channel
        try:
            entity = await client.get_entity(channel_username)
        except UsernameNotOccupiedError:
            raise ValueError(f"Channel @{channel_username} does not exist")
        except UsernameInvalidError:
            raise ValueError(f"Invalid channel username: @{channel_username}")
        except ChannelPrivateError:
            raise ValueError(
                f"Channel @{channel_username} is private. "
                "You must be a member to scrape it."
            )

        # Resolve human-readable title; fall back to username if title is
        # missing or purely numeric (e.g. a raw channel ID).
        raw_title = getattr(entity, 'title', None) or ''
        if raw_title and not raw_title.replace(' ', '').isdigit():
            channel_title = raw_title
        else:
            channel_title = channel_username.lstrip('@')
        entity_username = getattr(entity, 'username', channel_username) or channel_username

        logger.info(
            f"Scraping @{entity_username} ({channel_title}), "
            f"max_messages={max_messages}"
        )

        # Scrape messages — always start from the newest.
        # If offset_date is set we use it as a min-date cutoff: stop once
        # we reach messages older than offset_date.
        count = 0
        async for msg in client.iter_messages(
            entity,
            limit=max_messages,
            reverse=False,  # newest first
        ):
            # Stop early when we've gone past the date range
            if offset_date and msg.date:
                msg_dt = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                cutoff = offset_date.replace(tzinfo=None) if offset_date.tzinfo else offset_date
                if msg_dt < cutoff:
                    break

            if msg.message is None and not msg.media:
                continue  # skip service messages (joins, pins, etc.)

            # OCR: download photo and extract text
            ocr_text = ''
            if enable_ocr and isinstance(getattr(msg, 'media', None), MessageMediaPhoto):
                try:
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                        tmp_path = tmp.name
                    await client.download_media(msg, file=tmp_path)
                    ocr_text = _ocr_image(tmp_path)
                    if ocr_text:
                        logger.debug(f"OCR msg {msg.id}: {ocr_text[:80]}...")
                except Exception as e:
                    logger.debug(f"OCR download failed msg {msg.id}: {e}")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            messages.append(
                _message_to_dict(msg, entity_username, channel_title, ocr_text=ocr_text)
            )
            count += 1

            if progress_callback and count % 500 == 0:
                progress_callback(count, max_messages)

        logger.info(f"Scraped {len(messages)} messages from @{entity_username}")

    except FloodWaitError as e:
        logger.warning(f"Telegram flood wait: {e.seconds}s. Try again later.")
        raise RuntimeError(
            f"Telegram rate limit hit. Wait {e.seconds} seconds and retry."
        )
    finally:
        await client.disconnect()

    return messages


def scrape_channel(
    api_id: int,
    api_hash: str,
    channel_username: str,
    max_messages: int = 1000,
    offset_date: Optional[datetime] = None,
    progress_callback=None,
    enable_ocr: bool = False,
) -> List[Dict[str, Any]]:
    """Synchronous wrapper: scrape messages from a Telegram channel.

    Args:
        enable_ocr: If True, download photos and run Tesseract OCR to
            extract text from images (e.g. harmonic pattern charts).
    Returns list of dicts compatible with normalize_telegram_post().
    """
    # Use a new event loop (safe for Flask threads)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _scrape_channel_async(
                api_id, api_hash, channel_username,
                max_messages, offset_date, progress_callback,
                enable_ocr=enable_ocr,
            )
        )
    finally:
        loop.close()


async def get_channel_info_async(
    api_id: int, api_hash: str, channel_username: str
) -> Dict[str, Any]:
    """Get basic info about a channel (name, members, message count)."""
    session_path = _get_session_path()
    client = TelegramClient(session_path, api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Not authenticated. Run telegram_auth first.")

        entity = await client.get_entity(channel_username)

        return {
            'id': entity.id,
            'title': getattr(entity, 'title', ''),
            'username': getattr(entity, 'username', ''),
            'members': getattr(entity, 'participants_count', None),
            'is_channel': isinstance(entity, Channel),
        }
    finally:
        await client.disconnect()


def get_channel_info(
    api_id: int, api_hash: str, channel_username: str
) -> Dict[str, Any]:
    """Sync wrapper for get_channel_info_async."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            get_channel_info_async(api_id, api_hash, channel_username)
        )
    finally:
        loop.close()
