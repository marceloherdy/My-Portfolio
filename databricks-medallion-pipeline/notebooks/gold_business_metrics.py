import inspect
import os
import sys
from traceback import format_exc

# Databricks executa spark_python_task via exec(compile(...)) num kernel, sem
# definir __file__. O caminho real do arquivo continua acessível via co_filename.
_this_file = inspect.currentframe().f_code.co_filename
sys.path.append(os.path.join(os.path.dirname(_this_file), "..", "src"))

from databricks.sdk.runtime import spark

from pipeline.audit import PipelineAudit
from pipeline.gold import (
    compute_business_kpi,
    compute_device_usage,
    compute_field_quality,
    compute_track_popularity,
    compute_user_activity,
)

catalog = "databricks_course_ws_new"
silver_table = f"{catalog}.silver.spotify_events"
quarantine_table = f"{catalog}.silver.spotify_events_quarantine"
audit_table = f"{catalog}.ops.pipeline_audit"
file_audit_table = f"{catalog}.ops.file_audit"

# Diferente das Gold de auditoria (incrementais e aditivas), estas tabelas são
# recalculadas por inteiro a cada execução: a Silver sofre MERGE com UPDATE (um
# readStream falharia) e métricas como unique_users/distinct_tracks não são
# somáveis entre execuções. O volume é pequeno e o overwrite Delta é atômico.
gold_tables = {
    "track_popularity_daily": lambda silver, quarantine: compute_track_popularity(silver),
    "device_usage_daily": lambda silver, quarantine: compute_device_usage(silver),
    "user_activity_daily": lambda silver, quarantine: compute_user_activity(silver),
    "business_kpi_daily": lambda silver, quarantine: compute_business_kpi(silver),
    "field_quality": compute_field_quality,
}


def rebuild_table(name, compute_fn):
    """Recalcula uma tabela Gold por inteiro a partir da Silver/quarentena, com auditoria própria."""
    target_table = f"{catalog}.gold.{name}"
    audit = PipelineAudit(
        spark=spark,
        pipeline_name="spotify_events_pipeline",
        task_name=f"gold_business_{name}",
        target_table=target_table,
        audit_table=audit_table,
        file_audit_table=file_audit_table,
    )
    audit.ensure_tables()
    started_at = audit.utc_now()

    silver_df = spark.table(silver_table)
    quarantine_df = spark.table(quarantine_table)
    records_read = silver_df.count()

    if records_read == 0:
        audit.write_batch(
            batch_id=-1, started_at=started_at, finished_at=audit.utc_now(), status="SUCCESS",
            files_processed=0, records_read=0, records_inserted=0, schema_drift_records=0,
        )
        return

    try:
        result_df = compute_fn(silver_df, quarantine_df)
        (
            result_df.write.format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(target_table)
        )
        records_inserted = spark.table(target_table).count()
        audit.write_batch(
            batch_id=0, started_at=started_at, finished_at=audit.utc_now(), status="SUCCESS",
            files_processed=0, records_read=records_read, records_inserted=records_inserted,
            schema_drift_records=0,
        )
    except Exception:
        audit.write_batch(
            batch_id=0, started_at=started_at, finished_at=audit.utc_now(), status="FAILED",
            files_processed=0, records_read=records_read, records_inserted=0,
            schema_drift_records=0, error_message=format_exc()[-4000:],
        )
        raise


for table_name, compute in gold_tables.items():
    rebuild_table(table_name, compute)

print(f"Agregação Gold (métricas de negócio) concluída com sucesso: {', '.join(gold_tables)}")
