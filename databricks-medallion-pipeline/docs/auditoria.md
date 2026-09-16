# Auditoria da Ingestão

## Objetivo

O pipeline registra métricas operacionais da ingestão na camada Bronze para permitir acompanhamento, diagnóstico de falhas e rastreabilidade dos arquivos processados.

A auditoria é mantida no schema `databricks_course_ws_new.ops` e possui dois níveis:

- `pipeline_audit`: uma linha por lote ou execução sem novos dados.
- `file_audit`: uma linha por arquivo processado em cada lote.

## Tabelas

### `pipeline_audit`

Tabela agregada da execução. É usada para acompanhar o resultado e o volume processado por lote.

| Campo | Descrição |
| --- | --- |
| `audit_id` | Identificador único do registro de auditoria. |
| `run_id` | Identificador da execução do pipeline. Relaciona registros da mesma execução. |
| `pipeline_name` | Nome do pipeline executado. |
| `task_name` | Nome da tarefa responsável pelo processamento. |
| `target_table` | Tabela de destino dos dados processados. |
| `batch_id` | Identificador do lote. O valor `-1` representa uma execução sem arquivos novos. |
| `started_at` | Horário de início do processamento. |
| `finished_at` | Horário de conclusão do processamento. |
| `status` | Resultado da execução. Atualmente: `SUCCESS` ou `FAILED`. |
| `files_processed` | Quantidade de arquivos processados no lote. |
| `records_read` | Quantidade de registros lidos. |
| `records_inserted` | Quantidade de registros gravados no destino. |
| `records_rejected` | Quantidade de registros rejeitados. |
| `schema_drift_records` | Quantidade de registros com alteração ou inconsistência de schema. |
| `error_message` | Detalhes do erro, quando a execução falha. |

### `file_audit`

Tabela detalhada do processamento. É usada para identificar quais arquivos foram processados e quais métricas cada arquivo produziu.

| Campo | Descrição |
| --- | --- |
| `file_audit_id` | Identificador único do registro de auditoria do arquivo. |
| `run_id` | Identificador da execução relacionada. |
| `batch_id` | Lote em que o arquivo foi processado. |
| `source_file` | Caminho completo do arquivo no volume de origem. |
| `target_table` | Tabela de destino. |
| `processed_at` | Horário do registro do processamento. |
| `status` | Resultado do processamento do arquivo. Atualmente: `SUCCESS` ou `FAILED`. |
| `records_read` | Registros lidos do arquivo. |
| `records_inserted` | Registros inseridos na tabela de destino. |
| `schema_drift_records` | Registros afetados por schema drift e direcionados para `_rescued_data`. |
| `error_message` | Detalhes do erro, quando o processamento falha. |

## Comportamentos importantes

- A ingestão utiliza Auto Loader com `availableNow=True`.
- Quando não há dados novos para processar (arquivos na Bronze, registros pendentes na Silver ou na Gold), o pipeline registra uma linha em `pipeline_audit` com contadores iguais a zero e `batch_id = -1`, para cada camada.
- O job `gold_aggregation` grava em `pipeline_audit` com 4 `task_name` diferentes (`gold_pipeline_run_health`, `gold_file_processing_latency`, `gold_quality_rejection_reasons`, `gold_quality_timestamp_classification` — a task `data_quality_summary` do bundle roda duas streams/auditorias independentes), mas nunca em `file_audit` (agregam tabelas, não arquivos).
- O estado do Auto Loader e o schema ficam em volumes operacionais separados do landing.
- O checkpoint e a transação Delta tornam o processamento reexecutável sem duplicar o mesmo lote.
- Registros com alterações de schema são preservados na coluna `_rescued_data` da tabela Bronze.

## Consultas úteis

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
FROM databricks_course_ws_new.ops.pipeline_audit
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
FROM databricks_course_ws_new.ops.file_audit
WHERE run_id = (
    SELECT run_id
    FROM databricks_course_ws_new.ops.pipeline_audit
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
FROM databricks_course_ws_new.ops.file_audit
WHERE status = 'FAILED'
ORDER BY processed_at DESC;
```

### Execuções sem arquivos novos

```sql
SELECT
    run_id,
    finished_at,
    status
FROM databricks_course_ws_new.ops.pipeline_audit
WHERE batch_id = -1
ORDER BY finished_at DESC;
```
