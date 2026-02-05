"""Main CLI for Shopify product tagger."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.config import get_settings
from src.logging_config import get_logger, setup_logging
from src.shopify_client import Product, ShopifyClient, ShopifyGraphQLClient
from src.slack import send_tagging_report
from src.tagger import ClaudeTagger, get_all_existing_tags

app = typer.Typer(
    name="shopify-tagger",
    help="AI-powered product tagging for Shopify",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main_callback() -> None:
    """Initialize logging on startup."""
    setup_logging()


@app.command()
def tag_all(
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Preview changes without updating Shopify"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", help="Limit number of products to process"
    ),
    only_untagged: bool = typer.Option(
        False, "--only-untagged", "-u", help="Only process products with no tags"
    ),
    notify: bool = typer.Option(
        True, "--notify/--no-notify", help="Send Slack notification on completion"
    ),
    use_rest: bool = typer.Option(
        False, "--rest", help="Use REST API instead of GraphQL (slower)"
    ),
) -> None:
    """Tag all products in the catalog using AI."""
    logger = get_logger(__name__)
    settings = get_settings()

    # Override dry_run from settings if CLI flag set
    if dry_run:
        console.print("[yellow]🔍 DRY RUN MODE - No changes will be made[/yellow]\n")

    api_mode = "REST" if use_rest else "GraphQL"
    console.print(f"[dim]Using {api_mode} API[/dim]\n")

    # Choose client based on flag
    if use_rest:
        client = ShopifyClient()
    else:
        client = ShopifyGraphQLClient()

    with client:
        # Fetch products
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(f"Fetching products via {api_mode}...", total=None)
            products = client.get_all_products()

        console.print(f"Found [bold]{len(products)}[/bold] products\n")

        # Filter if needed
        if only_untagged:
            products = [p for p in products if not p.tags]
            console.print(f"Filtered to [bold]{len(products)}[/bold] untagged products\n")

        if limit:
            products = products[:limit]
            console.print(f"Limited to [bold]{len(products)}[/bold] products\n")

        if not products:
            console.print("[yellow]No products to process[/yellow]")
            return

        # Get existing tags for consistency
        all_existing_tags = get_all_existing_tags(products)
        console.print(f"Found [bold]{len(all_existing_tags)}[/bold] existing unique tags\n")

        # Initialize tagger with existing tags
        tagger = ClaudeTagger(existing_tags=all_existing_tags)

        # Process products
        updated_count = 0
        errors: list[str] = []

        for i, product in enumerate(products, 1):
            console.print(
                f"[dim][{i}/{len(products)}][/dim] Processing: {product.title[:50]}..."
            )

            try:
                new_tags = tagger.generate_tags(product)

                # Check if tags changed
                if set(new_tags) != set(product.tags):
                    console.print(f"  Old tags: {', '.join(product.tags) or '(none)'}")
                    console.print(f"  New tags: [green]{', '.join(new_tags)}[/green]")

                    if not dry_run:
                        client.update_product_tags(product.id, new_tags)
                        updated_count += 1
                    else:
                        updated_count += 1  # Count would-be updates in dry run
                else:
                    console.print("  [dim]No changes needed[/dim]")

            except Exception as e:
                error_msg = f"Error processing {product.id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                console.print(f"  [red]Error: {e}[/red]")

        # Summary
        console.print("\n" + "=" * 50)
        console.print(f"[bold]Summary[/bold]")
        console.print(f"  Products processed: {len(products)}")
        console.print(f"  Products {'would be ' if dry_run else ''}updated: {updated_count}")
        if errors:
            console.print(f"  [red]Errors: {len(errors)}[/red]")

        # Send Slack notification
        if notify and settings.slack_webhook_url:
            send_tagging_report(len(products), updated_count, errors, dry_run)


@app.command()
def tag_product(
    product_id: int = typer.Argument(..., help="Shopify product ID to tag"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Preview changes without updating"
    ),
    use_rest: bool = typer.Option(
        False, "--rest", help="Use REST API instead of GraphQL"
    ),
) -> None:
    """Tag a single product by ID."""
    if use_rest:
        client = ShopifyClient()
    else:
        client = ShopifyGraphQLClient()

    with client:
        product = client.get_product(product_id)

        console.print(f"\n[bold]{product.title}[/bold]")
        console.print(f"Current tags: {', '.join(product.tags) or '(none)'}")

        tagger = ClaudeTagger()
        new_tags = tagger.generate_tags(product)

        console.print(f"Suggested tags: [green]{', '.join(new_tags)}[/green]")

        if not dry_run:
            if typer.confirm("Apply these tags?"):
                client.update_product_tags(product.id, new_tags)
                console.print("[green]✓ Tags updated[/green]")
        else:
            console.print("[yellow]Dry run - no changes made[/yellow]")


@app.command()
def list_tags(
    use_rest: bool = typer.Option(
        False, "--rest", help="Use REST API instead of GraphQL"
    ),
) -> None:
    """List all unique tags currently in use."""
    if use_rest:
        client = ShopifyClient()
    else:
        client = ShopifyGraphQLClient()

    with client:
        products = client.get_all_products()

    all_tags = get_all_existing_tags(products)

    # Count tag usage
    tag_counts: dict[str, int] = {}
    for product in products:
        for tag in product.tags:
            tag_lower = tag.lower()
            tag_counts[tag_lower] = tag_counts.get(tag_lower, 0) + 1

    # Display as table
    table = Table(title=f"Tags in Catalog ({len(all_tags)} unique)")
    table.add_column("Tag", style="cyan")
    table.add_column("Count", justify="right")

    for tag in sorted(all_tags, key=lambda t: tag_counts.get(t, 0), reverse=True):
        table.add_row(tag, str(tag_counts.get(tag, 0)))

    console.print(table)


@app.command()
def find_untagged(
    use_rest: bool = typer.Option(
        False, "--rest", help="Use REST API instead of GraphQL"
    ),
) -> None:
    """Find products with no tags."""
    if use_rest:
        client = ShopifyClient()
    else:
        client = ShopifyGraphQLClient()

    with client:
        products = client.get_products_without_tags()

    if not products:
        console.print("[green]All products have tags![/green]")
        return

    table = Table(title=f"Untagged Products ({len(products)})")
    table.add_column("ID", style="dim")
    table.add_column("Title")
    table.add_column("Status")

    for product in products:
        table.add_row(str(product.id), product.title[:60], product.status)

    console.print(table)


@app.command()
def preview(
    count: int = typer.Option(5, "--count", "-c", help="Number of products to preview"),
    use_rest: bool = typer.Option(
        False, "--rest", help="Use REST API instead of GraphQL"
    ),
) -> None:
    """Preview tag suggestions for a sample of products."""
    if use_rest:
        client = ShopifyClient()
    else:
        client = ShopifyGraphQLClient()

    with client:
        products = client.get_all_products()[:count]

    if not products:
        console.print("[yellow]No products found[/yellow]")
        return

    all_existing_tags = get_all_existing_tags(products)
    tagger = ClaudeTagger(existing_tags=all_existing_tags)

    for product in products:
        console.print(f"\n[bold]{'=' * 50}[/bold]")
        console.print(f"[bold]{product.title}[/bold]")
        console.print(f"[dim]ID: {product.id} | Type: {product.product_type}[/dim]")
        console.print(f"Current: {', '.join(product.tags) or '(none)'}")

        new_tags = tagger.generate_tags(product)
        console.print(f"Suggested: [green]{', '.join(new_tags)}[/green]")


if __name__ == "__main__":
    app()
