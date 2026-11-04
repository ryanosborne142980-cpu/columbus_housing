# 0007: Test against real SQL Server and protect `main`

**Status:** Accepted, 2026-11-04

## Situation

Much of the logic lives in SQL: medians, rolling windows, duplicate-safe inserts. Skipping database tests in CI, or
using a substitute database, would leave that logic unchecked.

## Decision

- **CI runs `ruff` and the full test suite** on every pull request and every push to `main`. Tests run against a
  SQL Server 2022 container.
- **`db.py` accepts a SQL login through environment variables,** because the Linux container has no Windows auth.
  The CI password belongs to a container that exists only for that job.
- **`main` is protected:** pull requests only, `lint` and `test` required, branch up to date, no force pushes, and
  the same rules for admins.
- **Required approvals are set to 0.** This is a single-maintainer repo and GitHub doesn't allow approving your own
  pull request, so requiring one would block every merge. The [review checklist](../../CONTRIBUTING.md#review-checklist)
  is for self-review instead, and nothing enforces it.

## Consequences

- **SQL behavior is tested on every change,** and each run takes about a minute.
- **Emergency fixes go through a pull request too.**
- **There's no independent review.** Automated checks catch mechanical problems, not bad judgment. Require at least 1
  approval as soon as there is a second contributor.
- **CI doesn't cover live sources.** Tests use sample files, so a change on a source's site shows up in a real run,
  not in CI.
