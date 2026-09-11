# Pipeline de Ingestão no Azure Databricks

Pipeline de engenharia de dados que simula eventos de uma plataforma de música, ingere arquivos JSON Lines com Auto Loader e registra os dados na camada Bronze usando Azure Databricks, Unity Catalog e Declarative Automation Bundles.

## Objetivo

O projeto reproduz desafios comuns de ingestão de dados: arquivos incrementais, valores nulos, chaves ausentes, evolução de schema, inconsistências de tipo e registros duplicados. A finalidade é exercitar resiliência, rastreabilidade e governança em um Lakehouse.

## Arquitetura

O projeto segue a arquitetura Medalhão:

```text
Produtor Python
    -> Volume landing
    -> Bronze Delta com Auto Loader
    -> Silver (próxima etapa)
    -> Gold (futura etapa)
```

Recursos atuais no Unity Catalog:

```text
databricks_course_ws_new.landing.events_volume
databricks_course_ws_new.bronze.spotify_events_raw
databricks_course_ws_new.silver.spotify_events
databricks_course_ws_new.silver.spotify_events_quarantine
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

Colunas previstas:

```text
event_id
user_id
track_id
platform
device_type
duration_played_sec
event_timestamp
_ingested_at
_source_file
```

Critérios implementados no tratamento:

- `duration_played_sec` será convertido para inteiro quando possível;
- valores inválidos ou fora do domínio, como durações negativas, serão direcionados para quarentena;
- registros sem `user_id` permanecerão na Silver com valor `NULL`, pois o foco atual é analisar o interesse agregado dos usuários, e não gerar recomendações individuais;
- o campo `timestamp` da Bronze será convertido e padronizado como `event_timestamp`;
- `event_id` será tratado como identificador global do evento;
- duplicatas com o mesmo `event_id` serão reduzidas a um registro;
- duplicatas conflitantes exigirão uma regra de desempate baseada em metadados de ingestão e origem;
- `track_id`, `timestamp` e `event_id` serão considerados campos essenciais para identificar o evento e seu contexto;
- `_rescued_data` será preservado ou encaminhado para tratamento específico, sem descarte silencioso.

Os registros rejeitados são preservados em `databricks_course_ws_new.silver.spotify_events_quarantine` com o motivo do descarte. A implementação está em [notebooks/silver_transform.py](notebooks/silver_transform.py) e reutiliza o utilitário de auditoria.

## Auditoria

A implementação reutilizável está em [notebooks/utils/audit.py](notebooks/utils/audit.py). A documentação detalhada das tabelas e consultas está em [docs/auditoria.md](docs/auditoria.md).

`pipeline_audit` registra uma linha por lote ou uma linha com `batch_id = -1` quando a execução não encontra arquivos novos. `file_audit` registra uma linha para cada arquivo processado, incluindo contagens, status e mensagem de erro.

Os status atualmente utilizados são `SUCCESS` e `FAILED`.

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

O job usa o cluster configurado na variável `cluster_id` em [databricks.yml](databricks.yml).

## Ambiente local

O projeto utiliza Python 3.12 para compatibilidade com o runtime Databricks Connect 16.4:

```powershell
py -3.12 -m pip install -e .
py -3.12 -m py_compile .\src\producer\producer_simulator.py
```

O botão `Run` do VS Code executa o produtor localmente. Para executar no cluster Databricks, use `databricks bundle run`.

## Próximas etapas

O fluxo Bronze e Silver está implementado. As próximas evoluções são:

- implementar a camada Gold com métricas de interesse musical;
- adicionar Expectations no projeto Databricks Free Edition;
- incluir métricas de rejeição por arquivo na auditoria detalhada;
- criar testes automatizados para as regras da Silver.
