#!/usr/bin/env python3
"""Download AMFI's NAVAll.txt, validate it, and upload the untouched bytes to S3.

Stage 1 extractor. Design rules (from the week-1 file notes):
  * The S3 key date comes from the dates INSIDE the file, not from the clock.
  * "We already have this date" is a normal outcome (exit 0), not an error.
  * Raw bytes are uploaded unchanged. Parsing happens later, in Snowflake.

Usage:
  python extractor/extract_navall.py --dry-run             # download + validate only, no AWS needed
  python extractor/extract_navall.py --file NAVAll.txt     # use a local copy (if AMFI blocks the script)
  python extractor/extract_navall.py                       # download, validate, upload to S3

Config comes from environment variables or a .env file (never commit it):
  S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
  optional: AMFI_NAVALL_URL, MIN_DATA_ROWS

Exit codes: 0 = uploaded or already present, 2 = file failed validation, 3 = download failed.
"""
import argparse
import hashlib
import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # .env support is optional
    pass

AMFI_URL = os.getenv("AMFI_NAVALL_URL", "https://www.amfiindia.com/spages/NAVAll.txt")
S3_PREFIX = "raw/navall"
EXPECTED_FIELDS = 8  # Scheme Code;ISIN Payout/Growth;ISIN Reinvest;Scheme Name;Plan;Option;NAV;Date
DATE_FORMAT = "%d-%b-%Y"  # e.g. 09-Oct-2026
USER_AGENT = "Mozilla/5.0 (amfi-nav-pipeline; learning project)"


class ValidationError(Exception):
    pass


def decode(raw: bytes):
    """Decode for inspection only. The bytes we upload are never modified."""
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def inspect(raw: bytes, min_rows: int) -> dict:
    text, encoding = decode(raw)
    lines = text.splitlines()
    if not lines:
        raise ValidationError("file is empty")

    header = lines[0].lstrip("﻿")
    if not header.startswith("Scheme Code;") or header.count(";") != EXPECTED_FIELDS - 1:
        raise ValidationError(f"unexpected header line: {header[:150]!r}")

    dates = set()
    data_rows = odd_rows = blank_lines = 0
    for line in lines[1:]:
        if not line.strip():
            blank_lines += 1
            continue
        parts = line.split(";")
        if not parts[0].strip().isdigit():
            continue  # category line, fund-house line, or anything else that is not data
        if len(parts) != EXPECTED_FIELDS:
            odd_rows += 1  # looks like data but has the wrong shape; Stage 2 will quarantine these
            continue
        try:
            dates.add(datetime.strptime(parts[-1].strip(), DATE_FORMAT).date())
        except ValueError:
            odd_rows += 1
            continue
        data_rows += 1

    if not dates:
        raise ValidationError("no parseable dates found in any data row")
    if data_rows < min_rows:
        raise ValidationError(
            f"only {data_rows} data rows (floor is {min_rows}); partial download? "
            "Tune MIN_DATA_ROWS using the row count from your file notes."
        )

    return {
        "encoding": encoding,
        "has_bom": raw.startswith(b"\xef\xbb\xbf"),
        "possible_double_encoding": text.count("â€"),  # 'â€' sequences, e.g. 'â€™'
        "total_lines": len(lines),
        "blank_lines": blank_lines,
        "data_rows": data_rows,
        "odd_rows": odd_rows,
        "distinct_dates": len(dates),
        "file_date": max(dates),
    }


def download(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def upload(raw: bytes, bucket: str, key: str, metadata: dict) -> bool:
    """Return True if uploaded, False if the key already exists."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError as err:
        if err.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise  # a 403 here usually means the IAM policy is missing s3:ListBucket
    s3.put_object(Bucket=bucket, Key=key, Body=raw, ContentType="text/plain", Metadata=metadata)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="use a local file instead of downloading")
    ap.add_argument("--dry-run", action="store_true", help="validate only; do not upload")
    ap.add_argument("--min-rows", type=int, default=int(os.getenv("MIN_DATA_ROWS", "1000")))
    args = ap.parse_args()

    try:
        if args.file:
            with open(args.file, "rb") as fh:
                raw = fh.read()
        else:
            raw = download(AMFI_URL)
    except Exception as err:  # noqa: BLE001 - any failure here is a download failure
        print(f"DOWNLOAD FAILED: {err}", file=sys.stderr)
        return 3

    try:
        info = inspect(raw, args.min_rows)
    except ValidationError as err:
        print(f"VALIDATION FAILED: {err}", file=sys.stderr)
        return 2

    print("File report")
    for name, value in info.items():
        print(f"  {name}: {value}")
    if info["possible_double_encoding"]:
        print("  WARNING: text looks double-encoded (â€ sequences). Check before loading.")
    if info["encoding"] != "utf-8":
        print("  WARNING: not valid UTF-8. Set ENCODING = 'WINDOWS1252' in the Snowflake file format.")
    if info["odd_rows"]:
        print(f"  NOTE: {info['odd_rows']} data-looking lines have the wrong shape (kept in raw).")

    key = f"{S3_PREFIX}/{info['file_date'].isoformat()}/NAVAll.txt"
    if args.dry_run:
        print(f"DRY RUN: would upload to s3://<bucket>/{key}")
        return 0

    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        print("S3_BUCKET is not set (use .env or an environment variable)", file=sys.stderr)
        return 2

    metadata = {"sha256": hashlib.sha256(raw).hexdigest(), "source": "file" if args.file else AMFI_URL[:200]}
    if upload(raw, bucket, key, metadata):
        print(f"UPLOADED s3://{bucket}/{key}")
    else:
        print(f"ALREADY PRESENT s3://{bucket}/{key} (nothing to do)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
