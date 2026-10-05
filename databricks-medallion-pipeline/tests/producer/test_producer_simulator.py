from datetime import datetime, timedelta, timezone

from producer.producer_simulator import TRACK_POOL, USER_POOL, build_record, random_event_timestamp

# Each test covers one i % N condition of the scenario table in the README (section
# "Data quality scenarios"); build_record(i, ...) is the pure function extracted from the original loop.
BATCH_ID = "batch_test"


def _event_timestamp():
    return datetime.now(timezone.utc)


def test_build_record_baseline_is_valid():
    # i=1 matches no i % N rule -> a "clean" record, used as the reference.
    record = build_record(1, _event_timestamp(), BATCH_ID)
    assert record["event_id"] == f"evt_{BATCH_ID}_1"
    # user_id and track_id are drawn from the pools, not derived from the index.
    assert record["user_id"] in USER_POOL
    assert record["track_id"] in TRACK_POOL
    assert record["platform"] == "spotify_clone"
    assert record["duration_played_sec"] == 181
    assert "device_type" not in record


def test_build_record_ids_are_not_tied_to_the_index():
    # Regression: user_id/track_id derived from i made every user listen to a single track.
    pairs = {
        (r["user_id"], r["track_id"])
        for r in (build_record(1, _event_timestamp(), BATCH_ID) for _ in range(200))
    }
    assert len({user for user, _ in pairs}) > 1
    assert len({track for _, track in pairs}) > 1


def test_build_record_late_events_can_have_a_user():
    # i=13 is late and matches neither i % 3 nor i % 7: it must keep its user_id.
    record = build_record(13, _event_timestamp(), BATCH_ID)
    assert record["user_id"] in USER_POOL


def test_build_record_null_user_id():
    # i % 3 == 0 and i % 7 != 0 -> keeps the key with a null value
    record = build_record(3, _event_timestamp(), BATCH_ID)
    assert record["user_id"] is None


def test_build_record_missing_user_id_key():
    # i % 7 == 0 -> removes the whole key
    record = build_record(7, _event_timestamp(), BATCH_ID)
    assert "user_id" not in record


def test_build_record_schema_drift_device_type():
    # i % 4 == 0
    record = build_record(4, _event_timestamp(), BATCH_ID)
    assert record["device_type"] in {"mobile", "desktop", "smart_tv"}


def test_build_record_invalid_duration_type():
    # i == 9 -> type inconsistency (string instead of int)
    record = build_record(9, _event_timestamp(), BATCH_ID)
    assert record["duration_played_sec"] == "INVALID_DURATION"


def test_build_record_negative_duration():
    # i % 5 == 0 and i != 0
    record = build_record(5, _event_timestamp(), BATCH_ID)
    assert record["duration_played_sec"] == -10


def test_build_record_late_timestamp():
    # i % 13 == 0 and i != 0
    base = _event_timestamp()
    record = build_record(13, base, BATCH_ID)
    parsed = datetime.strptime(record["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    assert parsed < base


def test_build_record_future_timestamp():
    # i % 11 == 0 and i % 13 != 0
    base = _event_timestamp()
    record = build_record(11, base, BATCH_ID)
    parsed = datetime.strptime(record["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    assert parsed > base


def test_build_record_empty_track_and_platform():
    # i % 10 == 0 and i != 0
    record = build_record(10, _event_timestamp(), BATCH_ID)
    assert record["track_id"] == ""
    assert record["platform"] == ""


def test_random_event_timestamp_without_days_back_is_now():
    now = _event_timestamp()
    assert random_event_timestamp(now, 0) == now


def test_random_event_timestamp_spreads_over_days_without_future():
    now = _event_timestamp()
    samples = [random_event_timestamp(now, 7) for _ in range(500)]
    assert all(sample <= now for sample in samples)
    assert all(sample >= now - timedelta(days=8) for sample in samples)
    # With 500 draws over 8 possible days, covering several distinct days is practically certain.
    assert len({sample.date() for sample in samples}) >= 5
