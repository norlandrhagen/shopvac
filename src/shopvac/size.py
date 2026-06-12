import asyncio
from typing import Any

import obstore as obs
import pyarrow as pa
import pyarrow.compute as pc
from humanize import naturalsize

from shopvac.store_factory import store_factory


def _accumulate_batch(
    batch: pa.RecordBatch, max_depth: int, sizes: dict[str, int]
) -> int:
    """Accumulate object sizes into per-prefix totals for all depths <= max_depth."""
    batch_total = 0
    for path, size in zip(batch["path"].to_pylist(), batch["size"].to_pylist()):
        batch_total += size
        parts = path.split("/")
        for d in range(1, min(max_depth, len(parts) - 1) + 1):
            key = "/".join(parts[:d])
            sizes[key] = sizes.get(key, 0) + size
    return batch_total


def _order_hierarchy(sizes: dict[str, int]) -> list[tuple[str, int, int]]:
    """Order prefixes depth-first: parents before children, siblings by size desc."""
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for key in sizes:
        if "/" in key:
            children.setdefault(key.rsplit("/", 1)[0], []).append(key)
        else:
            roots.append(key)

    ordered: list[tuple[str, int, int]] = []

    def visit(key: str, depth: int) -> None:
        ordered.append((key, sizes[key], depth))
        for child in sorted(
            children.get(key, []), key=lambda k: sizes[k], reverse=True
        ):
            visit(child, depth + 1)

    for root in sorted(roots, key=lambda k: sizes[k], reverse=True):
        visit(root, 1)
    return ordered


async def get_prefix_size(
    store: obs.store,
    prefix: str,
    timeout_seconds: int = 3600,
    max_depth: int = 1,
    progress=None,
    task_id=None,
) -> tuple[str, int, dict[str, int]]:
    if progress is not None:
        progress.update(task_id, description=f"Scanning {prefix.rstrip('/')}")

    async def calculate_size() -> tuple[int, dict[str, int]]:
        stream = obs.list(store, prefix=prefix, return_arrow=True)
        total_size = 0
        sizes: dict[str, int] = {}
        async for batch in stream:
            pyarrow_batch = pa.record_batch(batch)
            if len(pyarrow_batch) > 0:
                if max_depth > 1:
                    batch_total = _accumulate_batch(pyarrow_batch, max_depth, sizes)
                else:
                    batch_total = pc.sum(pyarrow_batch["size"]).as_py()
                total_size += batch_total
                if progress is not None:
                    progress.update(
                        task_id,
                        description=f"Scanning {prefix.rstrip('/')}: {naturalsize(total_size, binary=True)}",
                    )
        if max_depth == 1:
            sizes[prefix.rstrip("/")] = total_size
        return total_size, sizes

    try:
        total_size, sizes = await asyncio.wait_for(
            calculate_size(), timeout=timeout_seconds
        )
    except Exception as e:
        if progress is not None:
            progress.update(
                task_id,
                completed=1,
                total=1,
                description=f"[red]✗ Failed {prefix.rstrip('/')}: {type(e).__name__}[/red]",
            )
        raise

    if progress is not None:
        progress.update(
            task_id,
            completed=1,
            total=1,
            description=f"[green]✓ Done {prefix.rstrip('/')}[/green]: {naturalsize(total_size, binary=True)}",
        )

    return prefix, total_size, sizes


async def get_top_level_sizes(
    bucket_url: str,
    min_size_gb: float = 1.0,
    timeout_per_prefix: int = 3600,
    continue_on_error: bool = True,
    show_progress: bool = False,
    depth: int = 1,
    **provider_options,
) -> pa.Table:
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.console import Console

    store = store_factory.create_store(bucket_url, **provider_options)
    result: dict[str, Any] = await obs.list_with_delimiter_async(store, prefix=None)
    top_level_prefixes: list[str] = result["common_prefixes"]

    if show_progress:
        with Progress(
            SpinnerColumn(finished_text=" "),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=Console(),
            expand=True,
        ) as progress:
            tasks = [
                get_prefix_size(
                    store,
                    prefix,
                    timeout_per_prefix,
                    max_depth=depth,
                    progress=progress,
                    task_id=progress.add_task(
                        f"Waiting {prefix.rstrip('/')}", total=None
                    ),
                )
                for prefix in top_level_prefixes
            ]
            results = await asyncio.gather(*tasks, return_exceptions=continue_on_error)
    else:
        tasks = [
            get_prefix_size(store, prefix, timeout_per_prefix, max_depth=depth)
            for prefix in top_level_prefixes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=continue_on_error)

    if continue_on_error:
        results = [r for r in results if not isinstance(r, Exception)]

    if depth <= 1:
        filtered_data = [
            (prefix, size)
            for prefix, size, _ in results
            if size / (1024**3) >= min_size_gb
        ]

        table = pa.table(
            {
                "prefix": [prefix for prefix, _ in filtered_data],
                "size_bytes": [size for _, size in filtered_data],
                "size_formatted": [
                    naturalsize(size, binary=True) for _, size in filtered_data
                ],
            }
        )

        sorted_indices = pc.sort_indices(
            table["size_bytes"], sort_keys=[("size_bytes", "descending")]
        )
        return pc.take(table, sorted_indices)

    merged: dict[str, int] = {}
    for _, _, sizes in results:
        merged.update(sizes)

    # Children never exceed parents, so filtering keeps the tree connected.
    threshold_bytes = min_size_gb * 1024**3
    kept = {k: v for k, v in merged.items() if v >= threshold_bytes}
    ordered = _order_hierarchy(kept)

    return pa.table(
        {
            "prefix": [p for p, _, _ in ordered],
            "size_bytes": [s for _, s, _ in ordered],
            "size_formatted": [naturalsize(s, binary=True) for _, s, _ in ordered],
            "depth": [d for _, _, d in ordered],
        }
    )
