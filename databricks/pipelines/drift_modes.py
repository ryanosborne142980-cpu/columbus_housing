"""Test target only: the same Auto Loader read in rescue mode, to compare with bronze's addNewColumns."""
import dlt
from pyspark.sql import functions as F


@dlt.table(name="bronze_sale_rescue_mode", comment="Test only. New columns should go to _rescued_data.")
def bronze_sale_rescue_mode():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821 (provided by the pipeline runtime)
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.inferColumnTypes", "false")
        .option("cloudFiles.schemaEvolutionMode", "rescue")
        .option("header", "true")
        .load(f"{spark.conf.get('columbus.volume')}/auditor_sale/")  # noqa: F821
        .withColumn("source_file", F.col("_metadata.file_path"))
    )
