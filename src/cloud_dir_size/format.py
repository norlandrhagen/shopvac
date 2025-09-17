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


def table_to_markdown(table: pa.Table) -> str:
    """Convert table to markdown-format table"""
    data = table_to_data(table)
    return tabulate(data, headers="firstrow", tablefmt="github")


def send_to_slack(
    webhook_url: str, table: pa.Table, title: str = "GCS Bucket Analysis"
) -> bool:
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
    print("Successfully sent to Slack!")
    return True
