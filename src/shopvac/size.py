import asyncio
from typing import Any

import obstore as obs
import pyarrow as pa
import pyarrow.compute as pc
from humanize import naturalsize

from shopvac.store_factory import store_factory


async def get_prefix_size(
    store: obs.store,
    prefix: str,
    timeout_seconds: int = 3600,
    progress=None,
    task_id=None,
) -> tuple[str, int]:
    if progress is not None:
        progress.update(task_id, description=f"Scanning {prefix.rstrip('/')}")

    async def calculate_size() -> int:
        stream = obs.list(store, prefix=prefix, return_arrow=True)
        total_size = 0
        async for batch in stream:
            pyarrow_batch = pa.record_batch(batch)
            if len(pyarrow_batch) > 0:
                batch_total = pc.sum(pyarrow_batch["size"]).as_py()
                total_size += batch_total
                if progress is not None:
                    progress.update(
                        task_id,
                        description=f"Scanning {prefix.rstrip('/')}: {naturalsize(total_size)}",
                    )
        return total_size

    try:
        total_size = await asyncio.wait_for(calculate_size(), timeout=timeout_seconds)
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
            description=f"[green]✓ Done {prefix.rstrip('/')}[/green]: {naturalsize(total_size)}",
        )

    return prefix, total_size


async def get_top_level_sizes(
    bucket_url: str,
    min_size_gb: float = 1.0,
    timeout_per_prefix: int = 3600,
    continue_on_error: bool = True,
    show_progress: bool = False,
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
            get_prefix_size(store, prefix, timeout_per_prefix)
            for prefix in top_level_prefixes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=continue_on_error)

    if continue_on_error:
        results = [r for r in results if not isinstance(r, Exception)]

    filtered_data = [
        (prefix, size) for prefix, size in results if size / (1024**3) >= min_size_gb
    ]

    table = pa.table(
        {
            "prefix": [prefix for prefix, _ in filtered_data],
            "size_bytes": [size for _, size in filtered_data],
            "size_formatted": [naturalsize(size) for _, size in filtered_data],
        }
    )

    sorted_indices = pc.sort_indices(
        table["size_bytes"], sort_keys=[("size_bytes", "descending")]
    )
    return pc.take(table, sorted_indices)
