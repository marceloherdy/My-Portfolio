[English](auditing.md) | **Português**

# Auditoria do pipeline

## Objetivo

O pipeline registra métricas operacionais de cada etapa, para que as execuções possam ser monitoradas, as falhas diagnosticadas e os arquivos processados rastreados.

A auditoria fica no schema `ops` do catálogo do projeto e tem dois níveis:

- `pipeline_audit`: uma linha por lote, ou por execução que não encontrou dados novos.
- `file_audit`: uma linha por arquivo processado em cada lote.

## Tabelas

### `pipeline_audit`

Visão agregada de uma execução. Use-a para acompanhar o resultado e o volume processado por lote.

| Coluna | Descrição |
| --- | --- |
| `audit_id` | Identificador único do registro de auditoria. |
| `run_id` | Identificador da execução do pipeline. Agrupa os registros da mesma execução. |
| `pipeline_name` | Nome do pipeline que foi executado. |
| `task_name` | Nome da tarefa que fez o processamento. |
| `target_table` | Tabela que recebeu os dados processados. |
| `batch_id` | Identificador do lote. `-1` indica uma execução sem dados novos (as tarefas Gold de negócio usam `0`, porque cada execução reconstrói a tabela). |
| `started_at` | Hora de início do processamento. |
| `finished_at` | Hora de término do processamento. |
| `status` | Resultado da execução. Atualmente `SUCCESS` ou `FAILED`. |
| `files_processed` | Número de arquivos processados no lote. |
| `records_read` | Número de registros lidos. |
| `records_inserted` | Número de registros gravados no destino. |
| `records_rejected` | Número de registros rejeitados. |
| `schema_drift_records` | Número de registros com mudança ou inconsistência de schema. |
| `error_message` | Detalhes do erro, quando a execução falha. |

### `file_audit`

Visão detalhada do processamento. Use-a para descobrir quais arquivos foram processados e quais métricas cada arquivo gerou.

| Coluna | Descrição |
| --- | --- |
| `file_audit_id` | Identificador único do registro de auditoria do arquivo. |
| `run_id` | Identificador da execução relacionada. |
| `batch_id` | Lote em que o arquivo foi processado. |
| `source_file` | Caminho completo do arquivo no volume de origem. |
| `target_table` | Tabela de destino. |
| `processed_at` | Hora em que o processamento foi registrado. |
| `status` | Resultado do processamento do arquivo. Atualmente `SUCCESS` ou `FAILED`. |
| `records_read` | Registros lidos do arquivo. |
| `records_inserted` | Registros inseridos na tabela de destino. |
| `schema_drift_records` | Registros afetados por schema drift e encaminhados para `_rescued_data`. |
| `error_message` | Detalhes do erro, quando o processamento falha. |

## Notas de comportamento

- A ingestão usa o Auto Loader com `availableNow=True`.
- Quando não há nada novo para processar (arquivos na Bronze, registros pendentes na Silver ou na Gold), cada camada grava uma linha em `pipeline_audit` com contadores zerados e `batch_id = -1`.
- O job `gold_aggregation` grava em `pipeline_audit` com quatro valores de `task_name` (`gold_pipeline_run_health`, `gold_file_processing_latency`, `gold_quality_rejection_reasons` e `gold_quality_timestamp_classification`; a tarefa `data_quality_summary` do bundle executa dois streams independentes, cada um com a sua auditoria). O job `gold_business` grava uma linha por tabela em `gold_business_<tabela>`. Nenhuma tarefa Gold grava em `file_audit`, porque elas agregam tabelas, e não arquivos.
- O estado e o schema do Auto Loader ficam em volumes operacionais separados do volume landing.
- O checkpoint e a transação Delta tornam seguro repetir uma execução sem duplicar um lote.
- A tarefa Bronze compara a contagem de linhas da tabela antes e depois de cada escrita. Se o número de linhas escritas for diferente do número de linhas lidas (por exemplo, o Delta descartou a escrita como um reprocessamento depois que os checkpoints foram apagados), o lote é registrado como `FAILED` em vez de `SUCCESS`.
- Registros com mudanças de schema são preservados na coluna `_rescued_data` da tabela Bronze.

## Consultas úteis

As consultas usam `your_catalog` como marcador de posição para o catálogo do projeto; substitua pelo seu (neste repositório, `databricks_course_ws_new`).

### Últimas execuções

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

### Arquivos processados na última execução

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

### Falhas de processamento

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

### Execuções sem dados novos

```sql
SELECT
    run_id,
    finished_at,
    status
FROM your_catalog.ops.pipeline_audit
WHERE batch_id = -1
ORDER BY finished_at DESC;
```
