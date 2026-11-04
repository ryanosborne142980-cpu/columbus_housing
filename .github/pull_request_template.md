## Summary

<!-- What changed and why. Link the issue: Closes #123 -->

## Test plan

- [ ] `ruff check .` is clean
- [ ] `python -m pytest -q` passes
- [ ] New behavior has tests
- [ ] Live run, if this touches a loader or parser (note the result)

## Review checklist

- [ ] Bad input fails loudly instead of loading wrong data
- [ ] Safe to run twice
- [ ] Source terms, robots.txt and attribution still respected
- [ ] No credentials, personal files or machine-specific names
- [ ] README, runbook and `tests/README.md` still true
- [ ] Decision record added, if this makes a lasting choice

## Not in this PR

<!-- Anything deliberately left out, and where it's tracked. -->
