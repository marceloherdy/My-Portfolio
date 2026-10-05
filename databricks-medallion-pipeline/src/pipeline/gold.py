from pyspark.sql import functions as F
from pyspark.sql.window import Window

# Timestamp classifications included in the business metrics: FUTURE and INVALID
# would distort the time series, so they are left out.
BUSINESS_TIMESTAMP_CLASSIFICATIONS = ["ON_TIME", "LATE"]

# Field affected by each quarantine rejection reason (see silver.py::normalize_batch).
REJECTION_REASON_TO_FIELD = {
    "INVALID_EVENT_ID": "event_id",
    "INVALID_TRACK_ID": "track_id",
    "INVALID_PLATFORM": "platform",
    "INVALID_DURATION": "duration_played_sec",
    "NEGATIVE_DURATION": "duration_played_sec",
    "INVALID_TIMESTAMP": "timestamp",
}

# File name written by the producer: eventos_com_caos_2026-09-16T085230-0300.json
FILENAME_TIMESTAMP_PATTERN = r"eventos_com_caos_(\d{4}-\d{2}-\d{2}T\d{6}[+-]\d{4})\.json"
FILENAME_TIMESTAMP_FORMAT = "yyyy-MM-dd'T'HHmmssZ"


def aggregate_pipeline_run_health(pipeline_audit_batch_df):
    """Aggregate pipeline_audit by day/pipeline/task for the pipeline health dashboard."""
    return (
        pipeline_audit_batch_df
        .withColumn("execution_date", F.to_date("started_at"))
        .withColumn(
            "duration_sec",
            F.col("finished_at").cast("long") - F.col("started_at").cast("long"),
        )
        .groupBy("execution_date", "pipeline_name", "task_name")
        .agg(
            F.count("*").alias("runs_count"),
            F.sum(F.when(F.col("status") == "SUCCESS", 1).otherwise(0)).alias("success_count"),
            F.sum(F.when(F.col("status") == "FAILED", 1).otherwise(0)).alias("failed_count"),
            F.sum(F.when(F.col("batch_id") == -1, 1).otherwise(0)).alias("empty_runs_count"),
            F.avg("duration_sec").alias("avg_duration_sec"),
            F.sum("records_read").alias("records_read_sum"),
            F.sum("records_inserted").alias("records_inserted_sum"),
            F.sum("records_rejected").alias("records_rejected_sum"),
            F.sum("schema_drift_records").alias("schema_drift_records_sum"),
        )
    )


def aggregate_file_processing_latency(file_audit_batch_df):
    """Aggregate file_audit by day/target table, measuring the delay between file generation
    (the timestamp in the file name, written by the producer) and processing (processed_at)."""
    extracted = (
        file_audit_batch_df
        .withColumn(
            "_file_timestamp_str",
            F.regexp_extract("source_file", FILENAME_TIMESTAMP_PATTERN, 1),
        )
        .withColumn("_file_timestamp", F.to_timestamp("_file_timestamp_str", FILENAME_TIMESTAMP_FORMAT))
        .withColumn(
            "latency_sec",
            F.col("processed_at").cast("long") - F.col("_file_timestamp").cast("long"),
        )
        .withColumn("processed_date", F.to_date("processed_at"))
    )
    return (
        extracted
        .groupBy("processed_date", "target_table")
        .agg(
            F.count("*").alias("files_count"),
            F.avg("latency_sec").alias("avg_latency_sec"),
            F.max("latency_sec").alias("max_latency_sec"),
            F.sum(F.when(F.col("status") == "FAILED", 1).otherwise(0)).alias("failed_files_count"),
        )
    )


def aggregate_rejection_reasons(quarantine_batch_df):
    """Aggregate the quarantine by day/rejection reason (a record can have several reasons
    concatenated in rejection_reason; each reason becomes its own row)."""
    return (
        quarantine_batch_df
        .withColumn("event_date", F.to_date("rejected_at"))
        .withColumn("category", F.explode(F.split(F.col("rejection_reason"), "; ")))
        .filter(F.col("category") != "")
        .groupBy("event_date", "category")
        .agg(F.count("*").alias("records_count"))
        .withColumn("metric_type", F.lit("REJECTION_REASON"))
        .select("event_date", "metric_type", "category", "records_count")
    )


def aggregate_timestamp_classifications(silver_batch_df):
    """Aggregate Silver by day/timestamp classification (ON_TIME/LATE/FUTURE/INVALID)."""
    return (
        silver_batch_df
        .withColumn("event_date", F.to_date("_ingested_at"))
        .groupBy("event_date", "timestamp_classification")
        .agg(F.count("*").alias("records_count"))
        .withColumnRenamed("timestamp_classification", "category")
        .withColumn("metric_type", F.lit("TIMESTAMP_CLASSIFICATION"))
        .select("event_date", "metric_type", "category", "records_count")
    )


