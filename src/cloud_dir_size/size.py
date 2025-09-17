import asyncio
from typing import List, Tuple, Any

import obstore as obs
from obstore.store import from_url
import pyarrow as pa
import pyarrow.compute as pc
from humanize import naturalsize


async def get_prefix_size(store: obs.store, prefix: str) -> int:
    """Calculate total size for a prefix in bytes."""
    print(f"  Processing: {prefix}")

    stream = obs.list(store, prefix=prefix, return_arrow=True)
    total_size = 0

    async for batch in stream:
        pyarrow_batch = pa.record_batch(batch)
        if len(pyarrow_batch) > 0:
            sizes_column = pyarrow_batch["size"]
            batch_total = pc.sum(sizes_column).as_py()
            total_size += batch_total

    print(f"    Completed {prefix}: {naturalsize(total_size)}")
    return total_size


async def get_top_level_sizes(bucket_url: str, min_size_gb: float = 1.0) -> pa.Table:
    """
    Return a filtered and sorted Arrow table of prefixes with sizes >= min_size_gb.
    """
    store = from_url(bucket_url, client_options={"timeout": "600s"})

    result: dict[str, Any] = await obs.list_with_delimiter_async(store, prefix=None)
    top_level_prefixes: List[str] = result["common_prefixes"]

    print(f"Found {len(top_level_prefixes)} prefixes to analyze...")
    print("Processing all prefixes concurrently...")

    tasks = [get_prefix_size(store, prefix) for prefix in top_level_prefixes]
    sizes: List[int] = await asyncio.gather(*tasks)

    filtered_data: List[Tuple[str, int]] = []
    for prefix, size in zip(top_level_prefixes, sizes):
        size_gb = size / (1024**3)
        if size_gb >= min_size_gb:
            filtered_data.append((prefix, size))

    print(f"Filtered to {len(filtered_data)} prefixes >= {min_size_gb} GB")

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
