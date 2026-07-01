import pyarrow as pa

from shopvac.size import get_prefix_size, get_top_level_sizes
from tests.conftest import (
    MOTO_ENDPOINT,
    TEST_REGION,
    PREFIX_A_SIZE,
    PREFIX_B_SIZE,
    PREFIX_C_SIZE,
    MIN_SIZE_INCLUDE_AB,
    MIN_SIZE_INCLUDE_ALL,
    PROJ_A_SIZE,
    PROJ_A_MODEL_1_SIZE,
    PROJ_A_MODEL_2_SIZE,
    PROJ_B_SIZE,
    PROJ_B_DATA_V1_SIZE,
    PROJ_B_DATA_V1_SUB_SIZE,
)

S3_KWARGS = dict(
    aws_access_key_id="testing",
    aws_secret_access_key="testing",
    aws_region=TEST_REGION,
    aws_endpoint=MOTO_ENDPOINT,
)


async def test_top_level_sizes_returns_table(seeded_bucket):
    table = await get_top_level_sizes(
        seeded_bucket, min_size_gb=MIN_SIZE_INCLUDE_ALL, **S3_KWARGS
    )
    assert isinstance(table, pa.Table)
    assert set(table.schema.names) == {
        "prefix",
        "size_bytes",
        "size_formatted",
        "skipped",
    }
    assert table["skipped"].to_pylist() == [False] * table.num_rows


async def test_top_level_sizes_correct_counts(seeded_bucket):
    table = await get_top_level_sizes(
        seeded_bucket, min_size_gb=MIN_SIZE_INCLUDE_ALL, **S3_KWARGS
    )
    assert table.num_rows == 3


async def test_top_level_sizes_sorted_descending(seeded_bucket):
    table = await get_top_level_sizes(
        seeded_bucket, min_size_gb=MIN_SIZE_INCLUDE_ALL, **S3_KWARGS
    )
    sizes = table["size_bytes"].to_pylist()
    assert sizes == sorted(sizes, reverse=True)


async def test_top_level_sizes_correct_aggregation(seeded_bucket):
    table = await get_top_level_sizes(
        seeded_bucket, min_size_gb=MIN_SIZE_INCLUDE_ALL, **S3_KWARGS
    )
    # obstore strips trailing slash from common_prefixes
    size_map = dict(zip(table["prefix"].to_pylist(), table["size_bytes"].to_pylist()))
    assert size_map["prefix-a"] == PREFIX_A_SIZE
    assert size_map["prefix-b"] == PREFIX_B_SIZE
    assert size_map["prefix-c"] == PREFIX_C_SIZE


async def test_min_size_filter(seeded_bucket):
    table = await get_top_level_sizes(
        seeded_bucket, min_size_gb=MIN_SIZE_INCLUDE_AB, **S3_KWARGS
    )
    prefixes = table["prefix"].to_pylist()
    assert "prefix-c" not in prefixes
    assert "prefix-a" in prefixes
    assert "prefix-b" in prefixes


async def test_get_prefix_size(seeded_bucket, moto_server):
    from obstore.store import from_url

    store = from_url(
        seeded_bucket,
        access_key_id="testing",
        secret_access_key="testing",
        region=TEST_REGION,
        endpoint=MOTO_ENDPOINT,
        client_options={"allow_http": True},
    )
    prefix, size, sizes, skipped, invalid_paths = await get_prefix_size(
        store, "prefix-a/"
    )
    assert prefix == "prefix-a/"
    assert size == PREFIX_A_SIZE
    assert sizes == {"prefix-a": PREFIX_A_SIZE}
    assert skipped == 0
    assert invalid_paths == []


async def test_get_prefix_size_with_depth(seeded_bucket_nested, moto_server):
    from obstore.store import from_url

    store = from_url(
        seeded_bucket_nested,
        access_key_id="testing",
        secret_access_key="testing",
        region=TEST_REGION,
        endpoint=MOTO_ENDPOINT,
        client_options={"allow_http": True},
    )
    prefix, total, sizes, skipped, invalid_paths = await get_prefix_size(
        store, "proj-a/", max_depth=2
    )
    assert total == PROJ_A_SIZE
    assert sizes["proj-a"] == PROJ_A_SIZE
    assert sizes["proj-a/model-1"] == PROJ_A_MODEL_1_SIZE
    assert sizes["proj-a/model-2"] == PROJ_A_MODEL_2_SIZE
    # objects directly at a level are not sub-prefixes
    assert "proj-a/readme.txt" not in sizes


