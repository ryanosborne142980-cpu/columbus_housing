# Tests

Run from the project root:

```
python -m pytest -q
```

The database tests need a SQL Server instance (`localhost` by default, or set
`COLUMBUS_HOUSING_SERVER`) and ODBC Driver 18 for SQL Server. The three parsing tests run without
it. Database tests use their own database, `columbus_housing_test`, which is created on first run
and emptied before every test. The real `columbus_housing` database is never touched.

## Sample files (`fixtures/`)

These are small hand-made files shaped like each source, not copies of real downloads. They show the
code handles the format we expect; they do not prove the live sources still look like this.

| File | Stands in for | Built to catch |
|---|---|---|
| `whsr.html` | A Franklin County weekly residential sales report page | Sales split across two ZIP tables, plus the county's own summary numbers |
| `wcsr.html` | A Franklin County weekly commercial sales report page | A ZIP given only in the table caption, and a week that runs from December into January |
| `delaware_sales.csv` | A Delaware County sales export | Owner mailing addresses in a different ZIP, a commercial sale, and a row with no sale date |
| `zillow_county.csv`, `zillow_zip.csv` | Zillow's monthly ZHVI files | Same-named counties in other states, a blank month |
| `redfin_weekly.tsv` | Redfin's weekly market file | Look-alike regions that must be dropped: Columbus, GA; Cleveland, OH; Delaware County, PA |

## What each test checks

### Reading Franklin County report pages

- **test_parse_residential**: Reads the sample residential report and checks that it finds the right
  week, publish date, county summary (6 sales, $300,000 median), all 6 sales, and the correct ZIP for
  each. It spot-checks the first sale field by field.
- **test_parse_commercial_caption_and_year_wrap**: Reads the sample commercial report. Checks that it is
  recognized as commercial, that a week from Dec 26 to Jan 1 gets the right year on each end, and that
  the ZIP is picked up from the table caption.
- **test_parse_period_month_abbreviations**: Checks that report weeks written as "Sept.", "Sep." or
  "September" all read correctly, that older pages with no year ("Apr. 3–9") take the year from the
  publish date, that dashed dates ("04-03-2026") read, and that an unrecognizable month name leaves the week blank instead
  of stopping the run.

### Saving to the database

- **test_load_idempotent_and_validation**: Saves the sample residential report twice. The first save
  adds 6 sales; the second adds none. It also checks that the parsed sale count matches the county's
  own count, which is how parser drift gets spotted on live data.

- **test_raw_page_dedupes_and_reparse_loads**: Saves a report page three times. An identical copy adds
  nothing; a changed copy is kept as a revision. Re-parsing from the saved pages loads 6 sales the first
  time and none the second.

- **test_load_url_saves_page_and_loads_once**: With a fake network, loads one report by URL, saves its page, adds
  nothing on a second run, and refuses a URL outside the county's reports.

### Finding report pages (offline)

- **test_discover_guesses_past_listing_and_stops_after_misses**: Fakes the county site. Checks that
  discovery reads the listing once (no `&page=` requests, which the site ignores), drops a commercial
  link, finds older weeks by guessing addresses (including one published a day early), and stops after
  the set number of weeks in a row with no page.

### Summary views

- **test_clean_view_drops_nominal_and_collapses_multiparcel**: Checks the cleaning rules. A $10 transfer
  is dropped as not a real sale. One sale recorded on two parcels counts once. The weekly median of two
  sales is the average of the two, and the week starts on Monday.
- **test_rolling4_pools_sales_and_computes_yoy**: Builds four weeks of sales this year and the same four
  weeks last year. Checks that the rolling 4-week median uses all 12 sales together (not an average of
  weekly medians) and that the year-over-year change is right (19.9%).
- **test_rolling4_keeps_counties_separate**: Puts Franklin and Delaware sales in the same week and checks
  each county gets its own median. It also checks that the same parcel number can exist in two counties.

### County files (Delaware sample; Licking uses the same loader but has no sample)

- **test_county_file_maps_columns_and_filters_residential**: Loads the sample Delaware file. Checks that
  columns are found by header name, the commercial sale and the dateless row are dropped, and the ZIP
  comes from the property address, not the owner's mailing address. Loading the file a second time
  adds nothing.
- **test_county_file_missing_columns_lists_headers**: Gives the loader a file with no sale date or sale
  price column and checks it fails with an error naming both missing fields and listing the file's
  headers, so you know which header to add.

### Redfin

- **test_redfin_keeps_columbus_metro_and_three_counties**: Loads the sample Redfin file and checks that
  only the Columbus metro rows and the Franklin, Delaware and Licking county rows (all Ohio) are kept.
- **test_redfin_gzip_read_in_chunks**: Loads a gzipped copy with no `.gz` in the name, read 3 rows at a
  time, and checks the same 5 rows come through with numbers intact. Real files cover the whole US, so
  they are filtered chunk by chunk instead of loaded whole.

### Polite fetching (offline, fake network)

