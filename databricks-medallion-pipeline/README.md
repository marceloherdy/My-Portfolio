# Pipeline de Ingestão no Azure Databricks

Pipeline de engenharia de dados com arquitetura Medalhão completa (Bronze, Silver e Gold) que simula eventos de uma plataforma de música, usando Azure Databricks, Unity Catalog e Databricks Asset Bundles.

## Objetivo

O projeto reproduz desafios comuns de ingestão de dados: arquivos incrementais, valores nulos, chaves ausentes, evolução de schema, inconsistências de tipo e registros duplicados. A finalidade é exercitar resiliência, rastreabilidade e governança em um Lakehouse.

## Arquitetura

O projeto segue a arquitetura Medalhão:

```text
Produtor Python
    -> Volume landing
    -> Bronze Delta com Auto Loader
    -> Silver (dedup + quarentena)
    -> Gold (agregações de auditoria e de negócio)
```

Recursos atuais no Unity Catalog:

```text
databricks_course_ws_new.landing.events_volume
databricks_course_ws_new.bronze.spotify_events_raw
databricks_course_ws_new.silver.spotify_events
databricks_course_ws_new.silver.spotify_events_quarantine
databricks_course_ws_new.gold.pipeline_run_health
databricks_course_ws_new.gold.file_processing_latency
databricks_course_ws_new.gold.data_quality_summary
databricks_course_ws_new.gold.track_popularity_daily
databricks_course_ws_new.gold.device_usage_daily
databricks_course_ws_new.gold.user_activity_daily
databricks_course_ws_new.gold.business_kpi_daily
databricks_course_ws_new.gold.field_quality
databricks_course_ws_new.ops.checkpoints_volume
databricks_course_ws_new.ops.pipeline_audit
databricks_course_ws_new.ops.file_audit
```

O volume `landing` armazena os arquivos de origem. O volume `ops` mantém o checkpoint e o schema do Auto Loader. As tabelas de auditoria registram métricas agregadas por lote e detalhadas por arquivo.

## Cenários de qualidade simulados

O produtor em [src/producer/producer_simulator.py](src/producer/producer_simulator.py) gera deliberadamente:

- valores nulos em campos como `user_id`;
- chaves ausentes;
- atributos adicionais, simulando schema drift;
- inconsistências de tipo em `duration_played_sec`;
- duplicidade de registros para testar deduplicação;
- valores fora do domínio, como durações negativas;
- eventos atrasados e timestamps futuros;
- campos vazios em atributos de negócio;
- duplicidades com conflito de conteúdo para testar a regra de desempate da Silver;
- identificadores globais por evento, compostos pelo `batch_id` e pelo índice do registro.

O produtor gera lotes JSON Lines. Portanto, ele simula uma fonte incremental baseada em arquivos, e não um broker de streaming em tempo real.

## Bronze

A ingestão está em [notebooks/ingest_bronze.py](notebooks/ingest_bronze.py) e utiliza:

- Auto Loader com `cloudFiles.format = json`;
- `cloudFiles.schemaLocation` para persistência do schema;
- `schemaEvolutionMode = rescue` para preservar alterações de schema em `_rescued_data`;
- `_ingested_at` e `_source_file` para rastreabilidade;
- `trigger(availableNow=True)` para processar os arquivos disponíveis e encerrar o job;
- `foreachBatch` para calcular métricas por lote e por arquivo;
- transação Delta por lote para evitar duplicação causada por reprocessamento do mesmo batch.

O modo `rescue` trata alterações de schema compatíveis com essa estratégia, mas não substitui validações de negócio nem elimina todos os possíveis erros de processamento.

O produtor gera um `batch_id` único para cada arquivo e usa a combinação desse identificador com o índice do registro para formar o `event_id`. Assim, eventos de arquivos diferentes não colidem, enquanto a duplicata intencional mantém o mesmo `event_id` e pode ser deduplicada na Silver.

## Silver e quarentena

A tabela tratada da camada Silver é:

```text
databricks_course_ws_new.silver.spotify_events
```

Colunas do contrato:

```text
event_id
user_id
track_id
platform
device_type
duration_played_sec
event_timestamp
timestamp_classification
_rescued_data
_ingested_at
_source_file
```

Critérios implementados no tratamento (lógica pura e testada em [src/pipeline/silver.py](src/pipeline/silver.py)):

- `duration_played_sec` é convertido para inteiro quando possível;
- valores inválidos ou fora do domínio, como durações negativas, são direcionados para quarentena;
- registros sem `user_id` permanecem na Silver com valor `NULL`, pois o foco é analisar o interesse agregado dos usuários, e não gerar recomendações individuais;
- o campo `timestamp` da Bronze é convertido e padronizado como `event_timestamp`, e classificado em `timestamp_classification` (`ON_TIME`, `LATE`, `FUTURE` ou `INVALID`);
- `event_id` é tratado como identificador global do evento (composto por `batch_id` + índice do registro);
- duplicatas com o mesmo `event_id` são reduzidas a um registro por `_ingested_at`/`_source_file` mais recentes;
- `track_id`, `platform`, `duration_played_sec` e `timestamp` são campos essenciais: sua ausência ou invalidade envia o registro para quarentena;
- `_rescued_data` é preservado, sem descarte silencioso.

