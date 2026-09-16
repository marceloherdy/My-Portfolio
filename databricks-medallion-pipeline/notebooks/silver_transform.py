import inspect
import os
import sys
from traceback import format_exc

# Databricks executa spark_python_task via exec(compile(...)) num kernel, sem
# definir __file__. O caminho real do arquivo continua acessível via co_filename.
_this_file = inspect.currentframe().f_code.co_filename
sys.path.append(os.path.join(os.path.dirname(_this_file), "..", "src"))

from databricks.sdk.runtime import spark
from delta.tables import DeltaTable
from pyspark.sql import functions as F

from pipeline.audit import PipelineAudit
from pipeline.metrics import compute_file_metrics
from pipeline.silver import build_quarantine_rows, dedupe_valid_records, normalize_batch

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
execution_started_at = audit.utc_now()


def process_batch(batch_df, batch_id):
    started_at = audit.utc_now()
    records_read = batch_df.count()
    normalized = normalize_batch(batch_df).cache()
    rejected = normalized.filter(F.col("rejection_reason") != "")
    valid = normalized.filter(F.col("rejection_reason") == "")
    records_rejected = rejected.count()
    schema_drift_records = normalized.filter(F.col("_rescued_data").isNotNull()).count()

    file_metrics = compute_file_metrics(
        normalized,
        extra_aggs={"records_inserted": F.sum(F.when(F.col("rejection_reason") == "", 1).otherwise(0))},
    )

    try:
        build_quarantine_rows(rejected).write.format("delta").mode("append").saveAsTable(quarantine_table)

        silver_batch = dedupe_valid_records(valid)

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

# Rastreado pelo Spark no driver, confiável independente de isolamento do
# foreachBatch (ver mesmo padrão em notebooks/ingest_bronze.py). recentProgress
# vem como dict neste runtime (Databricks Connect), não como objeto com atributos.
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

print(f"Transformação Silver concluída com sucesso para a tabela: {silver_table}")
