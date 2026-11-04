# Contributing

How changes get into this repo. `main` is protected, so the workflow below is enforced, not just suggested.

## Set up

You need Python 3.12 (the version CI uses), SQL Server, and ODBC Driver 18 for SQL Server.

```bash
pip install -r requirements-dev.txt
```

The default server is `localhost` with Windows auth. For a named instance, set `COLUMBUS_HOUSING_SERVER`.
For a SQL login, set `COLUMBUS_HOUSING_UID` and `COLUMBUS_HOUSING_PWD`. Never put credentials in code.

## Make a change

1. **Start from a task.** Open an issue using the task template if one doesn't exist. Write acceptance
   criteria that someone else could check.
2. **Branch from the latest `main`.** Use a short descriptive name, such as `zillow-loader` or
   `docs/process-docs`.
3. **Keep each commit to one logical change.** Tests should pass at every commit.
4. **Check locally before pushing:**
   ```bash
   ruff check .
   python -m pytest -q
   ```
5. **Open a pull request** and fill in the template.
6. **Merge when the checks are green,** using **Create a merge commit**. Squashing would lose the
   commit-by-commit reasoning. Delete the branch afterward.

## Commit messages

Use a short imperative subject. Use the body to explain why, not to restate the diff.

```text
Make Redfin a manual download and read files in chunks

The legacy S3 weekly file stopped updating in March 2025, so drop the default URL.
Read files in chunks, since loading a full-US file whole reached 6.8 GB of memory.
```

## What `main` enforces

| Rule | Setting |
|---|---|
| Changes | Pull requests only; no direct pushes |
| Required checks | `lint` and `test` |
| Branch state | Must be up to date with `main` |
| Review threads | Must be resolved |
| Force pushes and branch deletion | Blocked |
| Admins | The same rules apply; don't use an override to get past a failing check |
| Required approvals | 0, because this is a single-maintainer repo and GitHub doesn't allow self-approval. See [decision 0007](docs/decisions/0007-ci-and-branch-protection.md). |

CI runs ruff and the full test suite against a SQL Server container. `ruff format` is not enforced yet.

## Review checklist

Use this when reviewing a pull request, including your own:

- **Correctness:** does it meet the acceptance criteria, and do tests cover the new behavior?
- **Failure:** does bad input fail loudly instead of loading wrong data silently?
- **Re-runs:** is it still safe to run twice?
- **Data rules:** are source terms, robots.txt and attribution still respected?
- **Secrets:** are credentials, personal files and machine-specific names kept out?
- **Docs:** are the README, runbook and `tests/README.md` still true?
- **Decisions:** if this makes a lasting choice, is there a decision record?

## Project rules

- **New HTTP sources go through `pipeline/http.py`.** It applies robots.txt, rate limiting and backoff.
  Never work around bot protection or a robots.txt block. See
  [decision 0003](docs/decisions/0003-respect-source-access-rules.md).
- **Loads must be safe to repeat.** Re-running must not create duplicates.
- **Keep what can't be fetched again.** Save source pages before parsing them, because they drop off the
  county site. See [decision 0001](docs/decisions/0001-keep-raw-pages.md).
- **Schema lives in `sql/`.** `schema.sql` only creates missing tables, so changing an existing table also
  needs a manual `ALTER` on every database. Views are recreated on each connect.
- **Parser fixes come with a test.** After merging, run `python run.py reparse` to apply the fix to saved
  pages.

## Adding a data source

1. Read the source's terms and robots.txt, and record what you found in a decision record.
2. Add a loader in `pipeline/` and any tables in `sql/schema.sql`.
3. Add a small hand-made sample to `tests/fixtures/`, plus tests for filtering and repeat loads. Include
   look-alike rows that must be dropped.
4. Add attribution if the source requires it.
5. Update the README source table and the runbook.

## Decision records

Add a record to [docs/decisions/](docs/decisions/README.md) when a choice would be expensive to reverse or
would puzzle someone later. Don't edit an accepted record to change the decision. Write a new one and mark
the old one superseded.
