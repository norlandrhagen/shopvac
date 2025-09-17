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
    help="Min size in gb to filter out",
)
@click.option(
    "--send-slack", is_flag=True, help="Send table of result to a slack webhook"
)
@click.option(
    "--slack-webhook-url",
    default=None,
    help="Slack webhook URL",
)
def cli(
    bucket_url: str,
    min_size_gb: float,
    send_slack: bool,
    slack_webhook_url: Optional[str],
):
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

    Args:
        bucket_url: url to bucket. ex: gs://my-bucket
        min_size_gb: Min size in gb to filter out
        send_slack: Send results to Slack
        slack_webhook_url: S ack webhook url
    """
    table = await get_top_level_sizes(bucket_url, min_size_gb)

    print_table(table)

    print("\nMarkdown Table:")
    print(table_to_markdown(table))

    if send_slack:
        if not slack_webhook_url:
            raise ValueError("Slack webhook url must be provided if send_slack is True")
        send_to_slack(
            slack_webhook_url,
            table,
            f"Bucket: {bucket_url} (prefixes >= {min_size_gb} GB)",
        )
