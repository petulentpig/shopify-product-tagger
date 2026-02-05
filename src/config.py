"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Shopify
    shopify_shop_url: str  # e.g., "your-store.myshopify.com"
    shopify_access_token: str
    shopify_api_version: str = "2024-10"

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-20250514"

    # Tagging behavior
    max_tags_per_product: int = 13  # Shopify limit is 13 tags
    dry_run: bool = False  # If True, don't actually update products
    batch_size: int = 50  # Products to process per batch

    # Rate limiting
    shopify_rate_limit: int = 2  # calls per second (Shopify allows 2/sec for Plus, 4/sec otherwise but be conservative)
    claude_rate_limit: int = 10  # calls per minute (adjust based on your tier)

    # Logging
    log_level: str = "INFO"
    log_json: bool = False  # Set True for production/Railway

    # Slack notifications (optional)
    slack_webhook_url: str | None = None
    slack_channel: str = "#shopify-automation"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
