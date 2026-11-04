"""Bronze: land source files raw and append-only with Auto Loader.

Every value stays a string (no type inference), so bronze keeps what the file said. Each row
records which file it came from and when it was loaded, so it can be traced and replayed. Auto
Loader tracks processed files, so re-running the pipeline doesn't load a file twice.

Zillow adds a column every month, so its schema really does drift. In the default
addNewColumns mode the stream stops once on a new column, adds it, and continues on restart.
Data from Zillow requires attribution wherever it's shown.
"""
import dlt
from pyspark.sql import functions as F

VOLUME = "/Volumes/workspace/columbus_housing/raw"


def _auto_loader(folder: str):
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821 (provided by the pipeline runtime)
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.inferColumnTypes", "false")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        .load(f"{VOLUME}/{folder}/")
        .withColumn("source_file", F.col("_metadata.file_path"))
        .withColumn("source_modified_at", F.col("_metadata.file_modification_time"))
        .withColumn("loaded_at", F.current_timestamp())
    )


@dlt.table(
    name="bronze_auditor_sale",
    comment="County sales exported from SQL Server, raw. Rows arrive only as new files are landed.",
)
def bronze_auditor_sale():
    return _auto_loader("auditor_sale")


@dlt.table(
    name="bronze_auditor_report",
    comment="County report summaries, raw. A re-parsed report arrives again; silver picks the latest.",
)
def bronze_auditor_report():
    return _auto_loader("auditor_report")


@dlt.table(
    name="bronze_zillow_county",
    comment="Zillow Home Value Index by county, raw. Source: Zillow Group, zillow.com/research/data.",
)
def bronze_zillow_county():
    return _auto_loader("zillow_county")
