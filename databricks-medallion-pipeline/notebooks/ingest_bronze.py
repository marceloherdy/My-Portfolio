import inspect
import os
import sys
from datetime import datetime, timezone
from traceback import format_exc

# Databricks executa spark_python_task via exec(compile(...)) num kernel, sem
# definir __file__. O caminho real do arquivo continua acessível via co_filename.
_this_file = inspect.currentframe().f_code.co_filename
sys.path.append(os.path.join(os.path.dirname(_this_file), "..", "src"))

from databricks.sdk.runtime import spark
from pyspark.sql.functions import col, current_timestamp

from pipeline.audit import PipelineAudit
from pipeline.metrics import compute_file_metrics

# Caminhos de entrada, estado operacional e tabela de destino no Unity Catalog.
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
    started_at = audit.utc_now()
    records_read = batch_df.count()
    file_metrics = compute_file_metrics(batch_df)
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

# O foreachBatch roda isolado do processo principal neste cluster (Unity
# Catalog), então um contador Python global não sobrevive até aqui de forma
# confiável — usamos o progresso rastreado pelo próprio Spark no driver.
# recentProgress vem como dict neste runtime (Databricks Connect), não como
# objeto StreamingQueryProgress com atributos.
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

print(f"Ingestão Bronze concluída com sucesso para a tabela: {target_table}")