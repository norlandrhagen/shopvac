import pyarrow as pa
import requests
from tabulate import tabulate
from typing import List


def table_to_data(table: pa.Table) -> List[List[str]]:
    data = [["Prefix", "Size"]]
    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py()
        size_formatted = table["size_formatted"][i].as_py()
        data.append([prefix, size_formatted])
    return data


def print_table(table: pa.Table) -> None:
    """Pretty-print table to stdout."""
    print(f"\n{'Prefix':<50} {'Size':<15}")
    print("-" * 65)
    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py()
        size_formatted = table["size_formatted"][i].as_py()
        print(f"{prefix:<50} {size_formatted:<15}")


def print_rich_table(table: pa.Table, title: str) -> None:
    """Print a rich table to stdout."""
    from rich.table import Table
    from rich.console import Console

    console = Console()

    rich_table = Table(title=title)
    rich_table.add_column("Prefix", style="cyan", no_wrap=True)
    rich_table.add_column("Size", style="magenta")

    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py().rstrip("/")
        size_formatted = table["size_formatted"][i].as_py()

        rich_table.add_row(prefix, size_formatted)

    console.print("\n")
    console.print(rich_table)
    console.print("\n")


def display_results(
    table: pa.Table, bucket_url: str, use_rich_table: bool = False
) -> None:
    """rich table or standard"""
    if use_rich_table:
        print_rich_table(table, f"Bucket Analysis: {bucket_url}")
    else:
        print_table(table)


def send_to_slack(
    webhook_url: str, table: pa.Table, title: str = "Cloud Bucket Analysis"
) -> bool:
    """Send table results to Slack"""
    table_string = tabulate(table_to_data(table), headers="firstrow", tablefmt="simple")

    message = {
        "text": title,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{table_string}\n```"},
            },
        ],
    }

    response = requests.post(webhook_url, json=message)
    response.raise_for_status()
    print("sent table to slack")
    return True
