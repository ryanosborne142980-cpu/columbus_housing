# Glossary

Terms as this project uses them. Where a term is implemented, the code is the definition and this page describes it.

| Term | Meaning | Defined in |
|---|---|---|
| Sale | One row a county published: a parcel, a sale date and a price. Identified by county, parcel, date and price together | `auditor_sale` primary key |
| Clean sale | A residential sale of $10,000 or more, with a multi-parcel deed counted once. Every median is built on clean sales | `v_sale_clean`, `silver_sale` |
| Nominal transfer | A transfer priced under $10,000, such as a $1 quitclaim or a family deed. Left out of clean sales because the price isn't a market price | The price floor in `v_sale_clean` |
| Multi-parcel deed | One sale that covers several parcels. The county lists it as one row per parcel with the same address, date and price | The `GROUP BY` in `v_sale_clean` |
| Parcel count | The number of parcels on a deed. Above 1 marks a multi-parcel deed | `parcel_count` |
| Report | One weekly page from the Franklin County Auditor, residential or commercial, or one county export file | `auditor_report` |
| Report week | The Friday-to-Thursday week a Franklin report covers | `period_start`, `period_end` |
| Reported count | The number of sales the county printed in a report's summary | `reported_count` |
| Parsed rows | The number of sales the parser read from the same page. A difference from the reported count means the parser has drifted or the county miscounted | `parsed_rows`, `v_report_validation` |
| Week start | The Monday of the week a sale closed in. Not the same as the report week | `week_start` |
| Weekly median | The median price of clean sales in one county in one Monday-start week. With an even count, the average of the middle two | `v_county_week` |
| Rolling 4-week median | The median of every clean sale in the trailing four weeks, pooled. Not an average of four weekly medians. Built the same way as Redfin's figure so the two line up | `v_county_rolling4` |
| Year over year | The change from the same period one year earlier. For weeks, 364 days back, so weekdays line up | `v_county_rolling4`, `v_zip_month`, `v_zillow_yoy` |
| Low sample | A ZIP and month with fewer than 10 clean sales. Year-over-year is left blank when either month is a low sample | `low_sample` in `v_zip_month` |
| ZHVI | Zillow Home Value Index: Zillow's smoothed, seasonally adjusted estimate of the typical home value in a region. An estimate, not a sale price | `zillow_zhvi` |
| Raw page | A county report page saved exactly as fetched | `raw_page` |
| Reparse | Running the parser again over saved raw pages, with no network, after a parser fix | `run.py reparse` |
| Bronze | Databricks tables holding source files as received: every value a string, append-only, every version kept | `bronze.py` |
| Silver | Databricks tables with types set, the latest version of each row, and quality rules applied | `silver.py` |
| High point | The newest change time already exported from a SQL Server table. It moves forward only after an upload succeeds | `export.py`, `land_sql_tables.py` |
| Fail rule | A quality rule whose violation means the data is wrong. It stops the weekly job before anything lands in Databricks | `quality.py` |
| Warn rule | A quality rule whose violation may be real. It is printed for review and blocks nothing | `quality.py` |
| Checked exception | A rule violation that was looked at and accepted, recorded with what was found | `KNOWN` in `quality.py` |
| Reconciliation | Comparing Databricks silver with SQL Server on row counts, totals and date ranges after every run | `reconcile.py` |
