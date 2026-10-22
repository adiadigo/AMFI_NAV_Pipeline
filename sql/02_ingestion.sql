-- Stage 1: S3 -> Snowflake RAW via Snowpipe auto-ingest.
-- Run the sections in order; the runbook (docs/week2-ingestion-runbook.md) says when to switch to AWS.
-- Placeholders to replace: <BUCKET>, <AWS_ACCOUNT_ID>.
-- Assumes database AMFI_NAV and schema RAW. If your week-1 names differ, find-and-replace.
-- Re-runnable: every CREATE uses IF NOT EXISTS.

------------------------------------------------------------------------------
-- 1. Storage integration (one-time; needs ACCOUNTADMIN)
------------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;

CREATE STORAGE INTEGRATION IF NOT EXISTS s3_amfi_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::<AWS_ACCOUNT_ID>:role/snowflake-amfi-s3-role'
  STORAGE_ALLOWED_LOCATIONS = ('s3://<BUCKET>/raw/navall/');

-- Copy STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID from this output into the
-- AWS role's trust policy (runbook step C), then continue.
DESC INTEGRATION s3_amfi_int;

------------------------------------------------------------------------------
-- 2. File format, stage, raw table
------------------------------------------------------------------------------
USE DATABASE AMFI_NAV;
USE SCHEMA RAW;

-- One column per line, nothing interpreted. The file mixes header, category,
-- fund-house and data lines, so Stage 2 does the parsing, not the loader.
-- If the extractor reported "not valid UTF-8", change ENCODING to 'WINDOWS1252'.
CREATE FILE FORMAT IF NOT EXISTS ff_navall_lines
  TYPE = CSV
  FIELD_DELIMITER = NONE
  ESCAPE_UNENCLOSED_FIELD = NONE
  FIELD_OPTIONALLY_ENCLOSED_BY = NONE
  SKIP_BLANK_LINES = FALSE
  TRIM_SPACE = FALSE
  ENCODING = 'UTF8';

CREATE STAGE IF NOT EXISTS stg_navall
  URL = 's3://<BUCKET>/raw/navall/'
  STORAGE_INTEGRATION = s3_amfi_int
  FILE_FORMAT = ff_navall_lines;

-- Permission test: errors if the IAM trust or policy is wrong; empty result is fine.
LIST @stg_navall;

CREATE TABLE IF NOT EXISTS navall_lines (
  line_text    VARCHAR,
  source_file  VARCHAR,
  file_row_num NUMBER,
  loaded_at    TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

------------------------------------------------------------------------------
-- 3. Format check (run AFTER the extractor has uploaded the first real file)
------------------------------------------------------------------------------
-- Row 1 should be the header. Look for the apostrophe in "Children's Fund":
-- it should show as ' and NOT as the garbled three-character sequence.
SELECT t.$1 AS line_text, METADATA$FILENAME AS source_file, METADATA$FILE_ROW_NUMBER AS file_row_num
FROM @stg_navall t
LIMIT 30;

-- Compare with total_lines from the extractor's file report. A mismatch usually means
-- blank lines or line endings are being handled differently than you assumed.
SELECT COUNT(*) AS lines_in_stage FROM @stg_navall t;

------------------------------------------------------------------------------
-- 4. The pipe
------------------------------------------------------------------------------
CREATE PIPE IF NOT EXISTS pipe_navall
  AUTO_INGEST = TRUE
AS
COPY INTO navall_lines (line_text, source_file, file_row_num)
FROM (
  SELECT t.$1, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
  FROM @stg_navall t
);

-- Copy the notification_channel value (an SQS ARN) into the S3 event notification
-- (runbook step G).
SHOW PIPES LIKE 'pipe_navall';

-- Load files that were already in the stage before the pipe existed (last 7 days only).
ALTER PIPE pipe_navall REFRESH;

------------------------------------------------------------------------------
-- 5. Is it working?
------------------------------------------------------------------------------
SELECT SYSTEM$PIPE_STATUS('AMFI_NAV.RAW.pipe_navall');

SELECT *
FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY(
  TABLE_NAME => 'NAVALL_LINES',
  START_TIME => DATEADD(hour, -3, CURRENT_TIMESTAMP())));

SELECT source_file, COUNT(*) AS line_count
FROM navall_lines
GROUP BY source_file;

-- Clean up after the tiny pipe test (runbook step G):
-- DELETE FROM navall_lines WHERE source_file LIKE '%_pipe_test%';
