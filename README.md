# AMFI NAV Pipeline

An end-to-end data pipeline on India's daily mutual fund NAV data, built in public.

Every business day, AMFI (the Association of Mutual Funds in India) publishes the NAV (Net Asset Value) of every mutual fund scheme in India as one text file, usually between 7 and 11 PM IST. This project picks that file up automatically, loads it into Snowflake, models it into a warehouse that remembers history (renames, recategorisations), tests itself on every change, and serves it through a dashboard and, later, an AI agent that answers questions in plain English.

**Why this data?** It is real, it is messy, it arrives every day, and the things it describes change over time. A one-off tutorial CSV has none of those problems.

**Stack:** Snowflake · dbt · Airflow · AWS S3 · GitHub Actions · Streamlit · Snowflake Cortex

## Status

This is a work in progress, updated as each stage ships. Progress is posted on LinkedIn every Monday (goals) and Thursday (what actually happened).

| Stage | What | Status |
|---|---|---|
| 0 | Foundations: study the file, load it by hand, build the first tables | Done |
| 1 | Ingestion: extractor, S3, Snowpipe auto-ingest into a raw table | In progress |
| 2 | Staging: parse raw lines into typed tables, quarantine bad rows | Planned |
| 3 | Modeling: dbt star schema, SCD2 history, tests, docs | Planned |
| 4 | Orchestration: Airflow DAG with retries, alerts and backfill | Planned |
| 5 | Serving: Dynamic Tables for returns and rankings, Streamlit app | Planned |
| 6 | Hardening: roles, masking, row access, cost report, CI/CD | Planned |
| 7 | AI layer: Cortex Analyst, Cortex Search over SEBI documents, Cortex Agent | Planned |
| 8 | Packaging: final diagrams, demo video, retrospective | Planned |

## Architecture (planned)

```
AMFI NAVAll.txt
      |
      v
Python extractor ---> S3 (raw files) ---> Snowpipe ---> RAW
                                                         |
                                         streams + tasks |
                                                         v
                                                      STAGING
                                                         |
                                                 dbt     |
                                                         v
                                                       MARTS  (star schema, SCD2)
                                                         |
                                                         v
                                        Dynamic Tables ---> Streamlit app
                                                         \-> Cortex Analyst / Search / Agent

Airflow runs the extractor and dbt. GitHub Actions checks every change.
```

A proper diagram will be added once the data model settles.

## The source file

- Semicolon-delimited, with a header row of 8 columns: scheme code, two ISIN columns, scheme name, plan, option, NAV and date.
- Not every line is data. Category lines, fund-house lines and blank lines are mixed in with the data rows.
- Each fund appears several times, because plan (Direct or Regular) and option (Growth or IDCW) each get their own scheme code.
- Dates look like `09-Oct-2026`.
- Some text contains characters that come out garbled if the file is read with the wrong encoding.

## Design decisions

1. **Raw keeps every line untouched.** The file mixes line types, so the loader stores one line per row with its file name and line number, and parsing happens later in Snowflake.
2. **The S3 key date comes from inside the file, not from the clock.** A late publish can never be filed under the wrong day.
3. **"No new data" is a normal outcome, not an error.** Weekends and holidays produce no new file, and the extractor treats a file it already has as a success.
4. **Snowflake reads S3 through a storage integration, not access keys.** No secret is pasted into Snowflake, and access can be revoked by editing one trust policy.
5. **History will be kept with SCD2** (a new row per change, with valid-from and valid-to dates), built with dbt snapshots.

## Repository layout

```
extractor/    Python: download, validate and upload the file to S3
  sample/     a small trimmed sample for tests
sql/          Snowflake setup and ingestion scripts (placeholders, no real account values)
docs/         runbooks and diagrams
notes/        learning notes, one file per week
```

## Running the extractor

Requires Python 3 and, for uploads, an AWS account with a bucket (see `docs/week2-ingestion-runbook.md` for the full AWS and Snowflake setup).

```bash
python3 -m pip install -r requirements.txt

# Download and validate only; needs no AWS:
python3 extractor/extract_navall.py --dry-run

# Download, validate, upload to S3:
cp .env.example .env     # then fill in your values
python3 extractor/extract_navall.py
```

Configuration lives in `.env` (never committed). See `.env.example` for the variable names.

## Security

No credentials are committed. `.env` is git-ignored, and the SQL scripts use placeholders such as `<BUCKET>` and `<AWS_ACCOUNT_ID>` that you replace locally.

## Build in public

This project is built in public as a learning exercise. Posts and write-ups:

- Week 1: *link to follow*
- Week 2: *link to follow*

Feedback and suggestions are welcome. Open an issue or leave a comment on the posts.
