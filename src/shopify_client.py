"""Shopify API client with rate limiting and error handling."""

import time
from dataclasses import dataclass
from typing import Any

import httpx
from ratelimit import limits, sleep_and_retry

from src.config import get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# GraphQL Queries
PRODUCTS_QUERY = """
query GetProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        title
        handle
        descriptionHtml
        vendor
        productType
        status
        tags
        variants(first: 10) {
          edges {
            node {
              id
              title
              price
              sku
            }
          }
        }
        images(first: 5) {
          edges {
            node {
              id
              url
              altText
            }
          }
        }
      }
    }
  }
}
"""

PRODUCT_BY_ID_QUERY = """
query GetProduct($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    descriptionHtml
    vendor
    productType
    status
    tags
    variants(first: 10) {
      edges {
        node {
          id
          title
          price
          sku
        }
      }
    }
    images(first: 5) {
      edges {
        node {
          id
          url
          altText
        }
      }
    }
  }
}
"""

UPDATE_PRODUCT_TAGS_MUTATION = """
mutation UpdateProductTags($input: ProductInput!) {
  productUpdate(input: $input) {
    product {
      id
      title
      tags
    }
    userErrors {
      field
      message
    }
  }
}
"""


@dataclass
class Product:
    """Represents a Shopify product."""

    id: int
    gid: str  # GraphQL global ID
    title: str
    body_html: str | None
    vendor: str | None
    product_type: str | None
    tags: list[str]
    variants: list[dict[str, Any]]
    images: list[dict[str, Any]]
    handle: str
    status: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Product":
        """Create Product from Shopify REST API response."""
        tags_str = data.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

        return cls(
            id=data["id"],
            gid=f"gid://shopify/Product/{data['id']}",
            title=data["title"],
            body_html=data.get("body_html"),
            vendor=data.get("vendor"),
            product_type=data.get("product_type"),
            tags=tags,
            variants=data.get("variants", []),
            images=data.get("images", []),
            handle=data["handle"],
            status=data.get("status", "active"),
        )

    @classmethod
    def from_graphql(cls, node: dict[str, Any]) -> "Product":
        """Create Product from Shopify GraphQL response."""
        # Extract numeric ID from gid://shopify/Product/123456
        gid = node["id"]
        numeric_id = int(gid.split("/")[-1])

        # Tags come as a list in GraphQL
        tags = node.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Flatten variants from edges
        variants = []
        for edge in node.get("variants", {}).get("edges", []):
            v = edge["node"]
            variants.append({
                "id": v["id"],
                "title": v.get("title"),
                "price": v.get("price"),
                "sku": v.get("sku"),
            })

        # Flatten images from edges
        images = []
        for edge in node.get("images", {}).get("edges", []):
            img = edge["node"]
            images.append({
                "id": img["id"],
                "src": img.get("url"),
                "alt": img.get("altText"),
            })

        return cls(
            id=numeric_id,
            gid=gid,
            title=node["title"],
            body_html=node.get("descriptionHtml"),
            vendor=node.get("vendor"),
            product_type=node.get("productType"),
            tags=tags,
            variants=variants,
            images=images,
            handle=node["handle"],
            status=node.get("status", "ACTIVE").lower(),
        )


