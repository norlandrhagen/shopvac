# src/shopvac/cli.py

import click
import asyncio
from typing import Optional

from shopvac.size import get_top_level_sizes
from shopvac.format import send_to_slack, display_results

from shopvac.store_factory import store_factory


# Define CLI options organized by provider
AWS_OPTIONS = [
    click.option(
        "--aws-region",
        default=None,
        help="AWS region for S3 buckets. If not provided, will attempt to infer from bucket.",
    ),
    click.option(
        "--aws-access-key-id",
        default=None,
        help="AWS access key ID. If not provided, will use default credential chain.",
    ),
    click.option(
        "--aws-secret-access-key",
        default=None,
        help="AWS secret access key. If not provided, will use default credential chain.",
    ),
    click.option(
        "--aws-session-token",
        default=None,
        help="AWS session token for temporary credentials.",
    ),
    click.option(
        "--aws-profile",
        default=None,
        help="AWS profile name to use from credentials file.",
    ),
    click.option(
        "--skip-signature",
        is_flag=True,
        help="Skip request signing for public S3 buckets.",
    ),
]

GCP_OPTIONS = [
    click.option(
        "--gcp-service-account-path",
        default=None,
        help="Path to GCP service account JSON file.",
    ),
    click.option("--gcp-project-id", default=None, help="GCP project ID."),
]

# Combine all provider options
PROVIDER_OPTIONS = AWS_OPTIONS + GCP_OPTIONS


def add_options(options):
    """Decorator to add multiple click options to a command."""

    def decorator(func):
        for option in reversed(options):  # Reversed to maintain order
            func = option(func)
        return func

    return decorator


@click.command()
@click.option(
    "--bucket-url",
    required=True,
    help=f"Cloud bucket URL to analyze. Supported schemes: {', '.join(store_factory.get_supported_schemes())}",
)
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
@click.option(
    "--rich-table",
    is_flag=True,
    help="Display results as a rich table instead of markdown",
)
@add_options(PROVIDER_OPTIONS)
def cli(
    bucket_url: str,
    min_size_gb: float,
    send_slack: bool,
    slack_webhook_url: Optional[str],
    rich_table: bool,
    # AWS options
    aws_region: Optional[str],
    aws_access_key_id: Optional[str],
    aws_secret_access_key: Optional[str],
    aws_session_token: Optional[str],
    aws_profile: Optional[str],
    skip_signature: bool,
    # GCP options
    gcp_service_account_path: Optional[str],
    gcp_project_id: Optional[str],
):
    """Analyze cloud bucket sizes."""
    # Collect all provider-specific options
    provider_options = {
        "aws_region": aws_region,
        "aws_access_key_id": aws_access_key_id,
        "aws_secret_access_key": aws_secret_access_key,
        "aws_session_token": aws_session_token,
        "aws_profile": aws_profile,
        "skip_signature": skip_signature,
        "gcp_service_account_path": gcp_service_account_path,
        "gcp_project_id": gcp_project_id,
    }

    # Filter out None values to keep the interface clean
    provider_options = {k: v for k, v in provider_options.items() if v is not None}

    asyncio.run(
        main(
            bucket_url=bucket_url,
            min_size_gb=min_size_gb,
            send_slack=send_slack,
            slack_webhook_url=slack_webhook_url,
            rich_table=rich_table,
            **provider_options,
        )
    )


async def main(
    bucket_url: str,
    min_size_gb: float = 10.0,
    send_slack: bool = False,
    slack_webhook_url: Optional[str] = None,
    rich_table: bool = False,
    **provider_options,
) -> None:
    """
    Analyze cloud bucket sizes.

    Args:
        bucket_url: url to bucket. ex: gs://my-bucket or s3://my-bucket
        min_size_gb: Min size in gb to filter out
        send_slack: Send results to Slack
        slack_webhook_url: Slack webhook url
        rich_table: Display results as rich table instead of markdown
        **provider_options: Provider-specific options (AWS, GCP, etc.)
    """
    table = await get_top_level_sizes(bucket_url, min_size_gb, **provider_options)

    # Display results using format module
    display_results(table, bucket_url, use_rich_table=rich_table)

    if send_slack:
        if not slack_webhook_url:
            raise ValueError("Slack webhook url must be provided if send_slack is True")

        # Always send markdown to Slack (handled in format module)
        send_to_slack(
            slack_webhook_url,
            table,
            f"Bucket: {bucket_url} (prefixes >= {min_size_gb} GB)",
        )