async def test_tree_mode_depth_2(seeded_bucket_nested):
    table = await get_top_level_sizes(
        seeded_bucket_nested, min_size_gb=MIN_SIZE_INCLUDE_ALL, depth=2, **S3_KWARGS
    )
    assert set(table.schema.names) == {
        "prefix",
        "size_bytes",
        "size_formatted",
        "depth",
        "skipped",
    }

    size_map = dict(zip(table["prefix"].to_pylist(), table["size_bytes"].to_pylist()))
    assert size_map["proj-a"] == PROJ_A_SIZE
    assert size_map["proj-a/model-1"] == PROJ_A_MODEL_1_SIZE
    assert size_map["proj-b/data-v1"] == PROJ_B_DATA_V1_SIZE
    assert "proj-b/data-v1/sub" not in size_map

    # parents precede children; top level sorted by size desc
    prefixes = table["prefix"].to_pylist()
    assert prefixes[0] == "proj-b"
    assert prefixes.index("proj-b") < prefixes.index("proj-b/data-v1")
    assert prefixes.index("proj-a") < prefixes.index("proj-a/model-1")


async def test_tree_mode_depth_3(seeded_bucket_nested):
    table = await get_top_level_sizes(
        seeded_bucket_nested, min_size_gb=MIN_SIZE_INCLUDE_ALL, depth=3, **S3_KWARGS
    )
    size_map = dict(zip(table["prefix"].to_pylist(), table["size_bytes"].to_pylist()))
    assert size_map["proj-b/data-v1/sub"] == PROJ_B_DATA_V1_SUB_SIZE


async def test_tree_mode_threshold_prunes_children(seeded_bucket_nested):
    # threshold between 500 and 2000 bytes: prunes model-2 and data-v2,
    # keeps parents (their totals still include pruned children)
    threshold_gb = 600 / 1024**3
    table = await get_top_level_sizes(
        seeded_bucket_nested, min_size_gb=threshold_gb, depth=2, **S3_KWARGS
    )
    size_map = dict(zip(table["prefix"].to_pylist(), table["size_bytes"].to_pylist()))
    assert "proj-a/model-2" not in size_map
    assert "proj-b/data-v2" not in size_map
    assert size_map["proj-a"] == PROJ_A_SIZE
    assert size_map["proj-b"] == PROJ_B_SIZE


async def test_depth_1_schema_unchanged(seeded_bucket_nested):
    table = await get_top_level_sizes(
        seeded_bucket_nested, min_size_gb=MIN_SIZE_INCLUDE_ALL, depth=1, **S3_KWARGS
    )
    assert set(table.schema.names) == {
        "prefix",
        "size_bytes",
        "size_formatted",
        "skipped",
    }
    size_map = dict(zip(table["prefix"].to_pylist(), table["size_bytes"].to_pylist()))
    assert size_map == {"proj-a": PROJ_A_SIZE, "proj-b": PROJ_B_SIZE}


async def test_continue_on_error_skips_failures(seeded_bucket, monkeypatch):
    import obstore as obs

    original_list = obs.list

    call_count = 0

    def flaky_list(store, *, prefix=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if prefix and "prefix-b" in prefix:
            raise RuntimeError("simulated failure")
        return original_list(store, prefix=prefix, **kwargs)

    monkeypatch.setattr(obs, "list", flaky_list)

    table = await get_top_level_sizes(
        seeded_bucket,
        min_size_gb=MIN_SIZE_INCLUDE_ALL,
        continue_on_error=True,
        **S3_KWARGS,
    )
    prefixes = table["prefix"].to_pylist()
    assert "prefix-b" not in prefixes
    assert "prefix-a" in prefixes
