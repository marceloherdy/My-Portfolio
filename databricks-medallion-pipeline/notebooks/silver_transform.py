from traceback import format_exc

from databricks.sdk.runtime import spark
from delta.tables import DeltaTable
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from utils.audit import PipelineAudit

bronze_table = "databricks_course_ws_new.bronze.spotify_events_raw"
silver_table = "databricks_course_ws_new.silver.spotify_events"
quarantine_table = "databricks_course_ws_new.silver.spotify_events_quarantine"
checkpoint_path = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/spotify_events_silver_v4"
audit_table = "databricks_course_ws_new.ops.pipeline_audit"
file_audit_table = "databricks_course_ws_new.ops.file_audit"

silver_schema = """
    event_id STRING,
    user_id STRING,
    track_id STRING,
    platform STRING,
    device_type STRING,
    duration_played_sec INT,
    event_timestamp TIMESTAMP,
    timestamp_classification STRING,
    _rescued_data STRING,
    _ingested_at TIMESTAMP,
    _source_file STRING
"""

quarantine_schema = """
    event_id STRING,
    batch_id STRING,
    user_id STRING,
    track_id STRING,
    platform STRING,
    device_type STRING,
    duration_played_sec STRING,
    timestamp STRING,
    _rescued_data STRING,
    _ingested_at TIMESTAMP,
    _source_file STRING,
    rejection_reason STRING,
    rejected_at TIMESTAMP
"""

spark.sql(f"CREATE TABLE IF NOT EXISTS {silver_table} ({silver_schema}) USING DELTA")
spark.sql(f"CREATE TABLE IF NOT EXISTS {quarantine_table} ({quarantine_schema}) USING DELTA")

audit = PipelineAudit(
    spark=spark,
    pipeline_name="spotify_events_pipeline",
    task_name="transform_silver",
    target_table=silver_table,
    audit_table=audit_table,
    file_audit_table=file_audit_table,
)
audit.ensure_tables()


def normalize_batch(batch_df):
    current_time = F.current_timestamp()
    normalized = (
        batch_df
        .withColumn("event_id", F.trim(F.col("event_id")))
        .withColumn("track_id", F.trim(F.col("track_id")))
        .withColumn("platform", F.trim(F.col("platform")))
        .withColumn("duration_played_sec_int", F.expr("try_cast(duration_played_sec AS INT)"))
        .withColumn(
            "event_timestamp_parsed",
            F.to_timestamp("timestamp", "yyyy-MM-dd'T'HH:mm:ssZ"),
        )
        .withColumn(
            "rejection_reason",
            F.concat_ws(
                "; ",
                F.when(F.col("event_id").isNull() | (F.col("event_id") == ""), "INVALID_EVENT_ID"),
                F.when(F.col("track_id").isNull() | (F.col("track_id") == ""), "INVALID_TRACK_ID"),
                F.when(F.col("platform").isNull() | (F.col("platform") == ""), "INVALID_PLATFORM"),
                F.when(F.col("duration_played_sec_int").isNull(), "INVALID_DURATION"),
                F.when(F.col("duration_played_sec_int") < 0, "NEGATIVE_DURATION"),
                F.when(F.col("event_timestamp_parsed").isNull(), "INVALID_TIMESTAMP"),
            ),
        )
        .withColumn(
            "timestamp_classification",
            F.when(F.col("event_timestamp_parsed").isNull(), "INVALID")
            .when(F.col("event_timestamp_parsed") > current_time, "FUTURE")
            .when(F.col("event_timestamp_parsed") < current_time - F.expr("INTERVAL 1 DAY"), "LATE")
            .otherwise("ON_TIME"),
        )
    )
    return normalized


def process_batch(batch_df, batch_id):
    started_at = audit.utc_now()
    records_read = batch_df.count()
    normalized = normalize_batch(batch_df).cache()
    rejected = normalized.filter(F.col("rejection_reason") != "")
    valid = normalized.filter(F.col("rejection_reason") == "")
    records_rejected = rejected.count()
    schema_drift_records = normalized.filter(F.col("_rescued_data").isNotNull()).count()

    file_metrics = [
        row.asDict()
        for row in normalized.groupBy("_source_file").agg(
            F.count("*").alias("records_read"),
            F.sum(F.when(F.col("rejection_reason") == "", 1).otherwise(0)).alias("records_inserted"),
            F.sum(F.when(F.col("_rescued_data").isNotNull(), 1).otherwise(0)).alias("schema_drift_records"),
        ).withColumnRenamed("_source_file", "source_file").collect()
    ]

    try:
        rejected.select(
            "event_id", "batch_id", "user_id", "track_id", "platform", "device_type",
            "duration_played_sec", "timestamp", "_rescued_data", "_ingested_at", "_source_file",
            "rejection_reason",
        ).withColumn("rejected_at", F.current_timestamp()).write.format("delta").mode("append").saveAsTable(quarantine_table)

        rank_window = Window.partitionBy("event_id").orderBy(
            F.col("_ingested_at").desc(),
            F.col("_source_file").desc(),
        )
        silver_batch = (
            valid
            .withColumn("_row_number", F.row_number().over(rank_window))
            .filter(F.col("_row_number") == 1)
            .select(
                "event_id", "user_id", "track_id", "platform", "device_type",
                F.col("duration_played_sec_int").alias("duration_played_sec"),
                F.col("event_timestamp_parsed").alias("event_timestamp"),
                "timestamp_classification", "_rescued_data", "_ingested_at", "_source_file",
            )
        )

        target = DeltaTable.forName(spark, silver_table)
        (
            target.alias("target")
            .merge(silver_batch.alias("source"), "target.event_id = source.event_id")
            .whenMatchedUpdate(
                condition="source._ingested_at > target._ingested_at OR (source._ingested_at = target._ingested_at AND source._source_file > target._source_file)",
                set={column: f"source.{column}" for column in silver_batch.columns},
            )
            .whenNotMatchedInsert(
                values={column: f"source.{column}" for column in silver_batch.columns},
            )
            .execute()
        )

        records_inserted = silver_batch.count()
        finished_at = audit.utc_now()
        audit.write_files(file_metrics, batch_id, "SUCCESS")
        audit.write_batch(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            status="SUCCESS",
            files_processed=len(file_metrics),
            records_read=records_read,
            records_inserted=records_inserted,
            records_rejected=records_rejected,
            schema_drift_records=schema_drift_records,
        )
    except Exception:
        error_message = format_exc()[-4000:]
        finished_at = audit.utc_now()
        audit.write_files(file_metrics, batch_id, "FAILED", error_message)
        audit.write_batch(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            status="FAILED",
            files_processed=len(file_metrics),
            records_read=records_read,
            records_inserted=0,
            records_rejected=records_rejected,
            schema_drift_records=schema_drift_records,
            error_message=error_message,
        )
        raise
    finally:
        normalized.unpersist()


source = spark.readStream.table(bronze_table)
query = (
    source.writeStream
    .foreachBatch(process_batch)
    .option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True)
    .start()
)
query.awaitTermination()

print(f"Transformação Silver concluída com sucesso para a tabela: {silver_table}")
