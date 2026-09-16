from datetime import datetime, timezone
from uuid import UUID

from pipeline.audit import build_audit_record, build_file_audit_records

# Testes sem SparkSession: build_audit_record/build_file_audit_records só montam
# dicts (a parte pura, extraída de PipelineAudit.write_batch/write_files), sem
# tocar em Delta.


def test_build_audit_record_defaults():
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    finished_at = started_at

    record = build_audit_record(
        run_id="run_1",
        pipeline_name="spotify_events_pipeline",
        task_name="transform_silver",
        target_table="catalog.silver.spotify_events",
        batch_id=1,
        started_at=started_at,
        finished_at=finished_at,
        status="SUCCESS",
        files_processed=2,
        records_read=10,
        records_inserted=8,
        schema_drift_records=1,
    )

    assert UUID(record["audit_id"])
    assert record["run_id"] == "run_1"
    assert record["status"] == "SUCCESS"
    assert record["records_rejected"] == 0
    assert record["error_message"] is None


def test_build_audit_record_failure_with_error():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = build_audit_record(
        run_id="run_1",
        pipeline_name="spotify_events_pipeline",
        task_name="ingest_bronze",
        target_table="catalog.bronze.spotify_events_raw",
        batch_id=-1,
        started_at=now,
        finished_at=now,
        status="FAILED",
        files_processed=0,
        records_read=0,
        records_inserted=0,
        schema_drift_records=0,
        records_rejected=5,
        error_message="boom",
    )
    assert record["status"] == "FAILED"
    assert record["records_rejected"] == 5
    assert record["error_message"] == "boom"


def test_build_file_audit_records():
    file_metrics = [
        {"source_file": "file_a.json", "records_read": 5, "schema_drift_records": 1},
        {"source_file": "file_b.json", "records_read": 3, "schema_drift_records": 0, "records_inserted": 2},
    ]

    records = build_file_audit_records(
        file_metrics=file_metrics,
        run_id="run_1",
        batch_id=1,
        target_table="catalog.bronze.spotify_events_raw",
        status="SUCCESS",
    )

    assert len(records) == 2
    for record in records:
        assert UUID(record["file_audit_id"])
        assert record["run_id"] == "run_1"

    # sem records_inserted explícito, e status SUCCESS, assume records_read
    assert records[0]["records_inserted"] == 5
    # com records_inserted explícito, usa o valor informado
    assert records[1]["records_inserted"] == 2


def test_build_file_audit_records_failure_defaults_to_zero_inserted():
    file_metrics = [{"source_file": "file_a.json", "records_read": 5, "schema_drift_records": 0}]
    records = build_file_audit_records(
        file_metrics=file_metrics,
        run_id="run_1",
        batch_id=1,
        target_table="catalog.bronze.spotify_events_raw",
        status="FAILED",
        error_message="boom",
    )
    assert records[0]["records_inserted"] == 0
    assert records[0]["error_message"] == "boom"


def test_build_file_audit_records_empty_input():
    # PipelineAudit.write_files só chama spark.createDataFrame(...) se a lista não
    # for vazia; aqui garantimos que a função pura já devolve [] sem erro.
    assert build_file_audit_records(
        file_metrics=[],
        run_id="run_1",
        batch_id=1,
        target_table="catalog.bronze.spotify_events_raw",
        status="SUCCESS",
    ) == []
