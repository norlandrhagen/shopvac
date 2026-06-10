import pyarrow as pa
import requests
from tabulate import tabulate
from typing import List


def _is_tree(table: pa.Table) -> bool:
    return "depth" in table.schema.names


def _tree_lines(table: pa.Table) -> List[List[str]]:
    """Flatten hierarchical table into (label, size) lines with tree connectors.

    Rows must be ordered depth-first with parents before children
    (as produced by size._order_hierarchy).
    """
    children: dict = {}
    roots = []
    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py()
        size_formatted = table["size_formatted"][i].as_py()
        depth = table["depth"][i].as_py()
        if depth == 1:
            roots.append((prefix, size_formatted))
        else:
            children.setdefault(prefix.rsplit("/", 1)[0], []).append(
                (prefix, size_formatted)
            )

    lines: List[List[str]] = []

    def visit(prefix: str, size_formatted: str, ancestors_last: list) -> None:
        if ancestors_last:
            indent = "".join("    " if last else "│   " for last in ancestors_last[:-1])
            indent += "└── " if ancestors_last[-1] else "├── "
            label = indent + prefix.rsplit("/", 1)[1]
        else:
            label = prefix
        lines.append([label, size_formatted])
        kids = children.get(prefix, [])
        for i, (child_prefix, child_size) in enumerate(kids):
            visit(child_prefix, child_size, ancestors_last + [i == len(kids) - 1])

    for prefix, size_formatted in roots:
        visit(prefix, size_formatted, [])
    return lines


def table_to_data(table: pa.Table) -> List[List[str]]:
    data = [["Prefix", "Size"]]
    if _is_tree(table):
        for i in range(table.num_rows):
            prefix = table["prefix"][i].as_py()
            size_formatted = table["size_formatted"][i].as_py()
            depth = table["depth"][i].as_py()
            if depth > 1:
                prefix = "  " * (depth - 1) + prefix.rsplit("/", 1)[1]
            data.append([prefix, size_formatted])
        return data
    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py()
        size_formatted = table["size_formatted"][i].as_py()
        data.append([prefix, size_formatted])
    return data


def print_table(table: pa.Table) -> None:
    """Pretty-print table to stdout."""
    print(f"\n{'Prefix':<50} {'Size':<15}")
    print("-" * 65)
    if _is_tree(table):
        for label, size_formatted in _tree_lines(table):
            print(f"{label:<50} {size_formatted:<15}")
        return
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


def print_rich_tree(table: pa.Table, title: str) -> None:
    """Print hierarchical results as a rich tree."""
    from rich.tree import Tree
    from rich.console import Console

    console = Console()

    root = Tree(f"[bold]{title}[/bold]")
    nodes: dict = {}
    for i in range(table.num_rows):
        prefix = table["prefix"][i].as_py()
        size_formatted = table["size_formatted"][i].as_py()
        depth = table["depth"][i].as_py()
        name = prefix if depth == 1 else prefix.rsplit("/", 1)[1]
        parent = root if depth == 1 else nodes[prefix.rsplit("/", 1)[0]]
        nodes[prefix] = parent.add(
            f"[cyan]{name}[/cyan] [magenta]{size_formatted}[/magenta]"
        )

    console.print("\n")
    console.print(root)
    console.print("\n")


def display_results(
    table: pa.Table, bucket_url: str, use_rich_table: bool = False
) -> None:
    """rich table/tree or standard"""
    if use_rich_table:
        if _is_tree(table):
            print_rich_tree(table, f"Bucket Analysis: {bucket_url}")
        else:
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
