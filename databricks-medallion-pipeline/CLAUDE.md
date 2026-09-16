# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

Pipeline de engenharia de dados no Azure Databricks (Unity Catalog + Databricks Asset Bundles) que simula uma plataforma de streaming de música. Um producer Python gera arquivos JSON Lines "sujos" de propósito (nulos, chaves ausentes, schema drift, tipos inconsistentes, duplicatas conflitantes, timestamps atrasados/futuros) para exercitar resiliência, rastreabilidade e governança em um Lakehouse com arquitetura Medalhão.

```text
Producer Python -> Volume landing -> Bronze (Auto Loader) -> Silver (dedup + quarentena) -> Gold (futuro)
```

## Comandos

```powershell
# Validar/publicar o bundle
databricks bundle validate -t dev
databricks bundle deploy -t dev

# Rodar os jobs (cada um é um job Databricks separado, definido em databricks.yml)
databricks bundle run producer_simulator -t dev
databricks bundle run bronze_ingestion -t dev
databricks bundle run silver_transformation -t dev

# Ambiente local (Python 3.12, exigido por compatibilidade com Databricks Connect 16.4)
py -3.12 -m pip install -e .
py -3.12 -m py_compile .\src\producer\producer_simulator.py

# Testes (pytest local, sem cluster — ver seção "Testes")
py -3.12 -m pytest tests/ -v
py -3.12 -m pytest tests/pipeline/test_silver.py -v   # um único arquivo
py -3.12 -m pytest tests/pipeline/test_silver.py::test_normalize_batch_rejection_reason -v  # um único teste
```

Não há linter configurado no projeto.

**Testes que usam SparkSession local** (`tests/pipeline/test_silver.py`, `tests/pipeline/test_metrics.py`) exigem uma JVM (JDK) instalada e um `pyspark` capaz de abrir sessão `local[1]`. O `databricks-connect` do `.venv` do projeto bloqueia sessões locais de propósito (só aceita sessões remotas) — nesse ambiente, esses testes são pulados automaticamente (`SKIPPED`) pela fixture `spark` em `tests/conftest.py`, sem falhar a suíte. Para rodá-los de fato, use um ambiente com `pyspark` puro (não `databricks-connect`) e um JDK instalado. Os testes de `tests/pipeline/test_audit.py` e `tests/producer/test_producer_simulator.py` não usam Spark e sempre rodam.

## Arquitetura

### Camadas e tabelas no Unity Catalog

| Camada | Tabela/Volume |
| --- | --- |
| Landing | `databricks_course_ws_new.landing.events_volume` (Volume) |
| Bronze | `databricks_course_ws_new.bronze.spotify_events_raw` |
| Silver | `databricks_course_ws_new.silver.spotify_events` |
| Silver (quarentena) | `databricks_course_ws_new.silver.spotify_events_quarantine` |
| Ops | `databricks_course_ws_new.ops.checkpoints_volume` (Volume), `databricks_course_ws_new.ops.pipeline_audit`, `databricks_course_ws_new.ops.file_audit` |

### Onde fica cada coisa

- `src/pipeline/`: lógica de transformação **pura e testável** (sem Spark I/O nas funções principais, exceto SparkSession para DataFrames). O critério de estar aqui não é "isso é reusável entre tabelas/pipelines" — é "isso é determinístico (DataFrame in → DataFrame/dict out) e dá pra testar com pytest sem cluster". `silver.py` é específico da tabela `spotify_events` e mesmo assim vive aqui, porque a separação é entre **domínio** (regras de negócio) e **adapter** (I/O, streaming, Delta) — não entre "genérico" e "específico". `metrics.py` e `audit.py` acabam sendo reusados por Bronze e Silver, mas isso é consequência, não o objetivo da pasta.
- `notebooks/*.py`: orquestração Spark/streaming (o "adapter") — leitura via Auto Loader/`readStream`, `foreachBatch`, `MERGE` Delta, `writeStream`, chamadas de auditoria. Importam a lógica pura de `src/pipeline/` via `sys.path.append` (ver nota abaixo). Um notebook não deve crescer com regras de negócio testáveis embutidas; se uma lógica nova é determinística e vale testar isoladamente, ela nasce em `src/pipeline/`, mesmo que sirva só àquele notebook.
- `src/producer/producer_simulator.py`: gerador de dados sintéticos, Python puro (sem Spark).
- `databricks.yml`: define os 3 jobs do bundle e as variáveis (`cluster_id`, `output_dir`, `num_files`).

**Import de `src/pipeline` nos notebooks:** os jobs do bundle apontam `spark_python_task` diretamente para os arquivos em `notebooks/`, sem instalar o pacote no cluster. Por isso os notebooks fazem `sys.path.append` para o diretório `src/` antes de importar `pipeline.*`. Localmente, `pip install -e .` resolve o mesmo import para pytest.

