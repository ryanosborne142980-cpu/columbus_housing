# Runbook

How to run the pipeline, check that it worked, and recover when it didn't. Run commands from the repo root.

## Schedule

| Source | Published | Command | When to run |
|---|---|---|---|
| Franklin County | Sundays | `python run.py all --commercial` | Weekly, Monday morning |
| Zillow | 16th of the month | `python run.py zillow` | Monthly, after the 16th |
| Redfin | Thursdays | `python run.py redfin --file <download>` | When you download a new file |
| Database backup | n/a | `python run.py backup` | After each load, until scheduled |
| Delaware, Licking | On request | `python run.py county-file --county <name> --file <file>` | When you receive a file |

`all` loads Franklin and prints the report. It skips Redfin unless you pass `--file` or `--url`.

By default it looks back 56 days. After a longer gap, add `--since <date>`.

**Don't miss weeks.** The county appears to keep roughly 30 weeks of reports online. A week that drops off
before it is captured is gone for good.

## Check a run

A healthy Franklin run ends like this:

```text
auditor: {'reports': 1, 'new_rows': 340, 'skipped': 8}
```

- **`reports` of 1 or more:** new pages were loaded.
- **`reports` of 0 with `skipped` above 0:** normal if nothing new has been published.
- **`reports` and `skipped` both 0:** discovery found nothing. See the table below.
- **A `failed` key:** some pages couldn't be fetched. Re-run; it's safe.

Pages that return an error status are logged as `WARNING HTTP ...` but aren't counted in these numbers, so
read the warnings too.

Then run these checks. The first three should return no rows:

```sql
-- Parsed count differs from the county's own count.
SELECT report_url, reported_count, parsed_rows, diff FROM v_report_validation WHERE diff <> 0;

-- Report has no week or no sales.
SELECT report_url FROM auditor_report WHERE period_start IS NULL OR parsed_rows = 0;

-- Sale has no ZIP.
SELECT TOP 20 parcel_id, sale_date, report_url FROM auditor_sale WHERE zip IS NULL;

-- Newest week loaded. Should end within about 11 days of today.
SELECT MAX(period_end) FROM auditor_report;
```

`v_report_validation` leaves out reports with no county summary, so it can't vouch for them:

```sql
SELECT report_url, period_start, parsed_rows FROM auditor_report WHERE reported_count IS NULL;
```

Expected exceptions:

- **Week of Sep 4, 2026 (`diff` of -1):** the page lists 336 parcels, but its summary says 337. The county's
  number is wrong.
- **Nine April/May 2026 reports with no summary (5 residential, 4 commercial):** the pages don't include one.
  Their parsed counts were checked against the parcel numbers on each page instead.
- **Some report weeks look odd, such as Jun 20 – 26, 2026:** the county's page gives two different ranges. The
  summary views use each sale's own date, not the report's week.

## When something fails

| Symptom | Likely cause | What to do |
|---|---|---|
| `08001` or `Could not open a connection to SQL Server` | Wrong server, or a shell started before `COLUMBUS_HOUSING_SERVER` was set | Set the variable and open a new terminal. Check that the SQL Server service is running. |
| `reports` and `skipped` both 0 | Site down, or the county changed its URLs | Read the log for `listing unavailable` or `site unreachable`. Open the listing in a browser. If URLs changed, update `SLUG_GUESSES` or `discover`. |
| `WARNING skip unparseable row` | The page format changed | Fix the parser and add a test, then follow [Re-parse saved pages](#re-parse-saved-pages). |
| `WARNING count mismatch` | Rows were missed, or the county's count is wrong | Count parcel numbers in the saved page. If the page has more than were parsed, fix the parser. If they match, record the exception here. |
| `RobotsDisallowed` or a robots.txt block | The site's rules changed or it is blocking bots | **Stop. Don't work around it.** Check the rules by hand. See [decision 0003](decisions/0003-respect-source-access-rules.md). |
| Repeated 429 or 503 | The server is asking for less traffic | `http.py` already backs off and retries. Wait and try later. Don't raise the request rate. |
| Redfin: `needs --file` | The default URL was removed on purpose | Download from the [Redfin Data Center](https://www.redfin.com/news/data-center/). See [decision 0005](decisions/0005-redfin-manual-download.md). |
| Redfin: `No Columbus-area rows` | Region names changed, or it's the wrong file | Check the region column and update `REGION_MATCH`. |
| Zillow: 404 | Zillow moved its CSV paths | Get the new link from the [data page](https://www.zillow.com/research/data/), then use `--url` or `--file`. |
| County file: `no column for [...]` | An unfamiliar header | The error lists the file's columns. Add the header to `COLUMN_HINTS` and add a test. |
| CI `test` fails but local passes | A difference between the Linux container and local | Read the job log. Check for Windows-only assumptions in paths, line endings or auth. |

## Load one report

If a report is on the county's listing but discovery missed it, load it directly. This is safe to repeat.

```bash
python run.py auditor --url <report page URL>
```

## Re-parse saved pages

Use this after a parser fix. It needs no network.

```bash
python run.py reparse
```

**Limit:** this adds missed sales and refreshes report summaries, but it doesn't change or remove sales
already stored. Price is part of the sale key, so a corrected price would be added next to the wrong one. If a
bug stored wrong values, back up the database, delete that report's rows from `auditor_sale`, and then re-parse.

## Back up and restore

```bash
python run.py backup
```

This makes a verified, compressed backup and copies it to `%OneDrive%/Backups/columbus_housing`, keeping the newest
8. Set `COLUMBUS_HOUSING_BACKUP_DIR` to use another folder. Copy-only backups leave the database's recovery settings
alone. A file in that folder isn't proof it reached the cloud, so check that OneDrive shows it as synced.

**One-time setup:** SQL Server writes the file as its service account, so that account needs one folder it can write
to. Create `%LOCALAPPDATA%/columbus_housing/backups`, or set `COLUMBUS_HOUSING_BACKUP_STAGING`, and give the account
Modify access. Find the account with `SELECT service_account FROM sys.dm_server_services`.

**Restore:** copy the `.bak` into the staging folder, because SQL Server may not be able to read OneDrive. Then run
`RESTORE DATABASE` under a new name with `MOVE` for each file, and compare row counts before replacing anything. This
was tested on 2026-11-04: every table count matched, and `raw_page` matched on total bytes and content hashes.

## Known gaps

As of 2026-11-04. Move these to issues as they get scheduled.

- **The weekly job isn't scheduled.** It only runs by hand. Set up Windows Task Scheduler with the repo root
  as the working directory, and make sure the task can see `COLUMBUS_HOUSING_SERVER`.
- **Backups aren't scheduled.** They only run when someone runs `python run.py backup`.
- **Redfin, Delaware and Licking aren't loaded.** All three need a file obtained by hand.
- **Franklin year-over-year isn't available yet.** It needs a year of captured weeks. Zillow covers the gap.
