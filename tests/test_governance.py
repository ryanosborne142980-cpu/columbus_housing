"""Keep docs/governance in step with the code. None of these tests need a database.

A dictionary nobody checks goes stale the first time a column is added. These fail the build instead:
a column or rule that exists in code but not in the documents, or the other way round.
"""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
GOV = ROOT / "docs" / "governance"
CLASSIFICATIONS = {
    "public record",
    "public record, identifies a property",
    "public record, not reviewed",
    "licensed, attribution required",
    "operational",
}


def _dictionary() -> list[dict]:
    with (GOV / "data_dictionary.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _schema_columns() -> dict[tuple[str, str], str]:
    """(table, column) -> type, read from the CREATE TABLE statements in sql/schema.sql."""
    sql = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    found = {}
    for table, body in re.findall(r"CREATE TABLE dbo\.(\w+) \((.*?)\n\s*\);", sql, re.S):
        for line in body.splitlines():
            m = re.match(r"\s*(\w+)\s+([A-Z0-9]+(?:\([^)]*\))?)", line)
            if m and m.group(1) != "PRIMARY":
                found[(table, m.group(1))] = m.group(2)
    return found


def test_schema_parser_reads_a_known_table():
    # Guards the regex above: if it stops matching, the comparison below would pass on nothing.
    columns = _schema_columns()
    assert columns[("auditor_sale", "sale_price")] == "INT"
    assert columns[("raw_page", "content")] == "NVARCHAR(MAX)"
    assert len({table for table, _ in columns}) == 6


def test_dictionary_matches_sql_server_schema():
    documented = {(r["object"], r["column"]): r["type"] for r in _dictionary() if r["layer"] == "sql_server"}
    assert documented == _schema_columns()


def test_dictionary_silver_tables_exist_in_the_pipeline():
    silver = (ROOT / "databricks" / "pipelines" / "silver.py").read_text(encoding="utf-8")
    defined = set(re.findall(r'@dlt\.table\(\s*name="(\w+)"', silver))
    documented = {r["object"] for r in _dictionary() if r["layer"] == "silver"}
    assert documented == defined


def test_dictionary_rows_are_complete_and_unique():
    rows = _dictionary()
    keys = [(r["layer"], r["object"], r["column"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        assert r["layer"] in ("sql_server", "silver"), r
        assert r["description"].strip(), r
        assert r["classification"] in CLASSIFICATIONS, r


def test_classification_levels_are_all_explained():
    text = (GOV / "classification.md").read_text(encoding="utf-8").lower()
    for level in CLASSIFICATIONS:
        assert level in text, level


def test_rule_catalog_lists_every_rule_and_expectation():
    catalog = (GOV / "quality-rules.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `(\w+)` \|", catalog, re.M))
    rules = set(re.findall(r'Rule\("(\w+)"', (ROOT / "pipeline" / "quality.py").read_text(encoding="utf-8")))
    silver = (ROOT / "databricks" / "pipelines" / "silver.py").read_text(encoding="utf-8")
    expectations = set(re.findall(r'@dlt\.expect(?:_or_drop|_or_fail)?\("(\w+)"', silver))
    assert len(rules) == 23
    assert expectations
    assert listed == rules | expectations
