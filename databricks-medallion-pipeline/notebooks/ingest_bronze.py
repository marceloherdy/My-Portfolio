from databricks.sdk.runtime import spark
from pyspark.sql.functions import col, current_timestamp

# Caminhos de entrada, estado operacional e tabela de destino no Unity Catalog.
volume_path = "/Volumes/databricks_course_ws_new/landing/events_volume"
checkpoint_path = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/spotify_events"
schema_location = "/Volumes/databricks_course_ws_new/ops/checkpoints_volume/schema/spotify_events"
target_table = "databricks_course_ws_new.bronze.spotify_events_raw"

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

# Processa os arquivos disponíveis e grava os eventos na camada Bronze.
query = (
    df_bronze.writeStream.format("delta")
    .outputMode("append")
    .option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True)
    .toTable(target_table)
)

# Aguarda o encerramento do processamento incremental.
query.awaitTermination()

print(f"Ingestão Bronze concluída com sucesso para a tabela: {target_table}")