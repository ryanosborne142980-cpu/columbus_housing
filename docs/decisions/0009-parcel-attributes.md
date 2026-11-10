# 0009: Add square footage as a monthly parcel snapshot

**Status:** Proposed, 2026-11-07

## Situation

Every median in the project moves with the mix of homes that sold. A week heavy on small condos looks like a price
drop. The README tells readers to treat moves under about 3% as noise for this reason. Price per square foot, plus
year built, beds and baths, would fix most of that.

What each county publishes, as of 2026-11-07:

| County | Source | Square footage | Confirmed? |
|---|---|---|---|
| Franklin | Auditor FTP portal, "Appraisal Files" (tables: Build, Dwelling, Improvement, Land, Parcel, Permit, Sales). Monthly, archives back to 2014. | Expected in the Dwelling table. | Table exists. The living-area column name isn't confirmed; check the label guide XLSX on the FTP page. |
| Franklin | Auditor "Parcel CSV" | Has `YEARBLD`, `BEDRMS`, `BATHS`, `HBATHS`, `LANDUSE`, but no field labeled living area. `AREA_A` ("primary area in square feet") is probably not living area. | Fields confirmed from the field guide. |
| Delaware | No official bulk download found. | Unknown. The existing sales export may already include it, since `county_file.py` ignores unmapped columns. | No. |
| Licking | ArcGIS `Auditor/ParcelsFS` service, described as parcels "joined with CAMA attributes from OnTrac nightly." | Unknown; the field list wasn't readable. | No. |

The attributes describe each parcel **as it is now**, not as it was when it sold. A 2025 sale followed by a 2026
addition would show the 2026 square footage.

## Decision

1. **Store attributes in their own table, not on the sale.** One row per county, parcel and snapshot month:
   `county, parcel_id, snapshot_month, living_sqft, year_built, beds, baths, half_baths, land_use, source_file`.
2. **Snapshot monthly, starting now.** Franklin's archives go back to 2014, so backfill the months that cover
   captured sales. Each month adds rows; nothing is overwritten. The as-of-now problem gets smaller the longer this
   runs.
3. **Land it the same way as everything else** ([0008](0008-land-files-then-auto-loader.md)). Download the file
   locally through `pipeline/http.py`, upload it unchanged to the `raw` volume, and append it to a bronze table with
   Auto Loader. Silver keeps the typed snapshot.
4. **Join each sale to the latest snapshot on or before its sale date.** If the sale is older than the first
   snapshot, use the earliest snapshot and flag the row (`attr_as_of = 'after_sale'`).
5. **Normalize parcel IDs before joining.** Sales parse IDs as `\d{3}-\d{6}-\d{2}` (for example `010-123456-00`).
   The Parcel CSV documents `PID` as district, dash, six digits, with no card suffix. Settle the canonical form from a
   real Dwelling file, and convert both sides to it.
6. **Multi-parcel deeds:** `v_sale_clean` merges them into one sale. Sum `living_sqft` across the deed's parcels that
   have a dwelling, and keep `parcel_count` so these sales can be left out of $/sqft if they look wrong.
7. **New measures:** median $/sqft by county-week, county rolling 4-week and ZIP-month. Exclude sales with no square
   footage or with fewer than 400 sq ft, and report how many were excluded next to each figure.
8. **Franklin first.** Delaware and Licking follow once a source is confirmed. Until then, $/sqft is Franklin only,
   and outputs say so.

## Checks

- **Match rate:** the share of clean residential sales that found a snapshot row, by county and month. Under 95% for
  Franklin means the ID normalization is wrong.
- **Coverage:** the share of matched sales with a usable `living_sqft`.
- **Sanity:** $/sqft outside roughly $30–$1,000 goes to a review view, not the median.

## Consequences

- **$/sqft is mix-adjusted for size only.** Condition, lot and location within a ZIP still shift the figures.
- **Historic sales use today's attributes** until snapshots catch up. Remodeled homes will look cheaper per square
  foot than they were. The `after_sale` flag lets you measure how many rows are affected.
- **A new monthly manual-or-scheduled job,** next to Zillow's. It isn't part of the weekly run.
- **Franklin-only at first,** so county comparisons on $/sqft wait for Delaware and Licking.

## Open questions

- [ ] Name of the finished-living-area column in Franklin's Dwelling table, and whether a parcel can have several
      dwelling rows (one per card). If it can, sum them.
- [ ] Whether the FTP portal allows automated downloads under robots.txt and its terms
      ([0003](0003-respect-source-access-rules.md)). If not, this becomes a manual monthly download, like Redfin.
- [ ] Does the Delaware sales export already include square footage?
- [ ] Which fields the Licking `ParcelsFS` service exposes, and whether its terms allow bulk queries.

## Sources

- [Franklin County Auditor FTP downloads](https://auditor.franklincountyohio.gov/Auditor/FTP)
- [Franklin Parcel CSV field descriptions (PDF)](https://stagefranklincountyauditor.franklincountyohio.gov/AUDR-website/media/Documents/FTP/Parcel-CSV-description-of-fields.pdf)
- [Licking County `Auditor/ParcelsFS` service](https://apps.lickingcounty.gov/arcgis/rest/services/Auditor/ParcelsFS/FeatureServer)
- [Land Records: Delaware County coverage](https://www.landrecords.us/documentation/coverage/counties/39-041-delaware)
