# Glossary

| Term | Meaning | Where it's defined |
|---|---|---|
| Clean sale | A residential sale of $10,000 or more, with a multi-parcel deed counted once. | `v_sale_clean` in `sql/views.sql`; `silver_sale` in `databricks/pipelines/silver.py` |
| Nominal transfer | A sale below $10,000, such as a $1 quitclaim, a family deed or a partial-interest deed. Dropped from clean sales. | Comment on `v_sale_clean` |
| Multi-parcel deed | One deed covering several parcels, which the county lists as one row per parcel with the same address, date and price. Counted once; `parcel_count` says how many. | `v_sale_clean`, `silver_sale` |
| Report | The county's weekly sales page (or a loaded county export file), one row in `auditor_report`. | `sql/schema.sql` |
| Report week | The period from `period_start` to `period_end`, normally 7 days. Weeks in our views start on Monday. | `report_covers_7_days` rule; `v_sale_clean.week_start` |
| Pooled median | The median over every sale in a window, not a median of weekly medians. `v_county_rolling4` pools the trailing 4 weeks. | `v_county_rolling4` |
| Low sample | A ZIP-month with fewer than 10 sales; its year-over-year change is left blank. | `v_zip_month` |
| ZHVI | Zillow Home Value Index, monthly, from Zillow Group. Must be credited to Zillow wherever shown. | `zillow_zhvi` |
| Raw page | A report page saved verbatim so an old week can be re-parsed after a parser fix. | `raw_page`; decision 0001 |
| Bronze / silver | Databricks layers: bronze is raw strings with file and load metadata; silver is typed, de-duplicated tables. | `databricks/pipelines/` |
| Known exception | A checked, accepted rule violation listed in `KNOWN`. | `pipeline/quality.py` |
| Fail / warn | Rule severities. A fail blocks landing in Databricks; a warn is printed for review. | `pipeline/quality.py` |
