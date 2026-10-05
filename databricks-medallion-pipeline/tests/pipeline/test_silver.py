from datetime import datetime, timedelta, timezone

import pytest
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from pipeline.silver import build_quarantine_rows, dedupe_valid_records, normalize_batch

# Minimal schema expected by normalize_batch/dedupe_valid_records/build_quarantine_rows,
# equivalent to the columns that come from Bronze (producer + _ingested_at/_source_file/_rescued_data).
SCHEMA = StructType([
    StructField("event_id", StringType()),
    StructField("batch_id", StringType()),
    StructField("user_id", StringType()),
    StructField("track_id", StringType()),
    StructField("platform", StringType()),
    StructField("device_type", StringType()),
    StructField("duration_played_sec", StringType()),
    StructField("timestamp", StringType()),
    StructField("_rescued_data", StringType()),
    StructField("_ingested_at", TimestampType()),
    StructField("_source_file", StringType()),
])


def _ts(offset=timedelta()):
    # Builds a timestamp relative to "now" (not a fixed value), because normalize_batch
    # classifies LATE/FUTURE by comparing with F.current_timestamp() at run time.
    return (datetime.now(timezone.utc) + offset).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _row(**overrides):
    # Valid record by default; each test overrides only the field it wants to invalidate,
    # isolating the business rule under test from the rest of the record.
    row = {
        "event_id": "evt_1",
        "batch_id": "batch_1",
        "user_id": "usr_1",
        "track_id": "trk_1",
        "platform": "spotify_clone",
        "device_type": None,
        "duration_played_sec": "180",
        "timestamp": _ts(),
        "_rescued_data": None,
        "_ingested_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "_source_file": "file_a.json",
    }
    row.update(overrides)
    return row


def _build_df(spark, *rows):
    return spark.createDataFrame([dict(r) for r in rows], SCHEMA)


# One case per quarantine reason listed in the README (rejection_reason).
@pytest.mark.parametrize(
    "overrides, expected_reason",
    [
        ({}, ""),
        ({"event_id": ""}, "INVALID_EVENT_ID"),
        ({"event_id": None}, "INVALID_EVENT_ID"),
        ({"track_id": ""}, "INVALID_TRACK_ID"),
        ({"platform": ""}, "INVALID_PLATFORM"),
        ({"duration_played_sec": "INVALID_DURATION"}, "INVALID_DURATION"),
        ({"duration_played_sec": "-10"}, "NEGATIVE_DURATION"),
        ({"timestamp": "not-a-date"}, "INVALID_TIMESTAMP"),
    ],
)
def test_normalize_batch_rejection_reason(spark, overrides, expected_reason):
    df = _build_df(spark, _row(**overrides))
    result = normalize_batch(df).collect()[0]
    if expected_reason == "":
        assert result["rejection_reason"] == ""
    else:
        assert expected_reason in result["rejection_reason"]


def test_normalize_batch_rejection_reason_combined(spark):
    # rejection_reason is a concat_ws of all applicable reasons, not just the first.
    df = _build_df(spark, _row(event_id="", track_id=""))
    reason = normalize_batch(df).collect()[0]["rejection_reason"]
    assert "INVALID_EVENT_ID" in reason
    assert "INVALID_TRACK_ID" in reason


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("not-a-date", "INVALID"),
        (None, "INVALID"),
    ],
)
def test_normalize_batch_timestamp_classification_invalid(spark, timestamp, expected):
    df = _build_df(spark, _row(timestamp=timestamp))
    result = normalize_batch(df).collect()[0]
    assert result["timestamp_classification"] == expected


def test_normalize_batch_timestamp_classification_on_time(spark):
    df = _build_df(spark, _row(timestamp=_ts()))
    result = normalize_batch(df).collect()[0]
    assert result["timestamp_classification"] == "ON_TIME"


def test_normalize_batch_timestamp_classification_late(spark):
    # Same scenario as the producer (i % 13 == 0 and i != 0): timestamp 2 days ago -> LATE.
    df = _build_df(spark, _row(timestamp=_ts(-timedelta(days=2))))
    result = normalize_batch(df).collect()[0]
    assert result["timestamp_classification"] == "LATE"


def test_normalize_batch_timestamp_classification_future(spark):
    # Same scenario as the producer (i % 11 == 0): timestamp 1 day ahead -> FUTURE.
    df = _build_df(spark, _row(timestamp=_ts(timedelta(days=1))))
    result = normalize_batch(df).collect()[0]
    assert result["timestamp_classification"] == "FUTURE"


def test_dedupe_valid_records_tie_break_by_ingested_at(spark):
    # Same event_id in two files: the record with the latest _ingested_at wins.
    older = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    newer = datetime.now(timezone.utc).replace(tzinfo=None)
    df = _build_df(
        spark,
        _row(_ingested_at=older, _source_file="file_a.json", user_id="usr_old"),
        _row(_ingested_at=newer, _source_file="file_b.json", user_id="usr_new"),
    )
    normalized = normalize_batch(df)
    valid = normalized.filter(normalized.rejection_reason == "")
    result = dedupe_valid_records(valid).collect()
    assert len(result) == 1
    assert result[0]["user_id"] == "usr_new"


def test_dedupe_valid_records_tie_break_by_source_file(spark):
    # Tied _ingested_at: the tie is broken by _source_file in descending order.
    same_time = datetime.now(timezone.utc).replace(tzinfo=None)
    df = _build_df(
        spark,
        _row(_ingested_at=same_time, _source_file="file_a.json", user_id="usr_a"),
        _row(_ingested_at=same_time, _source_file="file_b.json", user_id="usr_b"),
    )
    normalized = normalize_batch(df)
    valid = normalized.filter(normalized.rejection_reason == "")
    result = dedupe_valid_records(valid).collect()
    assert len(result) == 1
    assert result[0]["user_id"] == "usr_b"


def test_build_quarantine_rows_shape(spark):
    # Confirms that the rejected record carries rejection_reason and gains rejected_at,
    # without performing the real write to the quarantine table.
    df = _build_df(spark, _row(track_id=""))
    normalized = normalize_batch(df)
    rejected = normalized.filter(normalized.rejection_reason != "")
    result = build_quarantine_rows(rejected).collect()
    assert len(result) == 1
    row = result[0]
    assert "rejected_at" in row.asDict()
    assert row["rejection_reason"] == "INVALID_TRACK_ID"
