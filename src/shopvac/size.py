import asyncio
from typing import List, Tuple, Any
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TaskID
from rich.console import Console

import obstore as obs
import pyarrow as pa
import pyarrow.compute as pc
from humanize import naturalsize

from shopvac.store_factory import store_factory


async def get_prefix_size_with_progress(
    store: obs.store,
    prefix: str,
    progress: Progress,
    task_id: TaskID,
    timeout_seconds: int = 3600,  # 1 hour default timeout
) -> Tuple[str, int]:
    """Calculate total size for a prefix with progress updates and timeout."""
    try:
        progress.update(task_id, description=f"🔍 {prefix.rstrip('/')}")

        # Wrap the entire operation in a timeout
        async def calculate_size():
            stream = obs.list(store, prefix=prefix, return_arrow=True)
            total_size = 0

            async for batch in stream:
                pyarrow_batch = pa.record_batch(batch)
                if len(pyarrow_batch) > 0:
                    sizes_column = pyarrow_batch["size"]
                    batch_total = pc.sum(sizes_column).as_py()
                    total_size += batch_total

                    # Update with current size
                    progress.update(
                        task_id,
                        description=f"🔍 {prefix.rstrip('/')}: {naturalsize(total_size)}",
                    )

            return total_size

        total_size = await asyncio.wait_for(calculate_size(), timeout=timeout_seconds)

        # Mark as completed
        progress.update(
            task_id, description=f"✅ {prefix.rstrip('/')}: {naturalsize(total_size)}"
        )
        return prefix, total_size

    except asyncio.TimeoutError:
        progress.update(
            task_id,
            description=f"⏱️  {prefix.rstrip('/')}: Timeout (>{timeout_seconds}s)",
        )
        return prefix, 0
    except obs.exceptions.InvalidPathError:
        progress.update(task_id, description=f"⚠️  {prefix.rstrip('/')}: Invalid path")
        return prefix, 0
    except Exception as e:
        progress.update(
            task_id, description=f"❌ {prefix.rstrip('/')}: Error ({type(e).__name__})"
        )
        return prefix, 0


async def get_top_level_sizes(
    bucket_url: str,
    min_size_gb: float = 1.0,
    timeout_per_prefix: int = 3600,  # 1 hour per prefix
    continue_on_error: bool = True,  # Continue even if some prefixes fail
    **provider_options,
) -> pa.Table:
    """
    Returns an Arrow table of prefixes with sizes.

    Args:
        bucket_url: URL of the bucket to analyze
        min_size_gb: Minimum size in GB to include in results
        timeout_per_prefix: Maximum seconds to spend on each prefix
        continue_on_error: If True, continue processing other prefixes on failure
        **provider_options: Provider-specific options (AWS, GCP, etc.)
    """
    console = Console()

    # Use the factory to create the appropriate store with provider-specific options
    store = store_factory.create_store(bucket_url, **provider_options)

    result: dict[str, Any] = await obs.list_with_delimiter_async(store, prefix=None)
    top_level_prefixes: List[str] = result["common_prefixes"]

    # Create progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
    ) as progress:
        # Create tasks for all prefixes with individual progress tracking
        tasks_and_ids = []
        for prefix in top_level_prefixes:
            task_id = progress.add_task(f"⏳ {prefix.rstrip('/')}", total=None)
            task_coro = get_prefix_size_with_progress(
                store, prefix, progress, task_id, timeout_seconds=timeout_per_prefix
            )
            tasks_and_ids.append(task_coro)

        # Run all tasks concurrently
        if continue_on_error:
            # Use return_exceptions=True to continue on failure
            results = await asyncio.gather(*tasks_and_ids, return_exceptions=True)

            # Filter out exceptions and log them
            valid_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    console.print(f"Error processing {top_level_prefixes[i]}: {result}")
                else:
                    valid_results.append(result)
            results = valid_results
        else:
            # Fail fast on first error
            results = await asyncio.gather(*tasks_and_ids)

    # Filter results based on size
    filtered_data: List[Tuple[str, int]] = []
    for prefix, size in results:
        size_gb = size / (1024**3)
        if size_gb >= min_size_gb:
            filtered_data.append((prefix, size))

    prefixes = [prefix for prefix, _ in filtered_data]
    sizes_bytes = [size for _, size in filtered_data]
    sizes_formatted = [naturalsize(size) for _, size in filtered_data]

    table = pa.table(
        {
            "prefix": prefixes,
            "size_bytes": sizes_bytes,
            "size_formatted": sizes_formatted,
        }
    )

    sorted_indices = pc.sort_indices(
        table["size_bytes"], sort_keys=[("size_bytes", "descending")]
    )
    return pc.take(table, sorted_indices)
