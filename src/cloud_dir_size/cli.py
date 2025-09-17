# src/cloud_dir_size/cli.py

import click
import asyncio
from typing import Optional


from cloud_dir_size.size import get_top_level_sizes
from cloud_dir_size.format import print_table, table_to_markdown, send_to_slack


@click.command()
@click.option("--bucket-url", required=True, help="GCS bucket URL to analyze.")
@click.option(
    "--min-size-gb",
    default=10.0,
    show_default=True,
    type=float,
    help="Minimum size (in GB) to include.",
)
@click.option("--send-slack", is_flag=True, help="Send results to Slack via webhook.")
@click.option(
    "--slack-webhook-url",
    default=None,
    help="Slack webhook URL (required if --send-slack is set).",
)
def cli(
    bucket_url: str,
    min_size_gb: float,
    send_slack: bool,
    slack_webhook_url: Optional[str],
):
    """Analyze a GCS bucket's top-level prefixes and optionally send results to Slack."""
    asyncio.run(
        main(
            bucket_url=bucket_url,
            min_size_gb=min_size_gb,
            send_slack=send_slack,
            slack_webhook_url=slack_webhook_url,
        )
    )


async def main(
    bucket_url: str,
    min_size_gb: float = 10.0,
    send_slack: bool = False,
    slack_webhook_url: Optional[str] = None,
) -> None:
    """
    Analyze GCS bucket prefixes and optionally send results to Slack.

    Args:
        bucket_url: GCS bucket to analyze.
        min_size_gb: Minimum size in GB to include in results.
        send_slack: Whether to send results to Slack.
        slack_webhook_url: Required if send_slack is True.
    """
    print(f"Analyzing {bucket_url} (min size: {min_size_gb} GB)...")

    table = await get_top_level_sizes(bucket_url, min_size_gb)

    print_table(table)

    print("\nMarkdown Table:")
    print(table_to_markdown(table))

    if send_slack:
        if not slack_webhook_url:
            raise ValueError("Slack webhook URL must be provided if send_slack=True")
        send_to_slack(
            slack_webhook_url,
            table,
            f"Bucket: {bucket_url} (prefixes >= {min_size_gb} GB)",
        )


if __name__ == "__main__":
    asyncio.run(
        main(
            send_slack=True,
            slack_webhook_url="https://hooks.slack.com/services/XXX/YYY/ZZZ",
        )
    )
