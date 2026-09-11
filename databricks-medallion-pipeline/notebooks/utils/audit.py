from datetime import datetime, timezone
from uuid import uuid4

from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


class PipelineAudit:
    """Persiste métricas de execução e de arquivos em tabelas Delta."""

    pipeline_schema = StructType([
        StructField("audit_id", StringType(), False),
        StructField("run_id", StringType(), False),
        StructField("pipeline_name", StringType(), False),
        StructField("task_name", StringType(), False),
        StructField("target_table", StringType(), False),
        StructField("batch_id", LongType(), False),
        StructField("started_at", TimestampType(), False),
        StructField("finished_at", TimestampType(), False),
        StructField("status", StringType(), False),
        StructField("files_processed", IntegerType(), False),
        StructField("records_read", LongType(), False),
        StructField("records_inserted", LongType(), False),
        StructField("records_rejected", LongType(), False),
        StructField("schema_drift_records", LongType(), False),
        StructField("error_message", StringType(), True),
    ])

    file_schema = StructType([
        StructField("file_audit_id", StringType(), False),
        StructField("run_id", StringType(), False),
        StructField("batch_id", LongType(), False),
        StructField("source_file", StringType(), False),
        StructField("target_table", StringType(), False),
        StructField("processed_at", TimestampType(), False),
        StructField("status", StringType(), False),
        StructField("records_read", LongType(), False),
        StructField("records_inserted", LongType(), False),
        StructField("schema_drift_records", LongType(), False),
        StructField("error_message", StringType(), True),
    ])

    def __init__(self, spark, pipeline_name, task_name, target_table,
                 audit_table, file_audit_table):
        self.spark = spark
        self.pipeline_name = pipeline_name
        self.task_name = task_name
        self.target_table = target_table
        self.audit_table = audit_table
        self.file_audit_table = file_audit_table
        self.run_id = str(uuid4())

    def ensure_tables(self):
        self.spark.sql(f"""
            CREATE TABLE IF NOT EXISTS {self.audit_table} (
                audit_id STRING,
                run_id STRING,
                pipeline_name STRING,
                task_name STRING,
                target_table STRING,
                batch_id BIGINT,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                status STRING,
                files_processed INT,
                records_read BIGINT,
                records_inserted BIGINT,
                records_rejected BIGINT,
                schema_drift_records BIGINT,
                error_message STRING
            ) USING DELTA
        """)
        self.spark.sql(f"""
            CREATE TABLE IF NOT EXISTS {self.file_audit_table} (
                file_audit_id STRING,
                run_id STRING,
                batch_id BIGINT,
                source_file STRING,
                target_table STRING,
                processed_at TIMESTAMP,
                status STRING,
                records_read BIGINT,
                records_inserted BIGINT,
                schema_drift_records BIGINT,
                error_message STRING
            ) USING DELTA
        """)

    def write_batch(self, batch_id, started_at, finished_at, status,
                    files_processed, records_read, records_inserted,
                    schema_drift_records, error_message=None):
        records = [{
            "audit_id": str(uuid4()),
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "task_name": self.task_name,
            "target_table": self.target_table,
            "batch_id": batch_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "files_processed": files_processed,
            "records_read": records_read,
            "records_inserted": records_inserted,
            "records_rejected": 0,
            "schema_drift_records": schema_drift_records,
            "error_message": error_message,
        }]
        self.spark.createDataFrame(records, self.pipeline_schema).write.format("delta").mode("append").saveAsTable(self.audit_table)

    def write_files(self, file_metrics, batch_id, status, error_message=None):
        processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        records = [{
            "file_audit_id": str(uuid4()),
            "run_id": self.run_id,
            "batch_id": batch_id,
            "source_file": metrics["source_file"],
            "target_table": self.target_table,
            "processed_at": processed_at,
            "status": status,
            "records_read": metrics["records_read"],
            "records_inserted": metrics["records_read"] if status == "SUCCESS" else 0,
            "schema_drift_records": metrics["schema_drift_records"],
            "error_message": error_message,
        } for metrics in file_metrics]
        if records:
            self.spark.createDataFrame(records, self.file_schema).write.format("delta").mode("append").saveAsTable(self.file_audit_table)

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc).replace(tzinfo=None)
