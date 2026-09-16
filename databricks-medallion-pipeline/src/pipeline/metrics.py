from pyspark.sql import functions as F


def compute_file_metrics(df, extra_aggs=None):
    aggs = [
        F.count("*").alias("records_read"),
        F.sum(F.when(F.col("_rescued_data").isNotNull(), 1).otherwise(0)).alias("schema_drift_records"),
    ]
    if extra_aggs:
        aggs.extend(column.alias(name) for name, column in extra_aggs.items())
    return [
        row.asDict()
        for row in df.groupBy("_source_file").agg(*aggs).withColumnRenamed("_source_file", "source_file").collect()
    ]