class ShopifyClient:
    """HTTP client for Shopify Admin API with rate limiting."""

    def __init__(self) -> None:
        settings = get_settings()
        self.shop_url = settings.shopify_shop_url.rstrip("/")
        self.api_version = settings.shopify_api_version
        self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"
        self._rate_limit = settings.shopify_rate_limit

        self.client = httpx.Client(
            headers={
                "X-Shopify-Access-Token": settings.shopify_access_token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _handle_rate_limit(self, response: httpx.Response) -> None:
        """Check and handle Shopify rate limit headers."""
        # Shopify returns X-Shopify-Shop-Api-Call-Limit: "32/40"
        call_limit = response.headers.get("X-Shopify-Shop-Api-Call-Limit")
        if call_limit:
            current, maximum = map(int, call_limit.split("/"))
            if current >= maximum - 2:
                logger.warning(
                    "Approaching rate limit, sleeping",
                    current=current,
                    maximum=maximum,
                )
                time.sleep(1)

    @sleep_and_retry
    @limits(calls=2, period=1)  # 2 calls per second
    def _request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> httpx.Response:
        """Make rate-limited request to Shopify API."""
        url = f"{self.base_url}{endpoint}"
        response = self.client.request(method, url, **kwargs)

        self._handle_rate_limit(response)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 2))
            logger.warning("Rate limited by Shopify", retry_after=retry_after)
            time.sleep(retry_after)
            return self._request(method, endpoint, **kwargs)

        response.raise_for_status()
        return response

    def get_products(
        self,
        limit: int = 50,
        since_id: int | None = None,
        status: str = "active",
        fields: str | None = None,
    ) -> list[Product]:
        """Fetch products with pagination support."""
        params: dict[str, Any] = {"limit": limit, "status": status}

        if since_id:
            params["since_id"] = since_id
        if fields:
            params["fields"] = fields

        response = self._request("GET", "/products.json", params=params)
        data = response.json()

        products = [Product.from_api(p) for p in data.get("products", [])]
        logger.info("Fetched products", count=len(products), since_id=since_id)
        return products

    def get_all_products(self, status: str = "active") -> list[Product]:
        """Fetch all products using pagination."""
        all_products: list[Product] = []
        since_id: int | None = None

        while True:
            batch = self.get_products(limit=250, since_id=since_id, status=status)
            if not batch:
                break

            all_products.extend(batch)
            since_id = batch[-1].id
            logger.info("Pagination progress", total=len(all_products))

        logger.info("Fetched all products", total=len(all_products))
        return all_products

    def get_product(self, product_id: int) -> Product:
        """Fetch a single product by ID."""
        response = self._request("GET", f"/products/{product_id}.json")
        data = response.json()
        return Product.from_api(data["product"])

    def update_product_tags(self, product_id: int, tags: list[str]) -> Product:
        """Update tags for a product."""
        tags_str = ", ".join(tags)
        payload = {"product": {"id": product_id, "tags": tags_str}}

        response = self._request("PUT", f"/products/{product_id}.json", json=payload)
        data = response.json()

        logger.info(
            "Updated product tags",
            product_id=product_id,
            tags=tags,
        )
        return Product.from_api(data["product"])

    def get_products_by_tag(self, tag: str, limit: int = 250) -> list[Product]:
        """Fetch products that have a specific tag."""
        # Note: Shopify doesn't support tag filtering directly in REST API
        # This fetches all and filters client-side
        # For large catalogs, consider using GraphQL instead
        all_products = self.get_all_products()
        return [p for p in all_products if tag.lower() in [t.lower() for t in p.tags]]

    def get_products_without_tags(self) -> list[Product]:
        """Fetch products that have no tags."""
        all_products = self.get_all_products()
        return [p for p in all_products if not p.tags]

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> "ShopifyClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class ShopifyGraphQLClient:
    """GraphQL client for Shopify Admin API - faster for bulk operations."""

    def __init__(self) -> None:
        settings = get_settings()
        self.shop_url = settings.shopify_shop_url.rstrip("/")
        self.api_version = settings.shopify_api_version
        self.graphql_url = f"https://{self.shop_url}/admin/api/{self.api_version}/graphql.json"

        self.client = httpx.Client(
            headers={
                "X-Shopify-Access-Token": settings.shopify_access_token,
                "Content-Type": "application/json",
            },
            timeout=60.0,  # GraphQL queries can take longer
        )

    def _handle_rate_limit(self, response: httpx.Response, data: dict) -> None:
        """Check GraphQL cost and throttle status."""
        extensions = data.get("extensions", {})
        cost = extensions.get("cost", {})

        throttle_status = cost.get("throttleStatus", {})
        currently_available = throttle_status.get("currentlyAvailable", 1000)
        restore_rate = throttle_status.get("restoreRate", 50)

        if currently_available < 100:
            sleep_time = (100 - currently_available) / restore_rate
            logger.warning(
                "GraphQL rate limit low, sleeping",
                currently_available=currently_available,
                sleep_time=sleep_time,
            )
            time.sleep(sleep_time)

    @sleep_and_retry
    @limits(calls=4, period=1)  # GraphQL allows higher rate
    def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        """Execute a GraphQL query with rate limiting."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self.client.post(self.graphql_url, json=payload)
        response.raise_for_status()

        data = response.json()

        # Check for GraphQL errors
        if "errors" in data:
            errors = data["errors"]
            error_messages = [e.get("message", str(e)) for e in errors]
            logger.error("GraphQL errors", errors=error_messages)
            raise Exception(f"GraphQL errors: {error_messages}")

        self._handle_rate_limit(response, data)
        return data

    def get_products(
        self,
        first: int = 50,
        after: str | None = None,
        query: str | None = None,
    ) -> tuple[list[Product], str | None, bool]:
        """
        Fetch products using GraphQL.

        Returns:
            Tuple of (products, end_cursor, has_next_page)
        """
        variables: dict[str, Any] = {"first": min(first, 250)}
        if after:
            variables["after"] = after
        if query:
            variables["query"] = query

        data = self._query(PRODUCTS_QUERY, variables)

        products_data = data.get("data", {}).get("products", {})
        page_info = products_data.get("pageInfo", {})
        edges = products_data.get("edges", [])

        products = [Product.from_graphql(edge["node"]) for edge in edges]

        logger.info(
            "GraphQL: Fetched products",
            count=len(products),
            has_next=page_info.get("hasNextPage"),
        )

        return (
            products,
            page_info.get("endCursor"),
            page_info.get("hasNextPage", False),
        )

    def get_all_products(
        self,
        query: str | None = None,
        status: str = "active",
    ) -> list[Product]:
        """
        Fetch all products using GraphQL pagination.

        Args:
            query: Optional Shopify search query (e.g., "status:active")
            status: Product status filter (active, draft, archived)
        """
        all_products: list[Product] = []
        cursor: str | None = None
        has_next = True

        # Build query filter
        search_query = f"status:{status}"
        if query:
            search_query = f"{search_query} AND {query}"

        while has_next:
            products, cursor, has_next = self.get_products(
                first=250,  # Max allowed by GraphQL
                after=cursor,
                query=search_query,
            )
            all_products.extend(products)
            logger.info("GraphQL pagination progress", total=len(all_products))

        logger.info("GraphQL: Fetched all products", total=len(all_products))
        return all_products

    def get_product(self, product_id: int) -> Product:
        """Fetch a single product by numeric ID."""
        gid = f"gid://shopify/Product/{product_id}"
        data = self._query(PRODUCT_BY_ID_QUERY, {"id": gid})

        product_data = data.get("data", {}).get("product")
        if not product_data:
            raise ValueError(f"Product {product_id} not found")

        return Product.from_graphql(product_data)

    def update_product_tags(self, product_id: int, tags: list[str]) -> Product:
        """Update tags for a product using GraphQL mutation."""
        gid = f"gid://shopify/Product/{product_id}"

        variables = {
            "input": {
                "id": gid,
                "tags": tags,
            }
        }

        data = self._query(UPDATE_PRODUCT_TAGS_MUTATION, variables)

        result = data.get("data", {}).get("productUpdate", {})
        user_errors = result.get("userErrors", [])

        if user_errors:
            error_messages = [f"{e['field']}: {e['message']}" for e in user_errors]
            raise Exception(f"Failed to update tags: {error_messages}")

        product_data = result.get("product")
        if not product_data:
            raise Exception("No product returned from mutation")

        logger.info(
            "GraphQL: Updated product tags",
            product_id=product_id,
            tags=tags,
        )

        # Fetch full product since mutation returns limited fields
        return self.get_product(product_id)

    def get_products_without_tags(self) -> list[Product]:
        """Fetch products that have no tags."""
        # GraphQL doesn't support "tags is empty" directly,
        # so we fetch all and filter
        all_products = self.get_all_products()
        return [p for p in all_products if not p.tags]

    def get_products_by_tag(self, tag: str) -> list[Product]:
        """Fetch products with a specific tag."""
        return self.get_all_products(query=f'tag:"{tag}"')

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> "ShopifyGraphQLClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
