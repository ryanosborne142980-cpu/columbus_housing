# Tests

Run from the project root:

```
python -m pytest -q
```

The database tests need the local SQL Server instance (`.\ROSBO_SQL`, or set
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
  "September" all read correctly, and that an unrecognizable month name leaves the week blank instead
  of stopping the run.

### Saving to the database

- **test_load_idempotent_and_validation**: Saves the sample residential report twice. The first save
  adds 6 sales; the second adds none. It also checks that the parsed sale count matches the county's
  own count, which is how parser drift gets spotted on live data.

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

## Not covered

- Finding report pages on the county website (`discover`, `_guess`) and the full `run`, because they
  need the network.
- The printed report from `run.py report`.
- Real pages and files. Saving one real Franklin report page into `fixtures/` and adding a test for it
  is the next most useful test to write.
