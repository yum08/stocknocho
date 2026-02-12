# Social Media Scraper

Multi-backend scraper for **Telegram**, **X.com (Twitter)**, and **LinkedIn** using **Apify cloud** and **Telethon**.

## Scrapers

| Script | Platform | Backend | Use Case |
|--------|----------|---------|----------|
| `apify_telegram_scraper.py` | Telegram | Apify REST API | **Recommended** — Cloud-based, no personal credentials |
| `apify_x_scraper.py` | X.com (Twitter) | Apify REST API | Scrape tweets by handle, search, or URL |
| `apify_linkedin_scraper.py` | LinkedIn | Apify REST API | Scrape profile posts, reactions, media (no cookies) |
| `unified_scraper.py` | Telegram | Auto (Apify / Telethon) | Hybrid — auto-selects best backend |
| `scrape_telegram.py` | Telegram | Telethon | Private channels, personal account required |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up credentials

Create a `.env` file in the project root:

```env
# For Apify (recommended for public channels)
APIFY_API_TOKEN=your_apify_token_here

# For Telethon (required for private channels)
# TELEGRAM_API_ID=your_api_id
# TELEGRAM_API_HASH=your_api_hash
```

Get credentials:
- **Apify**: https://console.apify.com/account/integrations
- **Telegram**: https://my.telegram.org

### 3. Run the scraper

**Apify Scraper (recommended):**

```bash
# Last 10 posts from a channel
python scripts/apify_telegram_scraper.py --channels DGPIndia --max-posts 10

# Multiple channels, last 7 days, all output formats
python scripts/apify_telegram_scraper.py --channels durov telegram --days 7 \
  --out messages.csv --out-json messages.json --out-excel messages.xlsx

# 200 posts with media download
python scripts/apify_telegram_scraper.py --channels channel_name --max-posts 200 --download-media

# Use the post-range actor for large scrapes
python scripts/apify_telegram_scraper.py --channels channel_name --actor posts --posts-from 1 --posts-to 500
```

**X.com (Twitter) Scraper:**

```bash
# Last 3 tweets from default handles (edit DEFAULT_HANDLES in script to customize)
python scripts/apify_x_scraper.py

# Specific handles, 5 tweets each
python scripts/apify_x_scraper.py --handles stockstix elonmusk --max-tweets 5

# With all output formats
python scripts/apify_x_scraper.py --handles adi408b rahul_saggi --max-tweets 3 \
  --out tweets.csv --out-json tweets.json --out-excel tweets.xlsx

# Search tweets
python scripts/apify_x_scraper.py --search "web scraping" --max-tweets 10
```

**Default X.com handles** (edit `DEFAULT_HANDLES` in `apify_x_scraper.py` to add more):
- @stockstix, @Derzuschauer7, @adi408b, @rahul_saggi, @Suchitpatel, @vivekthebaria

**LinkedIn Profile Posts Scraper:**

```bash
# Last 10 posts from a profile (default profile in script)
python scripts/apify_linkedin_scraper.py

# Specific profile, 5 posts
python scripts/apify_linkedin_scraper.py --profiles kavishka-abeywardana-01b891214 --max-posts 5

# Using full LinkedIn URL
python scripts/apify_linkedin_scraper.py --profiles "https://www.linkedin.com/in/satyanadella" --max-posts 3

# Multiple profiles, all output formats
python scripts/apify_linkedin_scraper.py --profiles satyanadella billgates --max-posts 10 \
  --out linkedin.csv --out-json linkedin.json --out-excel linkedin.xlsx
```

**Default LinkedIn profile** (edit `DEFAULT_PROFILES` in `apify_linkedin_scraper.py` to add more):
- kavishka-abeywardana-01b891214

**Unified Scraper:**

```bash
# Auto-select backend
python scripts/unified_scraper.py --channels channel1 channel2 --limit 500

# Force Telethon for private channels
python scripts/unified_scraper.py --channels private_channel --backend telethon

# With keyword and view filters
python scripts/unified_scraper.py --channels channel --keywords bitcoin crypto --min-views 1000

# Generate config file
python scripts/unified_scraper.py --generate-config config.json
```

**Original Telethon Scraper:**

```bash
python scripts/scrape_telegram.py --channel channel_name --limit 1000 --out messages.csv
```

## Apify Actor Backends

### Telegram Actors

| Actor | Flag | Best For |
|-------|------|----------|
| `webfinity/telegram-channel-content-media-scraper-v2` | `--actor media` (default) | Quick scrapes, up to 200 posts, media support |
| `danielmilevski9/telegram-channel-scraper` | `--actor posts` | Large scrapes with post range selection |
| `cheapget/telegram-channel-message` | `--actor messages` | Date-filtered message extraction |

### X.com (Twitter) Actors

| Actor | Flag | Best For |
|-------|------|----------|
| `danek/twitter-scraper-ppr` | `--actor ppr` (default) | Reliable per-handle scraping |
| `kaitoeasyapi/tweet-scraper` | `--actor search` | Search-based, pay-per-result |
| `apidojo/tweet-scraper` | `--actor full` | Full-featured V2 (may need paid plan) |

### LinkedIn Actors

| Actor | Flag | Best For |
|-------|------|----------|
| `apimaestro/linkedin-profile-posts` | `--actor profile_posts` (default) | Profile posts with media, no cookies needed |

## Feature Comparison

| Feature | Apify Scraper | Unified | Telethon |
|---------|--------------|---------|----------|
| Public channels | ✅ | ✅ | ✅ |
| Private channels | ❌ | ✅ | ✅ |
| No personal account needed | ✅ | ✅ (via Apify) | ❌ |
| Proxy rotation | ✅ (residential) | ✅ | ❌ |
| Cloud execution | ✅ | ✅ | ❌ |
| Multiple channels | ✅ | ✅ | ❌ |
| Date filtering | ✅ | ✅ | ✅ |
| Keyword filtering | ❌ | ✅ | ❌ |
| Media download | ✅ | ❌ | ✅ |
| CSV / JSON / Excel export | ✅ | ✅ | CSV only |

## Output Format

| Column | Description |
|--------|-------------|
| `id` | Post/message ID |
| `channel` | Channel username |
| `date` | Post timestamp (ISO 8601) |
| `text` | Message text content |
| `views` | View count |
| `forwards` | Forward count |
| `replies` | Reply/comment count |
| `url` | Direct link to the post |
| `has_media` | Whether post contains media |
| `media_urls` | Media file URLs (if available) |

## Notes

- Respect Telegram's terms of service and channel owners' privacy
- Apify has usage-based pricing — check your plan at https://console.apify.com
- For private channels, you must be a member and use Telethon
- Rate limiting and retries are handled automatically
- The `truststore` package is used to fix SSL issues on corporate networks
