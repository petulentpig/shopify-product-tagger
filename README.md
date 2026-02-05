# Shopify Product Tagger

AI-powered product tagging for Shopify stores using Claude. Automatically analyzes product titles, descriptions, and attributes to generate relevant, consistent tags.

## Features

- **AI-Powered Tagging**: Uses Claude to analyze products and suggest appropriate tags
- **GraphQL API**: Uses Shopify GraphQL Admin API by default for faster bulk operations
- **Consistency**: Learns from existing tags in your catalog to maintain naming consistency
- **Rate Limiting**: Built-in rate limiting for both Shopify and Anthropic APIs
- **Dry Run Mode**: Preview changes before applying them
- **Slack Notifications**: Get notified when tagging jobs complete
- **CLI Interface**: Easy-to-use command line interface

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/shopify-product-tagger.git
cd shopify-product-tagger

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

Create a `.env` file with your credentials:

```env
# Required
SHOPIFY_SHOP_URL=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx

# Optional
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/xxx/xxx
```

### Shopify Access Token

1. Go to your Shopify Admin → Settings → Apps and sales channels
2. Click "Develop apps" → "Create an app"
3. Configure Admin API scopes: `read_products`, `write_products`
4. Install the app and copy the Admin API access token

## Usage

By default, all commands use the **GraphQL Admin API** which is faster for bulk operations. Add `--rest` to any command to use the REST API instead.

### Tag All Products

```bash
# Preview changes (dry run)
python -m src.main tag-all --dry-run

# Apply tags to all products
python -m src.main tag-all

# Only tag products that have no tags
python -m src.main tag-all --only-untagged

# Limit to first N products
python -m src.main tag-all --limit 10

# Use REST API instead of GraphQL
python -m src.main tag-all --rest
```

### Tag a Single Product

```bash
# Preview tags for a specific product
python -m src.main tag-product 123456789 --dry-run

# Apply tags (with confirmation prompt)
python -m src.main tag-product 123456789
```

### List Existing Tags

```bash
python -m src.main list-tags
```

### Find Untagged Products

```bash
python -m src.main find-untagged
```

### Preview Tag Suggestions

```bash
# Preview suggestions for 5 random products
python -m src.main preview --count 5
```

## Customizing Tag Generation

Edit the `DEFAULT_SYSTEM_PROMPT` in `src/tagger.py` to customize how Claude generates tags for your specific business:

```python
DEFAULT_SYSTEM_PROMPT = """You are a product tagging assistant for [YOUR BUSINESS TYPE].
Your job is to analyze product information and generate relevant, consistent tags.

Guidelines:
- [Your specific guidelines]
- [Tag categories relevant to your products]
...
"""
```

## Deployment

### Railway

1. Push to GitHub
2. Connect Railway to your repository
3. Add environment variables in Railway dashboard
4. Deploy

The app will run as a one-off job. Set up a Railway cron trigger to run on a schedule.

### Docker

```bash
# Build
docker build -t shopify-tagger .

# Run
docker run --env-file .env shopify-tagger tag-all --dry-run
```

### Scheduled Runs

For scheduled tagging (e.g., tag new products nightly):

**Railway Cron:**
```bash
railway run --cron "0 2 * * *" python -m src.main tag-all --only-untagged
```

**System Cron:**
```cron
0 2 * * * cd /path/to/shopify-product-tagger && /path/to/venv/bin/python -m src.main tag-all --only-untagged
```

## Project Structure

```
shopify-product-tagger/
├── src/
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── logging_config.py  # Structured logging setup
│   ├── main.py            # CLI application
│   ├── shopify_client.py  # Shopify API client
│   ├── slack.py           # Slack notifications
│   └── tagger.py          # Claude AI tagger
├── tests/
│   └── test_tagger.py
├── .env.example
├── .gitignore
├── Dockerfile
├── railway.json
├── README.md
└── requirements.txt
```

## Development

```bash
# Run tests
pytest

# Run with verbose logging
LOG_LEVEL=DEBUG python -m src.main preview
```

## License

MIT
