import inspect
import os
import sys
from datetime import datetime, timezone
from traceback import format_exc

# Databricks runs spark_python_task files through exec(compile(...)) in a kernel and
# does not define __file__. The real file path is still available via co_filename.
_this_file = inspect.currentframe().f_code.co_filename
sys.path.append(os.path.join(os.path.dirname(_this_file), "..", "src"))

from databricks.sdk.runtime import spark
from pyspark.sql.functions import col, current_timestamp

from pipeline.audit import PipelineAudit
from pipeline.metrics import compute_file_metrics

# Input path, operational state and target table in Unity Catalog.
volume_path = "/Volumes/databricks_course_ws_new/landing/events_volume"
checkpoint_path = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/spotify_events_v2"
schema_location = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/schema/spotify_events_v2"
target_table = "databricks_course_ws_new.bronze.spotify_events_raw"
audit_table = "databricks_course_ws_new.ops.pipeline_audit"
file_audit_table = "databricks_course_ws_new.ops.file_audit"
audit = PipelineAudit(
    spark=spark,
    pipeline_name="spotify_events_pipeline",
    task_name="ingest_bronze",
    target_table=target_table,
    audit_table=audit_table,
    file_audit_table=file_audit_table,
)
audit.ensure_tables()
execution_started_at = audit.utc_now()

# Auto Loader discovers new files and keeps the schema persisted.
df_stream = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", schema_location)
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaEvolutionMode", "rescue")
    .load(volume_path)
)

# Adds audit metadata to trace the ingestion time and the source file.
df_bronze = (
    df_stream
    .withColumn("_ingested_at", current_timestamp())
    .withColumn("_source_file", col("_metadata.file_path"))
)


def bronze_row_count():
    """Current Bronze row count (0 if the table does not exist yet, before the first write)."""
    return spark.table(target_table).count() if spark.catalog.tableExists(target_table) else 0


def process_batch(batch_df, batch_id):
    """Write a batch to Bronze and record its processing metrics."""
    started_at = audit.utc_now()
    records_read = batch_df.count()
    file_metrics = compute_file_metrics(batch_df)
    files_processed = len(file_metrics)
    schema_drift_records = sum(metrics["schema_drift_records"] for metrics in file_metrics)

    try:
        rows_before = bronze_row_count()
        (
            batch_df.write.format("delta")
            .mode("append")
            .option("txnAppId", "spotify_events_pipeline")
            .option("txnVersion", batch_id)
            .saveAsTable(target_table)
        )
        records_inserted = bronze_row_count() - rows_before
        # Delta silently discards a write whose txnVersion it has already seen (idempotency),
        # for example after the checkpoints are deleted without dropping the table. Without
        # this check the audit would record SUCCESS with "inserted" records that were never written.
        if records_inserted != records_read:
            raise RuntimeError(
                f"Bronze wrote {records_inserted} rows, but batch {batch_id} read {records_read}. "
                "If the checkpoints were deleted, drop the Bronze table (see CLAUDE.md, 'Reset do pipeline')."
            )
        audit.write_files(file_metrics, batch_id, "SUCCESS")
        finished_at = audit.utc_now()
        audit.write_batch(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            status="SUCCESS",
            files_processed=files_processed,
            records_read=records_read,
            records_inserted=records_inserted,
            schema_drift_records=schema_drift_records,
        )
    except Exception:
        finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        error_message = format_exc()[-4000:]
        audit.write_files(file_metrics, batch_id, "FAILED", error_message)
        audit.write_batch(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            status="FAILED",
            files_processed=files_processed,
            records_read=records_read,
            records_inserted=0,
            schema_drift_records=schema_drift_records,
            error_message=error_message,
        )
        raise


# Process the available files and record one audit row per batch.
query = (
    df_bronze.writeStream
    .foreachBatch(process_batch)
    .option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True)
    .start()
)

# Wait for the incremental processing to finish.
query.awaitTermination()

# foreachBatch runs isolated from the main process on this Unity Catalog cluster,
# so a global Python counter would not reliably survive until here; use the
# progress tracked by Spark on the driver instead. recentProgress is a dict in
# this runtime (Databricks Connect), not a StreamingQueryProgress object with
# attributes.
had_new_data = any(progress["numInputRows"] > 0 for progress in query.recentProgress)

if not had_new_data:
    execution_finished_at = audit.utc_now()
    audit.write_batch(
        batch_id=-1,
        started_at=execution_started_at,
        finished_at=execution_finished_at,
        status="SUCCESS",
        files_processed=0,
        records_read=0,
        records_inserted=0,
        schema_drift_records=0,
    )

print(f"Bronze ingestion completed successfully for table: {target_table}")