from pyspark.sql import functions as F

# Nome de arquivo gerado pelo producer: eventos_com_caos_2026-09-16T085230-0300.json
FILENAME_TIMESTAMP_PATTERN = r"eventos_com_caos_(\d{4}-\d{2}-\d{2}T\d{6}[+-]\d{4})\.json"
FILENAME_TIMESTAMP_FORMAT = "yyyy-MM-dd'T'HHmmssZ"


def aggregate_pipeline_run_health(pipeline_audit_batch_df):
    """Agrega pipeline_audit por dia/pipeline/task para o dashboard de saúde do pipeline."""
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
    """Agrega file_audit por dia/tabela de destino, medindo o atraso entre a geração do
    arquivo (timestamp no nome, gerado pelo producer) e o processamento (processed_at)."""
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
    """Agrega a quarentena por dia/motivo de rejeição (um registro pode ter múltiplos
    motivos concatenados em rejection_reason; cada motivo vira uma linha própria)."""
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
    """Agrega a Silver por dia/classificação de timestamp (ON_TIME/LATE/FUTURE/INVALID)."""
    return (
        silver_batch_df
        .withColumn("event_date", F.to_date("_ingested_at"))
        .groupBy("event_date", "timestamp_classification")
        .agg(F.count("*").alias("records_count"))
        .withColumnRenamed("timestamp_classification", "category")
        .withColumn("metric_type", F.lit("TIMESTAMP_CLASSIFICATION"))
        .select("event_date", "metric_type", "category", "records_count")
    )
