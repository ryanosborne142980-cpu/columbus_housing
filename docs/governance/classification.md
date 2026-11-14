# Data classification

Levels used in `data_dictionary.csv`:

| Level | Meaning | Handling |
|---|---|---|
| Public | Published by the county or Zillow, or derived only from such data, and not about an identifiable home. | May be shown and shared. Credit Zillow wherever its data appears. |
| Internal | Pipeline bookkeeping with no business meaning outside this project. | Keep in the project's databases; no need to publish. |
| Confidential | Public record that identifies a particular home, such as a street address with a price and date. | Don't publish at the address level in reports or the portfolio site; aggregate to ZIP or county. |
| Restricted | Content not reviewed for personal fields. | Don't share or export. Review before changing its level. |

## Not collected

The pipeline parses only parcel ID, sale date, sale price, site address and ZIP from county pages. County export
loading deliberately skips owner, mailing, buyer, seller, grantor and grantee columns (`_NOT_PROPERTY` in
`pipeline/county_file.py`). No names, phone numbers or emails are stored in parsed tables.

## Open risk

`raw_page.content` holds county pages as published. Whether real pages carry personal fields beyond the four parsed
columns hasn't been checked, so the column is classified Restricted until it is.

## Not covered

`redfin_columbus_weekly` is rebuilt on every load and its columns vary, so it isn't in the dictionary. Redfin's data
is market statistics by region, with no individual homes.