- **test_http_blocked_robots_means_disallow**: A robots.txt that answers 403 blocks the site. One that
  answers 503 blocks for now but is checked again on the next request.
- **test_http_crawl_delay_and_retry_after**: A site with `Crawl-delay: 10` is fetched at most every 10
  seconds, and a 429 with `Retry-After: 7` waits 7 seconds and retries.

### Zillow

- **test_zillow_keeps_three_ohio_counties_and_their_zips**: Loads sample Zillow county and ZIP files.
  Keeps only the Ohio Franklin, Delaware and Licking rows and their ZIPs (drops Franklin County, PA, a
  Massachusetts ZIP in a "Franklin County", Cuyahoga and Columbus, GA). Checks year-over-year (7.5%),
  that a reload replaces rather than duplicates, and that each load logs the Zillow attribution.
- **test_zillow_skips_download_when_file_unchanged**: With a fake network, a second load sees the same
  Last-Modified date and skips the download.

### Run health

- **test_run_problems_flags_runs_that_look_finished_but_failed**: A run counts as failed if pages couldn't be fetched,
  discovery found nothing, or the newest week is over 14 days old. A week with nothing new to load doesn't.

### Data quality

- **test_quality_passes_clean_data**: A good report and Zillow's counties trip no failing rule.
- **test_quality_failing_rule_catches_bad_data**: Breaks the data 13 ways, one at a time, and checks the matching failing
  rule fires, so a rule that can never fire doesn't pass unnoticed.
- **test_quality_warning_rule_fires_when_broken**, **test_quality_cadence_and_duplicate_weeks**,
  **test_quality_volume_dip_compares_newest_week_with_recent_ones**, **test_quality_zillow_jump_warns**: Do the same for
  warnings. **test_quality_warning_alone_does_not_fail** checks a warning doesn't fail the check.
- **test_quality_known_exception_is_left_out**: A checked exception stops being reported.
- **test_quality_redfin_only_checked_once_loaded**, **test_quality_redfin_date_column_that_isnt_a_date**: Redfin rules
  skip a database with no Redfin table, then catch an unexpected region and a column holding 1970 dates.
- **test_zillow_refuses_a_file_much_smaller_than_what_is_loaded**: A cut-off file raises an error and the loaded rows
  stay.
- **test_county_file_fails_when_land_use_filter_keeps_nothing**: A wrong land use column raises an error instead of
  quietly loading nothing.
- **test_weekly_skips_databricks_only_when_the_data_check_fails**: With fake commands, a failed check skips the Databricks
  steps but not the backup.
- **test_run_check_exits_nonzero_on_a_failed_rule_but_not_a_warning**: `run.py check` exits 0 on clean data and on a
  warning, and 1 on a failure.
- **test_reconcile_reports_only_real_differences**: Numbers and dates that match as text aren't reported, and a different
  count is.

### Governance documents (`test_governance.py`, no database needed)

- **test_schema_parser_reads_a_known_table**: Checks the test's own reader of `sql/schema.sql` on two known columns and
  the table count, so the comparison below can't pass by reading nothing.
- **test_dictionary_matches_sql_server_schema**: Every column in `sql/schema.sql` is in the data dictionary with the
  same type, and the dictionary has no column the schema lacks.
- **test_dictionary_silver_tables_exist_in_the_pipeline**: The silver tables in the dictionary are the ones `silver.py`
  defines. It checks table names only, not their columns.
- **test_dictionary_rows_are_complete_and_unique**: No column is listed twice, and each has a description and one of
  the five classifications.
- **test_classification_levels_are_all_explained**: Each classification used in the dictionary is described in
  `classification.md`.
- **test_rule_catalog_lists_every_rule_and_expectation**: The rule catalog lists exactly the 23 rules in `quality.py`
  and the expectations in `silver.py`.

### Exports

- **test_export_only_sends_new_rows**: Exports two sales, finds nothing new on a second run, then exports only a third
  added later. Checks that `loaded_at` is renamed so it can't collide with bronze's column, and that an unknown table
  name is refused.

### Pipeline runs

- **test_run_pipeline_reports_how_a_restart_ended**: With a fake CLI, `run_pipeline.py` waits through a schema-change
  restart and reports whether the restart completed or failed.
- **test_run_pipeline_ignores_a_finished_update_from_before_this_run**: A run that fails to start can't report success
  by reading an older update.

### Backups

- **test_backup_prune_keeps_newest_of_that_database_only**: Keeps the newest backups and removes older ones, without
  touching other files or backups of a similarly named database such as `columbus_housing_test`.

## Not covered

- Discovery against the real county website and the full `run`, because they need the network. The
  offline discovery test uses a fake site, so it won't notice if the county changes its address
  pattern.
- The printed report from `run.py report`.
- Taking a real backup, because the CI container and local paths differ. It was tested by hand with a restore.
- Real pages and files. Saving one real Franklin report page into `fixtures/` and adding a test for it
  is the next most useful test to write.
