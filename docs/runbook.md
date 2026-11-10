# Runbook

How to run the pipeline, check that it worked, and recover when it didn't. Run commands from the repo root.

## Schedule

| Source | Published | Command | When to run |
|---|---|---|---|
| Weekly job (Franklin, backup, Databricks) | Sundays | `python scripts/weekly.py` | Mondays |
| Zillow | 16th of the month | `python run.py zillow` | Monthly, after the 16th |
| Redfin | Thursdays | `python run.py redfin --file <download>` | When you download a new file |
| Delaware, Licking | On request | `python run.py county-file --county <name> --file <file>` | When you receive a file |

Register the Monday task once with `powershell -ExecutionPolicy Bypass -File scripts\register_weekly_task.ps1`. It runs
only while you're logged on, and catches up the next time the laptop is on if it missed a Monday. Open a new terminal
first if `COLUMBUS_HOUSING_SERVER` or the Databricks CLI was set up recently, because the task needs both.

Each run writes a log to `data/logs/` and its outcome to `data/logs/last_run.txt`. A failed run also shows as a
non-zero last result in Task Scheduler. Nothing sends an alert, so look at one of those.

`run.py all` loads Franklin and prints the report. It skips Redfin unless you pass `--file` or `--url`.

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
- **`reports` and `skipped` both 0:** discovery found nothing. See the table below. `run.py` exits non-zero for this,
  for a page that couldn't be fetched, and when the newest week is over 14 days old.
- **A `failed` key:** some pages couldn't be fetched. Re-run; it's safe.

Pages that return an error status are logged as `WARNING HTTP ...` but aren't counted in these numbers, so
read the warnings too.

Then run the data checks. The weekly job does this after loading:

```bash
python run.py check
```

The rules are in [pipeline/quality.py](../pipeline/quality.py). `FAIL` means the data is wrong or incomplete: the
command exits 1, and the weekly job skips its Databricks steps but still backs up. Fix the data or the parser, then
re-run `scripts/weekly.py`. `WARN` is for review and blocks nothing.

If a failure turns out to be correct as published, add it to `KNOWN` in `quality.py` with what you found.

Expected as of 2026-11-06:

- **Week of Sep 4, 2026:** the page lists 336 parcels, but its summary says 337. In `KNOWN`.
- **ZIP 46026 (parcel 053-001136-00):** the county's page files the sale under that ZIP. Most sales in that parcel range
  are in 43026, so it's probably a typo, but the data is left as published. In `KNOWN`.
- **$13.1M at 5681 Rager Rd:** warns as a high residential price. The county's page shows that price, but whether it's
  a house hasn't been checked.
- **Three reports with a 6-day week, and two commercial reports giving Jun 5 - 11:** warn. `20260621-WCSR` also accounts
  for 18 of the sales outside their report's week. The summary views use each sale's own date, not the report's week.
- **Nine sales dated Jun 12 in `20260614-WHSR`:** warn as outside that report's Jun 5 - 11 week.
- **Nine April/May 2026 reports with no summary (5 residential, 4 commercial):** the pages don't include one. The
  `parsed_matches_page` rule compares them with the parcel IDs in the saved page instead.

Reports were published exactly 7 days apart across all 59, so these date oddities don't mean a week is missing.

After landing, `python databricks/reconcile.py` checks that silver matches SQL Server. It also runs in the weekly job.

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

- **Nothing alerts you to a failed run.** You have to check `last_run.txt` or Task Scheduler.
- **The weekly task only runs while you're logged on, and the laptop can sleep mid-run.** It went into standby during a
  test on 2026-11-04. Plug in and keep it awake on Monday mornings, or check `last_run.txt` afterward.
- **Discovery can miss a report dated over a day from its Sunday.** Compare the listing's count with what's loaded.
- **Redfin, Delaware and Licking aren't loaded.** All three need a file obtained by hand.
- **Franklin year-over-year isn't available yet.** It needs a year of captured weeks. Zillow covers the gap.
