from datetime import datetime, timedelta, timezone

from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType, TimestampType

from pipeline.gold import (
    aggregate_file_processing_latency,
    aggregate_pipeline_run_health,
    aggregate_rejection_reasons,
    aggregate_timestamp_classifications,
)

PIPELINE_AUDIT_SCHEMA = StructType([
    StructField("pipeline_name", StringType()),
    StructField("task_name", StringType()),
    StructField("batch_id", LongType()),
    StructField("started_at", TimestampType()),
    StructField("finished_at", TimestampType()),
    StructField("status", StringType()),
    StructField("records_read", LongType()),
    StructField("records_inserted", LongType()),
    StructField("records_rejected", LongType()),
    StructField("schema_drift_records", LongType()),
])

FILE_AUDIT_SCHEMA = StructType([
    StructField("source_file", StringType()),
    StructField("target_table", StringType()),
    StructField("processed_at", TimestampType()),
    StructField("status", StringType()),
])

QUARANTINE_SCHEMA = StructType([
    StructField("rejected_at", TimestampType()),
    StructField("rejection_reason", StringType()),
])

SILVER_SCHEMA = StructType([
    StructField("_ingested_at", TimestampType()),
    StructField("timestamp_classification", StringType()),
])


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_aggregate_pipeline_run_health_groups_by_date_pipeline_task(spark):
    now = _now()
    df = spark.createDataFrame([
        {
            "pipeline_name": "spotify_events_pipeline", "task_name": "ingest_bronze", "batch_id": 1,
            "started_at": now, "finished_at": now + timedelta(seconds=10), "status": "SUCCESS",
            "records_read": 10, "records_inserted": 10, "records_rejected": 0, "schema_drift_records": 0,
        },
        {
            # Mesmo dia/pipeline/task: deve ser agregado na mesma linha.
            "pipeline_name": "spotify_events_pipeline", "task_name": "ingest_bronze", "batch_id": -1,
            "started_at": now, "finished_at": now + timedelta(seconds=2), "status": "SUCCESS",
            "records_read": 0, "records_inserted": 0, "records_rejected": 0, "schema_drift_records": 0,
        },
    ], PIPELINE_AUDIT_SCHEMA)

    result = aggregate_pipeline_run_health(df).collect()

    assert len(result) == 1
    row = result[0]
    assert row["runs_count"] == 2
    assert row["success_count"] == 2
    assert row["failed_count"] == 0
    # Uma das duas execuções tinha batch_id=-1 (execução sem dados novos).
    assert row["empty_runs_count"] == 1
    assert row["records_read_sum"] == 10


def test_aggregate_pipeline_run_health_counts_failures(spark):
    now = _now()
    df = spark.createDataFrame([{
        "pipeline_name": "spotify_events_pipeline", "task_name": "transform_silver", "batch_id": 1,
        "started_at": now, "finished_at": now + timedelta(seconds=5), "status": "FAILED",
        "records_read": 5, "records_inserted": 0, "records_rejected": 0, "schema_drift_records": 0,
    }], PIPELINE_AUDIT_SCHEMA)

    result = aggregate_pipeline_run_health(df).collect()[0]

    assert result["failed_count"] == 1
    assert result["success_count"] == 0


def test_aggregate_file_processing_latency_extracts_timestamp_from_filename(spark):
    # Nome de arquivo real gerado pelo producer (ver src/producer/producer_simulator.py).
    file_ts = datetime(2026, 9, 16, 8, 52, 30) + timedelta(hours=3)  # -0300 -> UTC
    processed_at = file_ts + timedelta(seconds=90)
    df = spark.createDataFrame([{
        "source_file": "/Volumes/x/landing/events_volume/eventos_com_caos_2026-09-16T085230-0300.json",
        "target_table": "databricks_course_ws_new.bronze.spotify_events_raw",
        "processed_at": processed_at,
        "status": "SUCCESS",
    }], FILE_AUDIT_SCHEMA)

    result = aggregate_file_processing_latency(df).collect()[0]

    assert result["files_count"] == 1
    assert result["failed_files_count"] == 0
    assert abs(result["avg_latency_sec"] - 90) < 1


def test_aggregate_file_processing_latency_counts_failed_files(spark):
    now = _now()
    df = spark.createDataFrame([{
        "source_file": "/Volumes/x/landing/events_volume/eventos_com_caos_2026-09-16T085230-0300.json",
        "target_table": "databricks_course_ws_new.bronze.spotify_events_raw",
        "processed_at": now,
        "status": "FAILED",
    }], FILE_AUDIT_SCHEMA)

    result = aggregate_file_processing_latency(df).collect()[0]

    assert result["failed_files_count"] == 1


def test_aggregate_rejection_reasons_splits_combined_reasons(spark):
    # rejection_reason é um concat_ws de múltiplos motivos (ver silver.py); cada
    # motivo deve virar uma linha própria na agregação, não um bucket combinado.
    now = _now()
    df = spark.createDataFrame([{
        "rejected_at": now,
        "rejection_reason": "INVALID_EVENT_ID; INVALID_TRACK_ID",
    }], QUARANTINE_SCHEMA)

    result = {row["category"]: row["records_count"] for row in aggregate_rejection_reasons(df).collect()}

    assert result == {"INVALID_EVENT_ID": 1, "INVALID_TRACK_ID": 1}
    metric_types = {row["metric_type"] for row in aggregate_rejection_reasons(df).collect()}
    assert metric_types == {"REJECTION_REASON"}


def test_aggregate_timestamp_classifications_counts_per_category(spark):
    now = _now()
    df = spark.createDataFrame([
        {"_ingested_at": now, "timestamp_classification": "ON_TIME"},
        {"_ingested_at": now, "timestamp_classification": "ON_TIME"},
        {"_ingested_at": now, "timestamp_classification": "LATE"},
    ], SILVER_SCHEMA)

    result = {row["category"]: row["records_count"] for row in aggregate_timestamp_classifications(df).collect()}

    assert result == {"ON_TIME": 2, "LATE": 1}
