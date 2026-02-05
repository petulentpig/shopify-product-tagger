"""Slack notification helpers."""

import httpx

from src.config import get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)


def send_slack_message(
    message: str,
    blocks: list[dict] | None = None,
    webhook_url: str | None = None,
) -> bool:
    """Send a message to Slack via webhook."""
    settings = get_settings()
    url = webhook_url or settings.slack_webhook_url

    if not url:
        logger.debug("No Slack webhook configured, skipping notification")
        return False

    payload: dict = {"text": message}
    if blocks:
        payload["blocks"] = blocks

    try:
        response = httpx.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Sent Slack notification")
        return True
    except Exception as e:
        logger.error("Failed to send Slack notification", error=str(e))
        return False


def send_tagging_report(
    total_processed: int,
    total_updated: int,
    errors: list[str],
    dry_run: bool = False,
) -> bool:
    """Send a tagging job summary to Slack."""
    status_emoji = "✅" if not errors else "⚠️"
    mode = "DRY RUN" if dry_run else "LIVE"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{status_emoji} Product Tagging Complete ({mode})",
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Products Processed:*\n{total_processed}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Products Updated:*\n{total_updated}",
                },
            ],
        },
    ]

    if errors:
        error_text = "\n".join(f"• {e}" for e in errors[:10])
        if len(errors) > 10:
            error_text += f"\n... and {len(errors) - 10} more"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Errors:*\n{error_text}",
            },
        })

    fallback = f"Product tagging {mode}: {total_processed} processed, {total_updated} updated"
    return send_slack_message(fallback, blocks)
