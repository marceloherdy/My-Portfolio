from datetime import datetime, timezone
from traceback import format_exc

from databricks.sdk.runtime import spark
from pyspark.sql.functions import col, count, current_timestamp, sum as spark_sum, when
from utils.audit import PipelineAudit

# Caminhos de entrada, estado operacional e tabela de destino no Unity Catalog.
volume_path = "/Volumes/databricks_course_ws_new/landing/events_volume"
checkpoint_path = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/spotify_events"
schema_location = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/schema/spotify_events"
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
processed_batch_count = 0

# O Auto Loader identifica novos arquivos e mantém o schema persistido.
df_stream = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", schema_location)
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaEvolutionMode", "rescue")
    .load(volume_path)
)

# Adiciona metadados de auditoria para rastrear ingestão e arquivo de origem.
df_bronze = (
    df_stream
    .withColumn("_ingested_at", current_timestamp())
    .withColumn("_source_file", col("_metadata.file_path"))
)


def process_batch(batch_df, batch_id):
    """Grava um lote na Bronze e registra suas métricas de processamento."""
    global processed_batch_count
    processed_batch_count += 1
    started_at = audit.utc_now()
    records_read = batch_df.count()
    file_metrics = [
        row.asDict()
        for row in batch_df.groupBy("_source_file").agg(
            count("*").alias("records_read"),
            spark_sum(when(col("_rescued_data").isNotNull(), 1).otherwise(0)).alias("schema_drift_records"),
        ).withColumnRenamed("_source_file", "source_file").collect()
    ]
    files_processed = len(file_metrics)
    schema_drift_records = sum(metrics["schema_drift_records"] for metrics in file_metrics)

    try:
        (
            batch_df.write.format("delta")
            .mode("append")
            .option("txnAppId", "spotify_events_pipeline")
            .option("txnVersion", batch_id)
            .saveAsTable(target_table)
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
            records_inserted=records_read,
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


# Processa os arquivos disponíveis e registra uma linha de auditoria por lote.
query = (
    df_bronze.writeStream
    .foreachBatch(process_batch)
    .option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True)
    .start()
)

# Aguarda o encerramento do processamento incremental.
query.awaitTermination()

if processed_batch_count == 0:
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

print(f"Ingestão Bronze concluída com sucesso para a tabela: {target_table}")