"""Keeps docs/governance in step with the schema and the rules. Needs no database."""
import csv
import re
from pathlib import Path

from pipeline import quality

ROOT = Path(__file__).parent.parent
GOV = ROOT / "docs" / "governance"
SILVER = (ROOT / "databricks" / "pipelines" / "silver.py").read_text()
NOT_COLUMNS = ("PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN", "CHECK")


def _schema_columns() -> set[tuple[str, str]]:
    sql = (ROOT / "sql" / "schema.sql").read_text()
    found = set()
    for table, body in re.findall(r"CREATE TABLE dbo\.(\w+) \((.*?)\n    \);", sql, re.S):
        for line in body.splitlines():
            m = re.match(r"\s{8}(\w+)\s+\w", line)
            if m and not m.group(1).upper().startswith(NOT_COLUMNS):
                found.add((table, m.group(1)))
    return found


def _dictionary() -> list[dict]:
    with open(GOV / "data_dictionary.csv", newline="") as f:
        return list(csv.DictReader(f))


def _catalog_names(heading: str) -> set[str]:
    text = (GOV / "quality-rules.md").read_text()
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `(\w+)` \|", section, re.M))


def test_dictionary_matches_schema():
    rows = _dictionary()
    documented = {(r["table"], r["column"]) for r in rows if r["layer"] == "sql"}
    schema = _schema_columns()
    assert schema, "no columns parsed from sql/schema.sql"
    assert schema - documented == set(), "columns missing from the dictionary"
    assert documented - schema == set(), "dictionary columns the schema lacks"


def test_dictionary_rows_are_complete():
    levels = {"Public", "Internal", "Confidential", "Restricted"}
    for r in _dictionary():
        assert r["classification"] in levels, r
        assert r["type"] and r["meaning"], r


def test_every_silver_table_is_documented():
    tables = set(re.findall(r'name="(silver_\w+)"', SILVER))
    documented = {r["table"] for r in _dictionary() if r["layer"] == "silver"}
    assert tables - {"silver_sale_typed"} == documented


def test_rule_catalog_matches_rules():
    assert _catalog_names("## SQL Server rules") == {r.name for r in quality.RULES}


def test_rule_catalog_severities_match():
    text = (GOV / "quality-rules.md").read_text()
    listed = dict(re.findall(r"^\| `(\w+)` \| \w+ \| (fail|warn) \|", text, re.M))
    assert listed == {r.name: r.severity for r in quality.RULES}


def test_expectation_catalog_matches_silver():
    in_code = set(re.findall(r'@dlt\.expect\w*\("(\w+)"', SILVER))
    assert _catalog_names("## Pipeline expectations") == in_code
