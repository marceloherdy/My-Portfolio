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
from pipeline.gold import aggregate_pipeline_run_health

source_table = "databricks_course_ws_new.ops.pipeline_audit"
gold_table = "databricks_course_ws_new.gold.pipeline_run_health"
checkpoint_path = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/gold_pipeline_run_health"
audit_table = "databricks_course_ws_new.ops.pipeline_audit"
file_audit_table = "databricks_course_ws_new.ops.file_audit"

gold_schema = """
    execution_date DATE,
    pipeline_name STRING,
    task_name STRING,
    runs_count BIGINT,
    success_count BIGINT,
    failed_count BIGINT,
    empty_runs_count BIGINT,
    avg_duration_sec DOUBLE,
    records_read_sum BIGINT,
    records_inserted_sum BIGINT,
    records_rejected_sum BIGINT,
    schema_drift_records_sum BIGINT
"""
spark.sql(f"CREATE TABLE IF NOT EXISTS {gold_table} ({gold_schema}) USING DELTA")

audit = PipelineAudit(
    spark=spark,
    pipeline_name="spotify_events_pipeline",
    task_name="gold_pipeline_run_health",
    target_table=gold_table,
    audit_table=audit_table,
    file_audit_table=file_audit_table,
)
audit.ensure_tables()
execution_started_at = audit.utc_now()


def process_batch(batch_df, batch_id):
    started_at = audit.utc_now()
    records_read = batch_df.count()
    delta = aggregate_pipeline_run_health(batch_df)
    records_inserted = delta.count()

    try:
        target = DeltaTable.forName(spark, gold_table)
        (
            target.alias("target")
            .merge(
                delta.alias("source"),
                "target.execution_date = source.execution_date "
                "AND target.pipeline_name = source.pipeline_name "
                "AND target.task_name = source.task_name",
            )
            .whenMatchedUpdate(
                set={
                    "runs_count": "target.runs_count + source.runs_count",
                    "success_count": "target.success_count + source.success_count",
                    "failed_count": "target.failed_count + source.failed_count",
                    "empty_runs_count": "target.empty_runs_count + source.empty_runs_count",
                    "avg_duration_sec": (
                        "(target.avg_duration_sec * target.runs_count + source.avg_duration_sec * source.runs_count) "
                        "/ (target.runs_count + source.runs_count)"
                    ),
                    "records_read_sum": "target.records_read_sum + source.records_read_sum",
                    "records_inserted_sum": "target.records_inserted_sum + source.records_inserted_sum",
                    "records_rejected_sum": "target.records_rejected_sum + source.records_rejected_sum",
                    "schema_drift_records_sum": "target.schema_drift_records_sum + source.schema_drift_records_sum",
                },
            )
            .whenNotMatchedInsertAll()
            .execute()
        )
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

print(f"Gold aggregation (pipeline run health) completed successfully for table: {gold_table}")