Os registros rejeitados são preservados em `databricks_course_ws_new.silver.spotify_events_quarantine` com o motivo do descarte (`rejection_reason`). A implementação está em [notebooks/silver_transform.py](notebooks/silver_transform.py).

## Gold

O job `gold_aggregation` roda 3 tasks incrementais (mesmo padrão de Bronze/Silver: streaming + `trigger(availableNow=True)` + checkpoint + `MERGE` Delta), cada uma alimentada pela lógica pura em [src/pipeline/gold.py](src/pipeline/gold.py):

- **`gold.pipeline_run_health`** ([notebooks/gold_pipeline_run_health.py](notebooks/gold_pipeline_run_health.py)) — saúde do pipeline por dia/pipeline/task: execuções, sucessos, falhas, execuções sem dados novos, duração média, volume processado/rejeitado.
- **`gold.file_processing_latency`** ([notebooks/gold_file_processing_latency.py](notebooks/gold_file_processing_latency.py)) — latência entre a geração do arquivo (timestamp no nome, gerado pelo producer) e seu processamento.
- **`gold.data_quality_summary`** ([notebooks/gold_data_quality_summary.py](notebooks/gold_data_quality_summary.py)) — motivos de rejeição da quarentena e distribuição de `timestamp_classification`, em formato longo (`event_date, metric_type, category, records_count`).

São tabelas de auditoria/observabilidade, pensadas para dashboards de saúde do pipeline.

### Gold de negócio

O job `gold_business` ([notebooks/gold_business_metrics.py](notebooks/gold_business_metrics.py)) recalcula por inteiro, a cada execução, 5 tabelas a partir da Silver (e da quarentena), com a lógica pura em [src/pipeline/gold.py](src/pipeline/gold.py). O recálculo (em vez do incremental) é porque a Silver sofre `MERGE` com `UPDATE` e porque contagens distintas não são somáveis entre execuções.

- **`gold.track_popularity_daily`** — plays, duração e usuários distintos por dia/faixa.
- **`gold.device_usage_daily`** — plays, duração e participação (`share_pct`) por dia/dispositivo; `device_type` nulo aparece como `unknown`.
- **`gold.user_activity_daily`** — plays, duração e faixas distintas por dia/usuário identificado.
- **`gold.business_kpi_daily`** — KPIs diários, incluindo `pct_without_user` e `pct_without_device`.
- **`gold.field_quality`** — quais campos mais prejudicam os dados: `LOSS` (registro vai para a quarentena) ou `DEGRADED` (campo nulo, mas o registro permanece na Silver), com `pct_of_total`.

As métricas de negócio consideram apenas eventos `ON_TIME` e `LATE`.

## Auditoria

A implementação reutilizável está em [src/pipeline/audit.py](src/pipeline/audit.py). A documentação detalhada das tabelas e consultas está em [docs/auditoria.md](docs/auditoria.md).

`pipeline_audit` registra uma linha por lote/execução, ou uma linha com `batch_id = -1` quando a execução não encontra dados novos — comportamento comum a Bronze, Silver e Gold. `file_audit` registra uma linha para cada arquivo processado (Bronze e Silver), incluindo contagens, status e mensagem de erro; as tasks da Gold não usam `file_audit`, pois agregam tabelas, não arquivos.

Os status atualmente utilizados são `SUCCESS` e `FAILED`.

## Testes

A lógica de transformação pura (`src/pipeline/`) tem cobertura de testes com `pytest`, sem precisar de cluster:

```powershell
py -3.12 -m pytest tests/ -v
```

Os testes de `silver.py` e `gold.py` dependem de uma `SparkSession` local (requer JDK); em ambientes com `databricks-connect` (que só aceita sessões remotas), eles são pulados automaticamente e o restante da suíte roda normalmente.

## Executar

Valide e publique o bundle:

```powershell
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

Gere arquivos no landing:

```powershell
databricks bundle run producer_simulator -t dev
```

Execute a ingestão Bronze:

```powershell
databricks bundle run bronze_ingestion -t dev
```

Execute a transformação Silver:

```powershell
databricks bundle run silver_transformation -t dev
```

Execute as agregações Gold:

```powershell
databricks bundle run gold_aggregation -t dev
```

Ou rode tudo de uma vez com o orquestrador (Producer → Bronze → Silver → Gold de auditoria e de negócio):

```powershell
databricks bundle run medallion_pipeline -t dev
```

O volume gerado é configurável pelas variáveis `num_files`, `min_records`, `max_records` e `interval_sec` do bundle.

Todos os jobs usam o cluster configurado na variável `cluster_id` em [databricks.yml](databricks.yml).

## Ambiente local

O projeto utiliza Python 3.12 para compatibilidade com o runtime Databricks Connect 16.4:

```powershell
py -3.12 -m pip install -e .
py -3.12 -m py_compile .\src\producer\producer_simulator.py
```

O botão `Run` do VS Code executa o produtor localmente. Para executar no cluster Databricks, use `databricks bundle run`.

## Próximas etapas

O fluxo Bronze, Silver, as Gold de auditoria e de negócio e o orquestrador estão implementados, com testes automatizados para a lógica pura. As próximas evoluções são:

- replicar o contrato da Silver com Lakeflow Declarative Pipelines + Expectations, em um projeto Databricks Free Edition separado (repositório irmão `databricks-declarative-quality`).
