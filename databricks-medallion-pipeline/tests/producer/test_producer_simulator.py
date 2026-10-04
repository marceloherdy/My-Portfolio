from datetime import datetime, timezone

from producer.producer_simulator import TRACK_POOL, USER_POOL, build_record

# Cada teste cobre uma condição i % N da tabela de cenários em CLAUDE.md (seção
# "Producer"); build_record(i, ...) é a função pura extraída do loop original.
BATCH_ID = "batch_test"


def _event_timestamp():
    return datetime.now(timezone.utc)


def test_build_record_baseline_is_valid():
    # i=1 não cai em nenhuma regra i % N -> registro "limpo", usado como referência.
    record = build_record(1, _event_timestamp(), BATCH_ID)
    assert record["event_id"] == f"evt_{BATCH_ID}_1"
    # user_id e track_id são sorteados dos pools, não derivados do índice.
    assert record["user_id"] in USER_POOL
    assert record["track_id"] in TRACK_POOL
    assert record["platform"] == "spotify_clone"
    assert record["duration_played_sec"] == 181
    assert "device_type" not in record


def test_build_record_ids_are_not_tied_to_the_index():
    # Regressão: user_id/track_id derivados de i faziam cada usuário ouvir uma única faixa.
    pairs = {
        (r["user_id"], r["track_id"])
        for r in (build_record(1, _event_timestamp(), BATCH_ID) for _ in range(200))
    }
    assert len({user for user, _ in pairs}) > 1
    assert len({track for _, track in pairs}) > 1


def test_build_record_late_events_can_have_a_user():
    # i=13 é atrasado e não cai em i % 3 nem i % 7: deve manter user_id.
    record = build_record(13, _event_timestamp(), BATCH_ID)
    assert record["user_id"] in USER_POOL


def test_build_record_null_user_id():
    # i % 3 == 0 e i % 7 != 0 -> mantém a chave com valor nulo
    record = build_record(3, _event_timestamp(), BATCH_ID)
    assert record["user_id"] is None


def test_build_record_missing_user_id_key():
    # i % 7 == 0 -> remove a chave inteira
    record = build_record(7, _event_timestamp(), BATCH_ID)
    assert "user_id" not in record


def test_build_record_schema_drift_device_type():
    # i % 4 == 0
    record = build_record(4, _event_timestamp(), BATCH_ID)
    assert record["device_type"] in {"mobile", "desktop", "smart_tv"}


def test_build_record_invalid_duration_type():
    # i == 9 -> inconsistência de tipo (string no lugar de int)
    record = build_record(9, _event_timestamp(), BATCH_ID)
    assert record["duration_played_sec"] == "INVALID_DURATION"


def test_build_record_negative_duration():
    # i % 5 == 0 e i != 0
    record = build_record(5, _event_timestamp(), BATCH_ID)
    assert record["duration_played_sec"] == -10


def test_build_record_late_timestamp():
    # i % 13 == 0 e i != 0
    base = _event_timestamp()
    record = build_record(13, base, BATCH_ID)
    parsed = datetime.strptime(record["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    assert parsed < base


def test_build_record_future_timestamp():
    # i % 11 == 0 e i % 13 != 0
    base = _event_timestamp()
    record = build_record(11, base, BATCH_ID)
    parsed = datetime.strptime(record["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    assert parsed > base


def test_build_record_empty_track_and_platform():
    # i % 10 == 0 e i != 0
    record = build_record(10, _event_timestamp(), BATCH_ID)
    assert record["track_id"] == ""
    assert record["platform"] == ""