def _business_events(silver_df):
    """Silver events eligible for the business metrics, with the event date (event_date)."""
    return (
        silver_df
        .filter(F.col("timestamp_classification").isin(BUSINESS_TIMESTAMP_CLASSIFICATIONS))
        .withColumn("event_date", F.to_date("event_timestamp"))
    )


def compute_track_popularity(silver_df):
    """Plays, duration and distinct users per day/track."""
    return (
        _business_events(silver_df)
        .groupBy("event_date", "track_id")
        .agg(
            F.count("*").alias("plays_count"),
            F.sum("duration_played_sec").alias("total_duration_sec"),
            F.round(F.avg("duration_played_sec"), 2).alias("avg_duration_sec"),
            F.countDistinct("user_id").alias("unique_users"),
        )
    )


def compute_device_usage(silver_df):
    """Plays and duration per day/device. A null device_type becomes 'unknown' (the field only
    exists on records with schema drift) and share_pct is the share of the day's total plays."""
    per_day = Window.partitionBy("event_date")
    return (
        _business_events(silver_df)
        .withColumn("device_type", F.coalesce(F.col("device_type"), F.lit("unknown")))
        .groupBy("event_date", "device_type")
        .agg(
            F.count("*").alias("plays_count"),
            F.sum("duration_played_sec").alias("total_duration_sec"),
            F.round(F.avg("duration_played_sec"), 2).alias("avg_duration_sec"),
        )
        .withColumn("share_pct", F.round(F.col("plays_count") * 100 / F.sum("plays_count").over(per_day), 2))
    )


def compute_user_activity(silver_df):
    """Activity per day/identified user (events without user_id are excluded)."""
    return (
        _business_events(silver_df)
        .filter(F.col("user_id").isNotNull())
        .groupBy("event_date", "user_id")
        .agg(
            F.count("*").alias("plays_count"),
            F.sum("duration_played_sec").alias("total_duration_sec"),
            F.countDistinct("track_id").alias("distinct_tracks"),
        )
    )


def compute_business_kpi(silver_df):
    """Daily KPIs, including the coverage of user_id and device_type."""
    return (
        _business_events(silver_df)
        .groupBy("event_date")
        .agg(
            F.count("*").alias("plays_count"),
            F.countDistinct("user_id").alias("active_users"),
            F.sum("duration_played_sec").alias("total_duration_sec"),
            F.round(F.avg("duration_played_sec"), 2).alias("avg_duration_sec"),
            F.round(F.avg(F.col("user_id").isNull().cast("int")) * 100, 2).alias("pct_without_user"),
            F.round(F.avg(F.col("device_type").isNull().cast("int")) * 100, 2).alias("pct_without_device"),
        )
    )


def _missing_field_counts(silver_df, field, issue):
    return (
        silver_df
        .filter(F.col(field).isNull())
        .groupBy("event_date")
        .agg(F.count("*").alias("records_count"))
        .withColumn("field", F.lit(field))
        .withColumn("issue", F.lit(issue))
        .withColumn("impact", F.lit("DEGRADED"))
    )


def compute_field_quality(silver_df, quarantine_df):
    """Which fields hurt the data the most, per ingestion day.

    - ``LOSS``: quarantine rejection reasons mapped to the field (the record was lost).
    - ``DEGRADED``: null fields on records that stay in Silver (user_id, device_type).

    ``total_records`` is Silver + quarantine for the day (records that reached Silver, with
    duplicates already removed). A record can have more than one problem, so the per-field
    percentages do not add up to 100%.
    """
    silver = silver_df.withColumn("event_date", F.to_date("_ingested_at"))
    quarantine = quarantine_df.withColumn("event_date", F.to_date("_ingested_at"))

    field_map = F.create_map(*[F.lit(x) for pair in REJECTION_REASON_TO_FIELD.items() for x in pair])
    losses = (
        quarantine
        .withColumn("issue", F.explode(F.split(F.col("rejection_reason"), "; ")))
        .filter(F.col("issue") != "")
        .withColumn("field", F.coalesce(field_map[F.col("issue")], F.lit("unknown")))
        .groupBy("event_date", "field", "issue")
        .agg(F.count("*").alias("records_count"))
        .withColumn("impact", F.lit("LOSS"))
    )

    issues = (
        losses
        .unionByName(_missing_field_counts(silver, "user_id", "MISSING_USER_ID"))
        .unionByName(_missing_field_counts(silver, "device_type", "MISSING_DEVICE_TYPE"))
    )
    totals = (
        silver.groupBy("event_date").agg(F.count("*").alias("n"))
        .unionByName(quarantine.groupBy("event_date").agg(F.count("*").alias("n")))
        .groupBy("event_date")
        .agg(F.sum("n").alias("total_records"))
    )
    return (
        issues
        .join(totals, "event_date")
        .withColumn("pct_of_total", F.round(F.col("records_count") * 100 / F.col("total_records"), 2))
        .select("event_date", "field", "issue", "impact", "records_count", "total_records", "pct_of_total")
    )
