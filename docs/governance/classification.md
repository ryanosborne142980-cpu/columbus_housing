# Classification

Every column in the [data dictionary](data_dictionary.csv) has one of five levels. No data in this project is
confidential: the sources are public or published for public use. The levels exist because public data still
carries handling rules.

| Level | Meaning | Handling |
|---|---|---|
| Public record | Published by a county auditor, with no link to one property | No restriction |
| Public record, identifies a property | `parcel_id` and `site_address`. Public, but a county owner search turns either into a person's name | Show in aggregates. Don't join to owner or buyer data |
| Public record, not reviewed | `raw_page.content`: county pages saved whole | Keep in SQL Server and its backups only. Don't export or publish the pages |
| Licensed, attribution required | Zillow values, and Redfin's once loaded | Credit the source wherever the data is shown |
| Operational | Load times, hashes, file paths, row counts, addresses of pages | No restriction |

## What is deliberately not collected

- **Owner, buyer and seller names, and mailing addresses.** No table has a column for them. When a county export
  file includes them, [`county_file.py`](../../pipeline/county_file.py) leaves out any column whose header matches
  `owner`, `mail`, `buyer`, `seller`, `grantor` or `grantee` before it maps any column.
- **Franklin's Daily Conveyance data.** The county's robots.txt disallows it. See
  [decision 0003](../decisions/0003-respect-source-access-rules.md).

## How attribution is enforced

- `zillow_load_log.attribution` stores the credit line with every load.
- `run.py report` prints the source line, and `--export` writes `ATTRIBUTION.txt` beside the Zillow file.
- The Databricks table comments for `bronze_zillow_county` and `silver_zillow_county` name the source.

## Retention

| Data | Kept | Why |
|---|---|---|
| `raw_page` | Indefinitely | County pages leave the site after roughly 30 weeks, and a parser fix needs the original. See [decision 0001](../decisions/0001-keep-raw-pages.md) |
| Files in the Databricks `raw` volume | Indefinitely, never edited; no code deletes them | Bronze can be replayed from them |
| Bronze tables | Indefinitely, append-only | Every version of a row is kept; silver picks the latest |
| Database backups | The newest 8 | `KEEP` in [`backup.py`](../../pipeline/backup.py) |

## Open items

- [ ] **`raw_page.content` hasn't been reviewed for personal fields.** The parser reads four columns from each
      table: parcel number, site address, sale price and sale date. Whether real pages carry anything else, such as
      a buyer's name, hasn't been checked against a saved page. Until it is, the column keeps its own level.
- [ ] **Nothing stops a join to owner data.** The "don't join" rule for parcel IDs and addresses is a written rule
      only.
- [ ] **No column tags in Unity Catalog.** The levels live in the CSV.
