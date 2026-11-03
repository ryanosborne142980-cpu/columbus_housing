-- Analysis views, rebuilt on every connect.
-- Medians use PERCENTILE_CONT(0.5), which averages the middle two values when the count is even.
-- Weeks start on Monday.

-- Residential sales of $10k or more, with multi-parcel deeds counted once.
-- The price floor drops nominal transfers ($1 quitclaims, family and partial-interest deeds).
-- A deed covering several parcels shows up as one row per parcel with the same address, date and price.
CREATE OR ALTER VIEW dbo.v_sale_clean AS
SELECT
    county,
    MIN(parcel_id) AS parcel_id,
    sale_date,
    sale_price,
    MIN(site_address) AS site_address,
    zip,
    COUNT(*) AS parcel_count,
    -- 1900-01-01 was a Monday, so this works regardless of the server's DATEFIRST setting.
    DATEADD(day, -(DATEDIFF(day, '19000101', sale_date) % 7), sale_date) AS week_start,
    -- YYYY-MM
    CONVERT(char(7), sale_date, 126) AS month
FROM dbo.auditor_sale
WHERE report_type = 'residential'
    AND sale_price >= 10000
GROUP BY county, sale_date, sale_price, COALESCE(site_address, parcel_id), zip;
GO

CREATE OR ALTER VIEW dbo.v_county_week AS
WITH med AS (
    SELECT DISTINCT
        county,
        week_start,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sale_price)
            OVER (PARTITION BY county, week_start) AS median_price
    FROM dbo.v_sale_clean
)
SELECT
    c.county,
    c.week_start,
    COUNT(*) AS sales,
    ROUND(AVG(CAST(c.sale_price AS FLOAT)), 0) AS avg_price,
    m.median_price
FROM dbo.v_sale_clean c
JOIN med m ON m.county = c.county AND m.week_start = c.week_start
GROUP BY c.county, c.week_start, m.median_price;
GO

-- Median over every sale in the trailing 4 weeks (a pooled median, not a median of weekly medians).
-- This matches how Redfin builds its rolling 4-week figures, so the two can be compared.
CREATE OR ALTER VIEW dbo.v_county_rolling4 AS
WITH weeks AS (
    SELECT DISTINCT county, week_start FROM dbo.v_sale_clean
),
win AS (
    SELECT w.county, w.week_start, s.sale_price
    FROM weeks w
    JOIN dbo.v_sale_clean s
        ON s.county = w.county
        AND s.week_start BETWEEN DATEADD(day, -21, w.week_start) AND w.week_start
),
cur AS (
    SELECT DISTINCT
        county,
        week_start,
        COUNT(*) OVER (PARTITION BY county, week_start) AS sales_4wk,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sale_price)
            OVER (PARTITION BY county, week_start) AS median_4wk
    FROM win
)
SELECT
    c.county,
    c.week_start,
    c.sales_4wk,
    c.median_4wk,
    p.median_4wk AS median_4wk_prior_year,
    ROUND(100.0 * (c.median_4wk - p.median_4wk) / NULLIF(p.median_4wk, 0), 1) AS median_yoy_pct,
    CAST(ROUND(100.0 * (c.sales_4wk - p.sales_4wk) / NULLIF(p.sales_4wk, 0), 1) AS FLOAT) AS sales_yoy_pct
FROM cur c
LEFT JOIN cur p ON p.county = c.county AND p.week_start = DATEADD(day, -364, c.week_start);
GO

-- Monthly median by ZIP. Weekly ZIP counts are too small to trend.
-- All counties are pooled, because some ZIPs (e.g. 43081, 43082) cross the Franklin/Delaware line.
-- YoY is left blank when either month has fewer than 10 sales.
CREATE OR ALTER VIEW dbo.v_zip_month AS
WITH cur AS (
    SELECT DISTINCT
        zip,
        month,
        COUNT(*) OVER (PARTITION BY zip, month) AS sales,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sale_price)
            OVER (PARTITION BY zip, month) AS median_price
    FROM dbo.v_sale_clean
)
SELECT
    c.zip,
    c.month,
    c.sales,
    c.median_price,
    p.median_price AS median_prior_year,
    CASE
        WHEN c.sales >= 10 AND p.sales >= 10
        THEN ROUND(100.0 * (c.median_price - p.median_price) / NULLIF(p.median_price, 0), 1)
    END AS median_yoy_pct,
    CAST(CASE WHEN c.sales < 10 THEN 1 ELSE 0 END AS BIT) AS low_sample
FROM cur c
LEFT JOIN cur p
    ON p.zip = c.zip
    AND p.month = CONVERT(char(7), DATEADD(year, -1, CAST(c.month + '-01' AS DATE)), 126);
GO

-- Parsed row count vs the count the county printed on the report. A non-zero diff means the
-- parser has drifted. Franklin only: county export files carry no count to check against.
CREATE OR ALTER VIEW dbo.v_report_validation AS
SELECT
    report_url,
    county,
    report_type,
    period_start,
    period_end,
    reported_count,
    parsed_rows,
    parsed_rows - reported_count AS diff
FROM dbo.auditor_report
WHERE reported_count IS NOT NULL;
