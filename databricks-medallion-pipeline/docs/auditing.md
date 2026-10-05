**English** | [Português](auditing.pt-BR.md)

# Pipeline Auditing

## Purpose

The pipeline records operational metrics for every stage so runs can be monitored, failures diagnosed and processed files traced.

Auditing lives in the `ops` schema of the project catalog and has two levels:

- `pipeline_audit`: one row per batch, or per execution that found no new data.
- `file_audit`: one row per file processed in each batch.

## Tables

### `pipeline_audit`

Aggregated view of an execution. Use it to follow the result and the volume processed per batch.

| Column | Description |
| --- | --- |
| `audit_id` | Unique identifier of the audit record. |
| `run_id` | Identifier of the pipeline execution. Groups the records of the same execution. |
| `pipeline_name` | Name of the pipeline that ran. |
| `task_name` | Name of the task that did the processing. |
| `target_table` | Table that received the processed data. |
| `batch_id` | Batch identifier. `-1` means an execution with no new data (the Gold business tasks use `0`, because each run rebuilds the table). |
| `started_at` | Processing start time. |
| `finished_at` | Processing end time. |
| `status` | Outcome of the execution. Currently `SUCCESS` or `FAILED`. |
| `files_processed` | Number of files processed in the batch. |
| `records_read` | Number of records read. |
| `records_inserted` | Number of records written to the target. |
| `records_rejected` | Number of rejected records. |
| `schema_drift_records` | Number of records with a schema change or inconsistency. |
| `error_message` | Error details, when the execution fails. |

### `file_audit`

Detailed view of the processing. Use it to find out which files were processed and which metrics each file produced.

| Column | Description |
| --- | --- |
| `file_audit_id` | Unique identifier of the file audit record. |
| `run_id` | Identifier of the related execution. |
| `batch_id` | Batch in which the file was processed. |
| `source_file` | Full path of the file in the source volume. |
| `target_table` | Target table. |
| `processed_at` | Time the processing was recorded. |
| `status` | Outcome of the file processing. Currently `SUCCESS` or `FAILED`. |
| `records_read` | Records read from the file. |
| `records_inserted` | Records inserted into the target table. |
| `schema_drift_records` | Records affected by schema drift and routed to `_rescued_data`. |
| `error_message` | Error details, when the processing fails. |

## Behavior notes

- Ingestion uses Auto Loader with `availableNow=True`.
- When there is nothing new to process (files in Bronze, pending records in Silver or Gold), each layer writes a `pipeline_audit` row with zero counters and `batch_id = -1`.
- The `gold_aggregation` job writes to `pipeline_audit` under four `task_name` values (`gold_pipeline_run_health`, `gold_file_processing_latency`, `gold_quality_rejection_reasons` and `gold_quality_timestamp_classification`; the bundle task `data_quality_summary` runs two independent streams, each with its own audit). The `gold_business` job writes one row per table under `gold_business_<table>`. None of the Gold tasks write to `file_audit`, because they aggregate tables, not files.
- The Auto Loader state and schema live in operational volumes separate from the landing volume.
- The checkpoint and the Delta transaction make a run safe to repeat without duplicating a batch.
- The Bronze task compares the table row count before and after each write. If the number of rows written differs from the number read (for example, Delta discarded the write as a replay after the checkpoints were deleted), the batch is recorded as `FAILED` instead of `SUCCESS`.
- Records with schema changes are preserved in the `_rescued_data` column of the Bronze table.

## Useful queries

The queries use `your_catalog` as a placeholder for the catalog of the project; replace it with yours (in this repository, `databricks_course_ws_new`).

### Latest executions

```sql
SELECT
    run_id,
    pipeline_name,
    task_name,
    target_table,
    batch_id,
    status,
    files_processed,
    records_read,
    records_inserted,
    schema_drift_records,
    started_at,
    finished_at
FROM your_catalog.ops.pipeline_audit
ORDER BY finished_at DESC;
```

### Files processed in the latest execution

```sql
SELECT
    run_id,
    batch_id,
    source_file,
    status,
    records_read,
    records_inserted,
    schema_drift_records,
    processed_at
FROM your_catalog.ops.file_audit
WHERE run_id = (
    SELECT run_id
    FROM your_catalog.ops.pipeline_audit
    ORDER BY finished_at DESC
    LIMIT 1
)
ORDER BY processed_at DESC;
```

### Processing failures

```sql
SELECT
    run_id,
    batch_id,
    source_file,
    target_table,
    error_message,
    processed_at
FROM your_catalog.ops.file_audit
WHERE status = 'FAILED'
ORDER BY processed_at DESC;
```

### Executions with no new data

```sql
SELECT
    run_id,
    finished_at,
    status
FROM your_catalog.ops.pipeline_audit
WHERE batch_id = -1
ORDER BY finished_at DESC;
```
