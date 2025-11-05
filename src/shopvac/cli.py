import click
import asyncio
from typing import Optional, List, Tuple, Dict

from shopvac.size import get_top_level_sizes
from shopvac.format import send_to_slack, display_results

import pyarrow as pa


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

PROVIDER_OPTIONS = AWS_OPTIONS + GCP_OPTIONS


def add_options(options):
    def decorator(func):
        for option in reversed(options):
            func = option(func)
        return func

    return decorator


@click.command()
@click.option(
    "--bucket-url",
    "-b",
    "bucket_urls",
    multiple=True,
    required=True,
    help="Cloud bucket URL(s) to analyze. Can be specified multiple times.",
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
@click.option(
    "--timeout-per-prefix",
    default=3600,
    show_default=True,
    type=int,
    help="Maximum seconds to spend on each prefix before timeout",
)
@click.option(
    "--fail-fast",
    is_flag=True,
    help="Stop on first error instead of continuing with other prefixes",
)
@click.option(
    "--max-concurrent-buckets",
    default=5,
    show_default=True,
    type=int,
    help="Maximum number of buckets to analyze concurrently",
)
@add_options(PROVIDER_OPTIONS)
def cli(
    bucket_urls: Tuple[str, ...],
    min_size_gb: float,
    send_slack: bool,
    slack_webhook_url: Optional[str],
    rich_table: bool,
    timeout_per_prefix: int,
    fail_fast: bool,
    max_concurrent_buckets: int,
    aws_region: Optional[str],
    aws_access_key_id: Optional[str],
    aws_secret_access_key: Optional[str],
    aws_session_token: Optional[str],
    aws_profile: Optional[str],
    skip_signature: bool,
    gcp_service_account_path: Optional[str],
    gcp_project_id: Optional[str],
):
    bucket_urls = [url for url in bucket_urls if url and url.strip()]

    if not bucket_urls:
        raise click.BadParameter("At least one valid bucket URL must be provided")

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

    provider_options = {k: v for k, v in provider_options.items() if v is not None}

    asyncio.run(
        main(
            bucket_urls=list(bucket_urls),
            min_size_gb=min_size_gb,
            send_slack=send_slack,
            slack_webhook_url=slack_webhook_url,
            rich_table=rich_table,
            timeout_per_prefix=timeout_per_prefix,
            continue_on_error=not fail_fast,
            max_concurrent_buckets=max_concurrent_buckets,
            **provider_options,
        )
    )

async def analyze_single_bucket(
    bucket_url: str,
    min_size_gb: float,
    timeout_per_prefix: int,
    continue_on_error: bool,
    show_progress: bool,
    **provider_options,
) -> Tuple[str, Optional[pa.Table], Optional[Exception]]:
    try:
        table = await get_top_level_sizes(
            bucket_url,
            min_size_gb,
            timeout_per_prefix=timeout_per_prefix,
            continue_on_error=continue_on_error,
            show_progress=show_progress,
            **provider_options,
        )

        print(f"\nCompleted: {bucket_url} ({table.num_rows} prefixes)\n")
        return bucket_url, table, None

    except Exception as e:
        print(f"\nFailed: {bucket_url}")
        print(f"   Error: {type(e).__name__}: {e}\n")
        return bucket_url, None, e


async def analyze_multiple_buckets(
    bucket_urls: List[str],
    min_size_gb: float,
    timeout_per_prefix: int,
    continue_on_error: bool,
    max_concurrent_buckets: int,
    **provider_options,
) -> Dict[str, pa.Table]:
    semaphore = asyncio.Semaphore(max_concurrent_buckets)

    async def bounded_analyze(bucket_url: str):
        async with semaphore:
            return await analyze_single_bucket(
                bucket_url,
                min_size_gb,
                timeout_per_prefix,
                continue_on_error,
                show_progress=False,
                **provider_options,
            )

    results = await asyncio.gather(
        *[bounded_analyze(url) for url in bucket_urls], return_exceptions=True
    )

    bucket_tables = {}
    errors = []

    for result in results:
        if isinstance(result, Exception):
            errors.append(("Unknown bucket", result))
        else:
            bucket_url, table, error = result
            if table is not None:
                bucket_tables[bucket_url] = table
            if error is not None:
                errors.append((bucket_url, error))

    if errors:
        print(f"Failed: {len(errors)} buckets")
        for bucket_url, error in errors:
            print(f"   - {bucket_url}: {type(error).__name__}")

    return bucket_tables


async def main(
    bucket_urls: List[str],
    min_size_gb: float = 10.0,
    send_slack: bool = False,
    slack_webhook_url: Optional[str] = None,
    rich_table: bool = False,
    timeout_per_prefix: int = 3600,
    continue_on_error: bool = True,
    max_concurrent_buckets: int = 10,
    **provider_options,
) -> None:
    if len(bucket_urls) == 1:
        bucket_url = bucket_urls[0]
        table = await get_top_level_sizes(
            bucket_url,
            min_size_gb,
            timeout_per_prefix=timeout_per_prefix,
            continue_on_error=continue_on_error,
            show_progress=True,
            **provider_options,
        )

        display_results(table, bucket_url, use_rich_table=rich_table)

        if send_slack:
            if not slack_webhook_url:
                raise ValueError(
                    "Slack webhook url must be provided if send_slack is True"
                )
            send_to_slack(
                slack_webhook_url,
                table,
                f"Bucket: {bucket_url} (prefixes >= {min_size_gb} GB)",
            )

    else:
        print(
            f"Analyzing {len(bucket_urls)} buckets concurrently (max {max_concurrent_buckets} at a time)..."
        )
        print("This may take a while. Results will be displayed when complete.\n")

        import time

        start_time = time.time()

        bucket_tables = await analyze_multiple_buckets(
            bucket_urls,
            min_size_gb,
            timeout_per_prefix,
            continue_on_error,
            max_concurrent_buckets,
            **provider_options,
        )

        elapsed = time.time() - start_time

        failed_buckets = set(bucket_urls) - set(bucket_tables.keys())

        print(f"{'=' * 70}")
        print("ANALYSIS COMPLETE")
        print(f"{'=' * 70}")
        print(f"Successful: {len(bucket_tables)}/{len(bucket_urls)} buckets")
        print(f"Time: {int(elapsed // 60)}m {int(elapsed % 60)}s")
        if failed_buckets:
            print(f"Failed: {len(failed_buckets)} buckets")
            for bucket_url in failed_buckets:
                print(f"   - {bucket_url}")
        print(f"{'=' * 70}\n")

        for bucket_url, table in bucket_tables.items():
            print(f"\n{'=' * 70}")
            print(f"Results for: {bucket_url}")
            print(f"{'=' * 70}")
            display_results(table, bucket_url, use_rich_table=rich_table)

        if send_slack:
            if not slack_webhook_url:
                raise ValueError(
                    "Slack webhook url must be provided if send_slack is True"
                )

            for bucket_url, table in bucket_tables.items():
                send_to_slack(
                    slack_webhook_url,
                    table,
                    f"Bucket: {bucket_url} (prefixes >= {min_size_gb} GB)",
                )