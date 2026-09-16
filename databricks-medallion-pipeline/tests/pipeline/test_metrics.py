from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from pipeline.metrics import compute_file_metrics

SCHEMA = StructType([
    StructField("_source_file", StringType()),
    StructField("_rescued_data", StringType()),
    StructField("rejection_reason", StringType()),
])


def test_compute_file_metrics_basic(spark):
    # Uso da Bronze: sem extra_aggs, agrupa por _source_file e conta schema drift
    # (_rescued_data não nulo) por arquivo.
    df = spark.createDataFrame(
        [
            {"_source_file": "file_a.json", "_rescued_data": None, "rejection_reason": ""},
            {"_source_file": "file_a.json", "_rescued_data": "extra_field", "rejection_reason": ""},
            {"_source_file": "file_b.json", "_rescued_data": None, "rejection_reason": ""},
        ],
        SCHEMA,
    )
    metrics = {row["source_file"]: row for row in compute_file_metrics(df)}
    assert metrics["file_a.json"]["records_read"] == 2
    assert metrics["file_a.json"]["schema_drift_records"] == 1
    assert metrics["file_b.json"]["records_read"] == 1
    assert metrics["file_b.json"]["schema_drift_records"] == 0


def test_compute_file_metrics_with_extra_aggs(spark):
    # Uso da Silver: extra_aggs adiciona records_inserted (registros não rejeitados)
    # à agregação padrão, sem duplicar a lógica de groupBy em silver_transform.py.
    df = spark.createDataFrame(
        [
            {"_source_file": "file_a.json", "_rescued_data": None, "rejection_reason": ""},
            {"_source_file": "file_a.json", "_rescued_data": None, "rejection_reason": "INVALID_TRACK_ID"},
        ],
        SCHEMA,
    )
    metrics = compute_file_metrics(
        df,
        extra_aggs={"records_inserted": F.sum(F.when(F.col("rejection_reason") == "", 1).otherwise(0))},
    )
    assert len(metrics) == 1
    assert metrics[0]["records_read"] == 2
    assert metrics[0]["records_inserted"] == 1
