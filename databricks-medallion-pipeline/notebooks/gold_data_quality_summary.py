import inspect
import os
import sys
from traceback import format_exc

# Databricks runs spark_python_task files through exec(compile(...)) in a kernel and
# does not define __file__. The real file path is still available via co_filename.
_this_file = inspect.currentframe().f_code.co_filename
sys.path.append(os.path.join(os.path.dirname(_this_file), "..", "src"))

from databricks.sdk.runtime import spark
from delta.tables import DeltaTable

from pipeline.audit import PipelineAudit
from pipeline.gold import aggregate_rejection_reasons, aggregate_timestamp_classifications

quarantine_table = "databricks_course_ws_new.silver.spotify_events_quarantine"
silver_table = "databricks_course_ws_new.silver.spotify_events"
gold_table = "databricks_course_ws_new.gold.data_quality_summary"
audit_table = "databricks_course_ws_new.ops.pipeline_audit"
file_audit_table = "databricks_course_ws_new.ops.file_audit"

gold_schema = """
    event_date DATE,
    metric_type STRING,
    category STRING,
    records_count BIGINT
"""
spark.sql(f"CREATE TABLE IF NOT EXISTS {gold_table} ({gold_schema}) USING DELTA")


def merge_delta(delta_df):
    """Additive upsert (sums records_count) into Gold, keyed by (event_date, metric_type, category)."""
    target = DeltaTable.forName(spark, gold_table)
    (
        target.alias("target")
        .merge(
            delta_df.alias("source"),
            "target.event_date = source.event_date "
            "AND target.metric_type = source.metric_type "
            "AND target.category = source.category",
        )
        .whenMatchedUpdate(set={"records_count": "target.records_count + source.records_count"})
        .whenNotMatchedInsertAll()
        .execute()
    )


def run_stream(task_name, source_table, aggregate_fn, checkpoint_path):
    """Run an incremental stream from a source table into Gold, with its own audit."""
    audit = PipelineAudit(
        spark=spark,
        pipeline_name="spotify_events_pipeline",
        task_name=task_name,
        target_table=gold_table,
        audit_table=audit_table,
        file_audit_table=file_audit_table,
    )
    audit.ensure_tables()
    execution_started_at = audit.utc_now()

    def process_batch(batch_df, batch_id):
        started_at = audit.utc_now()
        records_read = batch_df.count()
        delta = aggregate_fn(batch_df)
        records_inserted = delta.count()

        try:
            merge_delta(delta)
            finished_at = audit.utc_now()
            audit.write_batch(
                batch_id=batch_id,
                started_at=started_at,
                finished_at=finished_at,
                status="SUCCESS",
                files_processed=0,
                records_read=records_read,
                records_inserted=records_inserted,
                schema_drift_records=0,
            )
        except Exception:
            finished_at = audit.utc_now()
            error_message = format_exc()[-4000:]
            audit.write_batch(
                batch_id=batch_id,
                started_at=started_at,
                finished_at=finished_at,
                status="FAILED",
                files_processed=0,
                records_read=records_read,
                records_inserted=0,
                schema_drift_records=0,
                error_message=error_message,
            )
            raise

    source = spark.readStream.table(source_table)
    query = (
        source.writeStream
        .foreachBatch(process_batch)
        .option("checkpointLocation", checkpoint_path)
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()

    # Tracked by Spark on the driver, so it is reliable regardless of foreachBatch
    # process isolation (same pattern as notebooks/ingest_bronze.py). recentProgress
    # is a dict in this runtime (Databricks Connect), not an object with attributes.
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


run_stream(
    task_name="gold_quality_rejection_reasons",
    source_table=quarantine_table,
    aggregate_fn=aggregate_rejection_reasons,
    checkpoint_path="/Volumes/databricks_course_ws_new/ops/checkpoints_volume/gold_quality_rejection_reasons",
)

run_stream(
    task_name="gold_quality_timestamp_classification",
    source_table=silver_table,
    aggregate_fn=aggregate_timestamp_classifications,
    checkpoint_path="/Volumes/databricks_course_ws_new/ops/checkpoints_volume/gold_quality_timestamp_classification",
)

print(f"Gold aggregation (data quality) completed successfully for table: {gold_table}")
