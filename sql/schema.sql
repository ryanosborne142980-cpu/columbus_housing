-- Landed tables. Each is created only if missing, so existing data is kept.
--
-- Layers:
--   raw      raw_page (fetched HTML, kept verbatim), plus county export files and the Redfin file
--   cleaned  auditor_report / auditor_sale (parsed), redfin_columbus_weekly, v_sale_clean
--   summary  v_county_week, v_county_rolling4, v_zip_month (sql/views.sql)
-- Franklin report pages drop off the county site after ~30 weeks, so raw_page is the only
-- way to re-parse an old week after a parser fix (python run.py reparse).

-- Every fetched report page, verbatim. A refetch adds a row only if the content changed.
IF OBJECT_ID('dbo.raw_page', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.raw_page (
        id INT IDENTITY PRIMARY KEY,
        url NVARCHAR(450) NOT NULL,
        http_status INT NOT NULL,
        content_sha256 CHAR(64) NOT NULL,
        content NVARCHAR(MAX) NOT NULL,
        fetched_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME()
    );
    CREATE UNIQUE INDEX ux_raw_page ON dbo.raw_page (url, content_sha256);
END
GO

-- One row per fetched report page or loaded county file.
IF OBJECT_ID('dbo.auditor_report', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.auditor_report (
        -- Page URL, or file:<county>:<name> for county exports.
        report_url NVARCHAR(450) NOT NULL PRIMARY KEY,
        county NVARCHAR(20) NOT NULL DEFAULT 'Franklin',
        -- residential or commercial
        report_type NVARCHAR(20) NOT NULL,
        period_start DATE,
        period_end DATE,
        published_on DATE,
        -- The county's own summary figures, used to validate parsing.
        reported_count INT,
        reported_median FLOAT,
        reported_avg FLOAT,
        parsed_rows INT,
        fetched_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- Parcel-level sales, keyed on county + parcel + date + price.
IF OBJECT_ID('dbo.auditor_sale', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.auditor_sale (
        county NVARCHAR(20) NOT NULL DEFAULT 'Franklin',
        parcel_id NVARCHAR(50) NOT NULL,
        sale_date DATE NOT NULL,
        sale_price INT NOT NULL,
        site_address NVARCHAR(200),
        zip NVARCHAR(10),
        report_type NVARCHAR(20) NOT NULL,
        report_url NVARCHAR(450) NOT NULL REFERENCES dbo.auditor_report (report_url),
        loaded_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        PRIMARY KEY (county, parcel_id, sale_date, sale_price)
    );
    CREATE INDEX ix_sale_date ON dbo.auditor_sale (sale_date);
    CREATE INDEX ix_sale_zip ON dbo.auditor_sale (zip, sale_date);
END
GO

-- One row per Redfin load. The Redfin data table itself (redfin_columbus_weekly) is
-- rebuilt by the loader each time, since Redfin revises history and its columns vary.
IF OBJECT_ID('dbo.redfin_load_log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.redfin_load_log (
        loaded_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        source NVARCHAR(1000) NOT NULL,
        rows_loaded INT NOT NULL,
        columns NVARCHAR(MAX) NOT NULL
    );
END
