# Governance

What the data means, how sensitive it is, where it comes from, and which rule protects it. A catalog tool would
normally hold this. The project doesn't run one, so the documents live beside the code and
[`tests/test_governance.py`](../../tests/test_governance.py) fails the build when they disagree with it.

| Document | Answers | A catalog tool calls this |
|---|---|---|
| [data_dictionary.csv](data_dictionary.csv) | What is this column, and what type is it? | Technical metadata, asset descriptions |
| [glossary.md](glossary.md) | What does the business mean by this term? | Business glossary |
| [classification.md](classification.md) | How sensitive is it, and how must it be handled? | Classifications, sensitivity labels |
| [lineage.md](lineage.md) | Where did it come from, and what changed it on the way? | Lineage |
| [quality-rules.md](quality-rules.md) | What checks it, and what happens when a check fails? | Data quality rules |

## Roles

This is a single-maintainer project, so one person holds every role. They're listed separately because they are
different jobs.

| Role | Who | Decides |
|---|---|---|
| Source owner | Franklin, Delaware and Licking County Auditors; Zillow; Redfin | What is published, and on what terms |
| Data owner | The repo maintainer | What is loaded, kept and shown |
| Data steward | The repo maintainer | Definitions, classifications, rule thresholds and checked exceptions |

A checked exception to a rule is a steward decision. Each one is written next to the rule, in `KNOWN` in
[`pipeline/quality.py`](../../pipeline/quality.py), with what was found.

## What CI enforces

- Every column in [`sql/schema.sql`](../../sql/schema.sql) is in the dictionary with the same type, and the
  dictionary has no column the schema lacks.
- Every silver table in the dictionary exists in [`silver.py`](../../databricks/pipelines/silver.py), and the other
  way round.
- Every dictionary row has a description and one of the five classifications.
- Every rule in `pipeline/quality.py` and every expectation in `silver.py` is in the rule catalog.

## What nothing enforces

- **Silver column lists and types.** They were read from the pipeline code by hand. CI checks the table names only.
- **Descriptions being right.** CI checks that one exists.
- **The lineage diagram.**
- **`redfin_columbus_weekly` has no dictionary rows.** The loader rebuilds it on every load and Redfin's columns
  vary, so `redfin_load_log.columns` records what each file held. No real Redfin file has been loaded yet.
- **Classifications aren't applied in Databricks.** The pipeline code sets table comments, and those do reach
  Unity Catalog. Column comments, classification tags and access rules don't.
