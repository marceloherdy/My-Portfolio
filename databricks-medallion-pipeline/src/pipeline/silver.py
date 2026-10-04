from pyspark.sql import functions as F
from pyspark.sql.window import Window


def normalize_batch(batch_df):
    current_time = F.current_timestamp()
    normalized = (
        batch_df
        .withColumn("event_id", F.trim(F.col("event_id")))
        .withColumn("track_id", F.trim(F.col("track_id")))
        .withColumn("platform", F.trim(F.col("platform")))
        .withColumn("duration_played_sec_int", F.expr("try_cast(duration_played_sec AS INT)"))
        .withColumn(
            "event_timestamp_parsed",
            F.to_timestamp("timestamp", "yyyy-MM-dd'T'HH:mm:ssZ"),
        )
        .withColumn(
            "rejection_reason",
            F.concat_ws(
                "; ",
                F.when(F.col("event_id").isNull() | (F.col("event_id") == ""), "INVALID_EVENT_ID"),
                F.when(F.col("track_id").isNull() | (F.col("track_id") == ""), "INVALID_TRACK_ID"),
                F.when(F.col("platform").isNull() | (F.col("platform") == ""), "INVALID_PLATFORM"),
                F.when(F.col("duration_played_sec_int").isNull(), "INVALID_DURATION"),
                F.when(F.col("duration_played_sec_int") < 0, "NEGATIVE_DURATION"),
                F.when(F.col("event_timestamp_parsed").isNull(), "INVALID_TIMESTAMP"),
            ),
        )
        .withColumn(
            "timestamp_classification",
            F.when(F.col("event_timestamp_parsed").isNull(), "INVALID")
            .when(F.col("event_timestamp_parsed") > current_time, "FUTURE")
            .when(F.col("event_timestamp_parsed") < current_time - F.expr("INTERVAL 1 DAY"), "LATE")
            .otherwise("ON_TIME"),
        )
    )
    return normalized


def dedupe_valid_records(valid_df):
    rank_window = Window.partitionBy("event_id").orderBy(
        F.col("_ingested_at").desc(),
        F.col("_source_file").desc(),
    )
    return (
        valid_df
        .withColumn("_row_number", F.row_number().over(rank_window))
        .filter(F.col("_row_number") == 1)
        .select(
            "event_id", "user_id", "track_id", "platform", "device_type",
            F.col("duration_played_sec_int").alias("duration_played_sec"),
            F.col("event_timestamp_parsed").alias("event_timestamp"),
            "timestamp_classification", "_rescued_data", "_ingested_at", "_source_file",
        )
    )


def build_quarantine_rows(rejected_df):
    return (
        rejected_df
        .select(
            "event_id", "batch_id", "user_id", "track_id", "platform", "device_type",
            "duration_played_sec", "timestamp", "_rescued_data", "_ingested_at", "_source_file",
            "rejection_reason",
        )
        .withColumn("rejected_at", F.current_timestamp())
    )
