import pytest
import boto3
from moto.server import ThreadedMotoServer


MOTO_PORT = 5555
MOTO_ENDPOINT = f"http://localhost:{MOTO_PORT}"
TEST_BUCKET = "test-shopvac"
TEST_REGION = "us-east-1"

# Sizes in bytes — kept small for test performance.
# Tests use min_size_gb values scaled to these byte counts.
PREFIX_A_SIZE = 6000  # "large": two objects 3000+3000
PREFIX_B_SIZE = 2000  # "medium": one object
PREFIX_C_SIZE = 100  # "small": intentionally below filter threshold in some tests

# min_size_gb that includes A+B but excludes C
MIN_SIZE_INCLUDE_AB = PREFIX_C_SIZE / 1024**3 + 1e-12
# min_size_gb that includes all three
MIN_SIZE_INCLUDE_ALL = 0.0


@pytest.fixture(scope="session")
def moto_server():
    server = ThreadedMotoServer(port=MOTO_PORT)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def s3_client(moto_server):
    return boto3.client(
        "s3",
        endpoint_url=MOTO_ENDPOINT,
        region_name=TEST_REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


NESTED_BUCKET = "test-shopvac-nested"

# Per-prefix totals for the nested layout below
PROJ_A_SIZE = 2550  # model-1 (2000) + model-2 (500) + readme.txt (50)
PROJ_A_MODEL_1_SIZE = 2000
PROJ_A_MODEL_2_SIZE = 500
PROJ_B_SIZE = 4300  # data-v1 (4000) + data-v2 (300)
PROJ_B_DATA_V1_SIZE = 4000
PROJ_B_DATA_V1_SUB_SIZE = 2000
PROJ_B_DATA_V2_SIZE = 300


@pytest.fixture
def seeded_bucket(s3_client):
    """Bucket with known prefix/size layout."""
    s3_client.create_bucket(Bucket=TEST_BUCKET)

    objects = [
        ("prefix-a/file1.bin", 3000),
        ("prefix-a/file2.bin", 3000),
        ("prefix-b/file1.bin", 2000),
        ("prefix-c/file1.bin", 100),
    ]
    for key, size in objects:
        s3_client.put_object(Bucket=TEST_BUCKET, Key=key, Body=b"\x00" * size)

    yield f"s3://{TEST_BUCKET}"

    # cleanup so fixture is reusable across test runs
    for key, _ in objects:
        s3_client.delete_object(Bucket=TEST_BUCKET, Key=key)
    s3_client.delete_bucket(Bucket=TEST_BUCKET)


@pytest.fixture
def seeded_bucket_nested(s3_client):
    """Bucket with multi-level prefix layout for tree-mode tests."""
    s3_client.create_bucket(Bucket=NESTED_BUCKET)

    objects = [
        ("proj-a/model-1/f1.bin", 1000),
        ("proj-a/model-1/f2.bin", 1000),
        ("proj-a/model-2/f1.bin", 500),
        ("proj-a/readme.txt", 50),
        ("proj-b/data-v1/c1.bin", 2000),
        ("proj-b/data-v1/sub/c2.bin", 2000),
        ("proj-b/data-v2/c1.bin", 300),
    ]
    for key, size in objects:
        s3_client.put_object(Bucket=NESTED_BUCKET, Key=key, Body=b"\x00" * size)

    yield f"s3://{NESTED_BUCKET}"

    for key, _ in objects:
        s3_client.delete_object(Bucket=NESTED_BUCKET, Key=key)
    s3_client.delete_bucket(Bucket=NESTED_BUCKET)
