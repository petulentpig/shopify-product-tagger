"""Tests for the tagger module."""

import pytest

from src.shopify_client import Product
from src.tagger import get_all_existing_tags


@pytest.fixture
def sample_product() -> Product:
    """Create a sample product for testing."""
    return Product(
        id=123456789,
        title="Classic Aviator Sunglasses",
        body_html="<p>Timeless aviator style with UV protection.</p>",
        vendor="Ray-Ban",
        product_type="Sunglasses",
        tags=["aviator", "uv-protection"],
        variants=[{"id": 1, "title": "Gold/Green", "price": "159.00"}],
        images=[],
        handle="classic-aviator-sunglasses",
        status="active",
    )


@pytest.fixture
def sample_products() -> list[Product]:
    """Create sample products for testing."""
    return [
        Product(
            id=1,
            title="Product 1",
            body_html=None,
            vendor="Vendor A",
            product_type="Type A",
            tags=["tag-a", "tag-b"],
            variants=[],
            images=[],
            handle="product-1",
            status="active",
        ),
        Product(
            id=2,
            title="Product 2",
            body_html=None,
            vendor="Vendor B",
            product_type="Type B",
            tags=["tag-b", "tag-c", "Tag-A"],  # Note: Tag-A with different case
            variants=[],
            images=[],
            handle="product-2",
            status="active",
        ),
    ]


class TestGetAllExistingTags:
    """Tests for get_all_existing_tags function."""

    def test_extracts_unique_tags(self, sample_products: list[Product]) -> None:
        """Should extract all unique tags across products."""
        tags = get_all_existing_tags(sample_products)

        assert "tag-a" in tags
        assert "tag-b" in tags
        assert "tag-c" in tags

    def test_normalizes_to_lowercase(self, sample_products: list[Product]) -> None:
        """Should normalize tags to lowercase."""
        tags = get_all_existing_tags(sample_products)

        # Both "tag-a" and "Tag-A" should result in single "tag-a"
        assert tags.count("tag-a") == 1
        assert "Tag-A" not in tags

    def test_returns_sorted_list(self, sample_products: list[Product]) -> None:
        """Should return tags in sorted order."""
        tags = get_all_existing_tags(sample_products)

        assert tags == sorted(tags)

    def test_empty_products_list(self) -> None:
        """Should handle empty products list."""
        tags = get_all_existing_tags([])
        assert tags == []


class TestProductFromApi:
    """Tests for Product.from_api class method."""

    def test_parses_tags_string(self) -> None:
        """Should parse comma-separated tags string into list."""
        data = {
            "id": 1,
            "title": "Test Product",
            "tags": "tag-one, tag-two, tag-three",
            "handle": "test-product",
        }

        product = Product.from_api(data)

        assert product.tags == ["tag-one", "tag-two", "tag-three"]

    def test_handles_empty_tags(self) -> None:
        """Should handle empty tags string."""
        data = {
            "id": 1,
            "title": "Test Product",
            "tags": "",
            "handle": "test-product",
        }

        product = Product.from_api(data)

        assert product.tags == []

    def test_handles_missing_tags(self) -> None:
        """Should handle missing tags field."""
        data = {
            "id": 1,
            "title": "Test Product",
            "handle": "test-product",
        }

        product = Product.from_api(data)

        assert product.tags == []
