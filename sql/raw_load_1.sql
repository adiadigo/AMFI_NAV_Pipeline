Create schema AMFI_NAV.RAW;

CREATE OR REPLACE FILE FORMAT raw.ff_lines
  TYPE = CSV
  FIELD_DELIMITER = NONE
  SKIP_HEADER = 0
  SKIP_BLANK_LINES = FALSE
  FIELD_OPTIONALLY_ENCLOSED_BY = NONE
  ENCODING = 'UTF8';

CREATE OR REPLACE STAGE raw.nav_stage FILE_FORMAT = raw.ff_lines;

CREATE OR REPLACE TABLE raw.nav_lines (
  file_name        VARCHAR,
  line_number      NUMBER,
  raw_line         VARCHAR,
  file_modified_at TIMESTAMP_NTZ,
  loaded_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

LIST @raw.nav_stage;

COPY INTO raw.nav_lines (file_name, line_number, raw_line, file_modified_at)
FROM (
  SELECT METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, $1, METADATA$FILE_LAST_MODIFIED
  FROM @raw.nav_stage
);

SELECT COUNT(*) FROM raw.nav_lines;
SELECT file_name, line_number, COUNT(*) FROM raw.nav_lines GROUP BY 1,2 HAVING COUNT(*) > 1;
SELECT MIN(line_number), MAX(line_number), COUNT(*) FROM raw.nav_lines;
SELECT COUNT(*) FROM raw.nav_lines WHERE ENDSWITH(raw_line, CHR(13));
SELECT COUNT(*) FROM raw.nav_lines WHERE REGEXP_LIKE(raw_line, '^[0-9]+;.*') AND REGEXP_COUNT(raw_line, ';') = 7;
SELECT line_number, raw_line FROM raw.nav_lines WHERE raw_line RLIKE '.*[^\\x00-\\x7F].*' LIMIT 20;
