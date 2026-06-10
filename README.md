## shopvac

Get prefix sizes from cloud storage buckets (S3 / GCS) for cleanups and data audits. Supports flat (top-level only) and tree modes that descend N prefix levels.

### Install

```bash
uv tool install git+https://github.com/carbonplan/shopvac
```

### Usage

**Single bucket:**

```bash
shopvac --bucket-url s3://my-bucket --min-size-gb 5
```

**Multiple buckets from a file** (one URL per line, `#` lines ignored):

```bash
shopvac --bucket-file buckets.txt --min-size-gb 1
```

**GCS bucket:**

```bash
shopvac --bucket-url gs://my-gcs-bucket --min-size-gb 1
```

**Send results to Slack:**

```bash
shopvac --bucket-url s3://my-bucket --send-slack --slack-webhook-url "https://hooks.slack.com/..."
```

**Rich table output:**

```bash
shopvac --bucket-url s3://my-bucket --rich-table
```

**Tree mode** (descend 3 prefix levels, show subtrees ≥ 1 GB):

```bash
shopvac --bucket-url s3://my-bucket --depth 3 --min-size-gb 1 --rich-table
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-b`, `--bucket-url` | — | Bucket URL(s), repeatable |
| `-B`, `--bucket-file` | — | File with one bucket URL per line |
| `-d`, `--depth` | 1 | Prefix levels to descend; 1 = flat, >1 = tree |
| `--min-size-gb` | 10.0 | Exclude prefixes smaller than this (applies at every depth) |
| `--rich-table` | off | Display as rich table instead of plain text |
| `--send-slack` | off | Post results to Slack |
| `--slack-webhook-url` | — | Slack incoming webhook URL |
| `--timeout-per-prefix` | 3600 | Seconds before a prefix scan times out |
| `--fail-fast` | off | Stop on first error instead of continuing |
| `--max-concurrent-buckets` | 5 | Concurrent bucket scans |

### AWS options

Credentials follow the standard AWS credential chain (env vars, `~/.aws/credentials`, IAM role). Override with:

| Flag | Description |
|------|-------------|
| `--aws-profile` | Profile name from `~/.aws/credentials` |
| `--aws-region` | Override region |
| `--aws-access-key-id` | Explicit key ID |
| `--aws-secret-access-key` | Explicit secret |
| `--aws-session-token` | Session token for temporary credentials |
| `--skip-signature` | Skip signing (public buckets) |

### GCS options

| Flag | Description |
|------|-------------|
| `--gcp-service-account-path` | Path to service account JSON |
| `--gcp-project-id` | GCP project ID |

Application Default Credentials are used when no flags are provided.