### Fluxo Bronze (`notebooks/ingest_bronze.py`)

- Auto Loader (`cloudFiles.format=json`), `cloudFiles.schemaEvolutionMode=rescue` (schema drift vai para `_rescued_data`, nunca é descartado silenciosamente).
- Adiciona `_ingested_at` e `_source_file` (via `_metadata.file_path`) a cada registro.
- `trigger(availableNow=True)`: processa o que está disponível e encerra (não é streaming contínuo).
- `foreachBatch` grava na Bronze com `txnAppId`/`txnVersion` (idempotência Delta — reprocessar o mesmo `batch_id` não duplica).
- Métricas por lote/arquivo calculadas via `src/pipeline/metrics.py::compute_file_metrics` e registradas em `pipeline_audit`/`file_audit`.
- Quando não há arquivos novos, registra uma linha de auditoria com `batch_id = -1`.

### Fluxo Silver (`notebooks/silver_transform.py`)

Colunas do contrato Silver: `event_id, user_id, track_id, platform, device_type, duration_played_sec, event_timestamp, timestamp_classification, _rescued_data, _ingested_at, _source_file`.

Regras de negócio (implementadas em `src/pipeline/silver.py`):

- **Rejeição/quarentena** (`normalize_batch`, campo `rejection_reason`, concatenação de múltiplos motivos): `INVALID_EVENT_ID` (vazio/nulo), `INVALID_TRACK_ID`, `INVALID_PLATFORM`, `INVALID_DURATION` (não convertível para INT), `NEGATIVE_DURATION`, `INVALID_TIMESTAMP` (não parseável no formato `yyyy-MM-dd'T'HH:mm:ssZ`).
- **Classificação de timestamp** (`timestamp_classification`): `INVALID` (timestamp não parseável) > `FUTURE` (> agora) > `LATE` (> 1 dia atrás) > `ON_TIME`.
- **`user_id` nulo/ausente**: permanece na Silver com `NULL` — não é motivo de quarentena (foco é interesse agregado, não recomendação individual).
- **Dedup** (`dedupe_valid_records`): `event_id` é o identificador global do evento (composto por `batch_id` + índice do registro no producer). Duplicatas com mesmo `event_id` são reduzidas a 1 registro via `Window.partitionBy("event_id").orderBy(_ingested_at desc, _source_file desc)` + `row_number()==1`.
- **Merge na Silver**: `MERGE` Delta condicionado — só atualiza se `source._ingested_at` for mais recente (desempate por `_source_file` em ordem decrescente).
- Registros rejeitados vão para `spotify_events_quarantine` com `rejection_reason`, nunca são descartados sem rastro.

### Auditoria

Duas tabelas (`src/pipeline/audit.py::PipelineAudit`): `pipeline_audit` (uma linha por lote/execução) e `file_audit` (uma linha por arquivo processado). Status usados: `SUCCESS`/`FAILED`. Documentação completa e queries prontas em [docs/auditoria.md](docs/auditoria.md) — não duplicar aqui, só consultar quando precisar investigar uma execução.

### Producer (`src/producer/producer_simulator.py`)

Gera cenários de sujeira de dados por índice `i` do registro dentro do lote (`build_record(i, ...)`):

| Condição | Cenário |
| --- | --- |
| `i % 3 == 0` | `user_id` nulo |
| `i % 4 == 0` | `device_type` extra (schema drift) |
| `i % 7 == 0` | `user_id` ausente (chave removida) |
| `i == 9` | `duration_played_sec = "INVALID_DURATION"` (tipo inconsistente) |
| `i % 5 == 0` e `i != 0` | `duration_played_sec = -10` (fora do domínio) |
| `i % 6 == 0` e `i != 0` | timestamp atrasado (-2 dias) |
| `i % 11 == 0` | timestamp futuro (+1 dia) |
| `i % 10 == 0` e `i != 0` | `track_id`/`platform` vazios |
| último registro de cada lote | duplicata conflitante de `records[0]` (mesmo `event_id`, `duration_played_sec=999999`, `user_id="usr_conflict"`) — testa o desempate da Silver |

Gera lotes JSON Lines (não é streaming em tempo real — simula uma fonte incremental baseada em arquivos).

## Próximo projeto (Free Edition)

O plano para replicar o contrato funcional da Silver em um workspace Databricks Free Edition separado, usando Lakeflow Declarative Pipelines + Expectations em vez de PySpark manual, vive em outro repositório (`databricks-declarative-quality`, pasta irmã deste projeto). É um projeto/repositório distinto — não misturar credenciais, catálogo ou cluster com este.
