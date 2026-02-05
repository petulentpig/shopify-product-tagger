"""Claude AI-powered product tag generation."""

import json
from typing import Any

import anthropic
from ratelimit import limits, sleep_and_retry

from src.config import get_settings
from src.logging_config import get_logger
from src.shopify_client import Product

logger = get_logger(__name__)

# Default tagging prompt - customize for your business
DEFAULT_SYSTEM_PROMPT = """You are a product tagging assistant for an eyewear retail business (Gypsy Belle). 
Your job is to analyze product information and generate relevant, consistent tags.

Guidelines:
- Generate tags that help with search and filtering
- Use lowercase format (e.g., "blue light blocking", "progressive lenses")
- Include tags for: frame material, style, face shape compatibility, features, gender, brand category
- Be consistent with tag naming across products
- Don't include overly generic tags like "eyewear" or "glasses" (assumed)
- Do NOT include any of these fixed tags (they are added automatically):
  boutique bradenton, boutique ellenton, boutique lakewood ranch, bradentons best,
  gypsy belle, boutique, nashville, best boutique
- Focus on distinguishing characteristics

Common tag categories for eyewear:
- Frame material: metal frame, acetate frame, titanium frame, plastic frame, rimless, semi-rimless
- Style: aviator, cat eye, round, rectangular, oversized, vintage, modern, classic
- Features: blue light blocking, progressive ready, prescription ready, adjustable nose pads
- Gender: mens, womens, unisex
- Use case: reading, computer, everyday, sports, fashion
- Price tier: budget friendly, mid range, premium, luxury
"""


class ClaudeTagger:
    """Uses Claude AI to generate intelligent product tags."""

    def __init__(
        self,
        system_prompt: str | None = None,
        existing_tags: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_ai_tags = settings.max_ai_tags
        self.max_tags = settings.max_tags_per_product
        self.fixed_tags = [t.lower().strip() for t in settings.fixed_tags]

        # Build system prompt
        base_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        if existing_tags:
            # Filter out fixed tags from the existing tags list
            filtered = [t for t in sorted(set(existing_tags)) if t.lower() not in self.fixed_tags]
            if filtered:
                tags_list = "\n".join(f"- {tag}" for tag in filtered)
                base_prompt += f"\n\nExisting tags in the catalog (prefer using these for consistency):\n{tags_list}"

        self.system_prompt = base_prompt

    @sleep_and_retry
    @limits(calls=10, period=60)  # 10 calls per minute - adjust based on your tier
    def _call_claude(self, prompt: str) -> str:
        """Make rate-limited call to Claude API."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _get_non_fixed_tags(self, tags: list[str]) -> list[str]:
        """Return tags that are not in the fixed tags list."""
        return [t for t in tags if t.lower().strip() not in self.fixed_tags]

    def _get_missing_fixed_tags(self, current_tags: list[str]) -> list[str]:
        """Return fixed tags that are missing from the current tags."""
        current_lower = {t.lower().strip() for t in current_tags}
        return [t for t in self.fixed_tags if t not in current_lower]

    def generate_tags(self, product: Product) -> list[str]:
        """Generate tags for a single product using Claude.

        Always ensures fixed tags are present. Only calls Claude AI
        if the product has fewer than max_ai_tags non-fixed tags.
        """
        current_tags = product.tags
        non_fixed = self._get_non_fixed_tags(current_tags)
        missing_fixed = self._get_missing_fixed_tags(current_tags)

        # Start with existing tags + any missing fixed tags
        final_tags = list(current_tags) + missing_fixed

        # Only call Claude if product needs more AI tags
        if len(non_fixed) < self.max_ai_tags:
            try:
                product_info = self._format_product_info(product)

                prompt = f"""Analyze this product and suggest appropriate tags.

{product_info}

Current non-fixed tags: {', '.join(non_fixed) if non_fixed else 'None'}

Return ONLY a JSON array of tag strings, no explanation. Example: ["tag-one", "tag-two", "tag-three"]
Suggest up to {self.max_ai_tags - len(non_fixed)} new tags (product already has {len(non_fixed)} non-fixed tags).
Do NOT include any fixed/location tags."""

                response = self._call_claude(prompt)
                ai_tags = self._parse_tags_response(response)

                # Filter out any fixed tags Claude might have included
                ai_tags = [t for t in ai_tags if t.lower() not in self.fixed_tags]

                # Filter out duplicates of existing tags
                existing_lower = {t.lower() for t in final_tags}
                new_ai_tags = [t for t in ai_tags if t.lower() not in existing_lower]

                # Limit AI tags
                slots_available = self.max_ai_tags - len(non_fixed)
                new_ai_tags = new_ai_tags[:slots_available]

                final_tags.extend(new_ai_tags)

                logger.info(
                    "Generated tags",
                    product_id=product.id,
                    product_title=product.title,
                    ai_tags=new_ai_tags,
                    fixed_tags_added=missing_fixed,
                )

            except Exception as e:
                logger.error(
                    "Failed to generate AI tags, keeping fixed tags",
                    product_id=product.id,
                    error=str(e),
                )
        else:
            logger.info(
                "Skipping AI tagging (has 5+ non-fixed tags), ensuring fixed tags",
                product_id=product.id,
                product_title=product.title,
                non_fixed_count=len(non_fixed),
                fixed_tags_added=missing_fixed,
            )

        # Enforce Shopify's 13-tag limit
        return final_tags[:self.max_tags]

    def _format_product_info(self, product: Product) -> str:
        """Format product information for Claude."""
        lines = [
            f"Title: {product.title}",
            f"Vendor: {product.vendor or 'N/A'}",
            f"Product Type: {product.product_type or 'N/A'}",
        ]

        if product.body_html:
            # Strip HTML for cleaner text (basic strip)
            import re

            clean_desc = re.sub(r"<[^>]+>", " ", product.body_html)
            clean_desc = " ".join(clean_desc.split())[:500]  # Limit length
            lines.append(f"Description: {clean_desc}")

        if product.variants:
            variant_info = []
            for v in product.variants[:5]:  # Limit to first 5 variants
                variant_info.append(
                    f"  - {v.get('title', 'Default')}: ${v.get('price', 'N/A')}"
                )
            lines.append("Variants:\n" + "\n".join(variant_info))

        return "\n".join(lines)

    def _parse_tags_response(self, response: str) -> list[str]:
        """Parse Claude's response into a list of tags."""
        # Try to extract JSON array from response
        response = response.strip()

        # Handle if Claude wrapped in markdown code block
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        try:
            tags = json.loads(response)
            if isinstance(tags, list):
                # Normalize tags
                normalized = []
                for tag in tags:
                    if isinstance(tag, str):
                        tag = tag.lower().strip()
                        if tag and tag not in normalized:
                            normalized.append(tag)
                return normalized
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract comma-separated tags
        logger.warning("Failed to parse JSON, attempting fallback parsing")
        tags = [t.strip().lower() for t in response.split(",")]
        return [t for t in tags if t]

    def generate_tags_batch(
        self, products: list[Product]
    ) -> dict[int, list[str]]:
        """Generate tags for multiple products."""
        results: dict[int, list[str]] = {}

        for i, product in enumerate(products, 1):
            logger.info(
                "Processing product",
                progress=f"{i}/{len(products)}",
                product_id=product.id,
                title=product.title,
            )
            results[product.id] = self.generate_tags(product)

        return results


def get_all_existing_tags(products: list[Product]) -> list[str]:
    """Extract all unique tags from a list of products."""
    all_tags: set[str] = set()
    for product in products:
        all_tags.update(tag.lower() for tag in product.tags)
    return sorted(all_tags)
