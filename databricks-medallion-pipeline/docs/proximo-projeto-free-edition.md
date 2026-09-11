# Próximo Projeto: Databricks Free Edition

## Objetivo

Criar um projeto separado na conta Databricks Free Edition para demonstrar uma arquitetura declarativa de qualidade de dados usando Lakeflow Declarative Pipelines e Expectations.

Este documento registra as decisões do projeto Azure que devem ser reaproveitadas, além das adaptações necessárias para o ambiente Free Edition.

## Arquitetura planejada

```text
Producer Python
    -> Landing no workspace Free
    -> Bronze com Auto Loader
    -> Silver com Lakeflow Pipeline + Expectations
         -> spotify_events
         -> spotify_events_quarantine
    -> Gold com métricas de interesse musical
```

A Bronze pode continuar demonstrando ingestão incremental. A Silver será implementada como um Lakeflow Declarative Pipeline acionado no modo `TRIGGERED`, evitando processamento contínuo e mantendo o uso controlado.

## Contrato funcional reaproveitado

Tabela Silver:

```text
<catalogo-free>.silver.spotify_events
```

Tabela de quarentena:

```text
<catalogo-free>.silver.spotify_events_quarantine
```

Colunas esperadas na Silver:

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

Critérios de negócio:

- `duration_played_sec` deve ser inteiro e não negativo;
- valores inválidos ou negativos devem ser direcionados à quarentena;
- `user_id` nulo ou ausente permanece na Silver;
- `event_id` é globalmente único no contrato do produtor;
- duplicatas por `event_id` são reduzidas a um registro;
- em conflito, vence o maior `_ingested_at`; em empate, vence o `_source_file` em ordem decrescente;
- `track_id` e `platform` vazios ou ausentes vão para a quarentena;
- `timestamp` é normalizado para `event_timestamp`;
- timestamps atrasados ou futuros permanecem na Silver com classificação `LATE` ou `FUTURE`;
- `_rescued_data` é preservado quando os campos essenciais são válidos.

## Expectations

As regras devem ser declaradas no pipeline, usando Expectations nativas sempre que possível.

Exemplos de categorias:

| Regra | Ação sugerida |
| --- | --- |
| `event_id` obrigatório | `DROP` ou quarentena |
| `track_id` preenchido | `DROP` ou quarentena |
| `platform` preenchida | `DROP` ou quarentena |
| `duration_played_sec >= 0` | `DROP` ou quarentena |
| `user_id` preenchido | `WARN` |
| timestamp atrasado | `WARN` |
| timestamp futuro | `WARN` |
| schema drift | `WARN` |

A decisão final entre `expect_or_drop` e o padrão de quarentena deve considerar a necessidade de preservar o registro inválido para investigação. Para este projeto, a preferência é manter uma tabela de quarentena consultável, e não apenas descartar linhas.

## Limitações do Free Edition

O Free Edition deve ser tratado como um ambiente de estudo e portfólio:

- somente serverless compute;
- sem clusters clássicos configuráveis;
- limite de uma pipeline ativa por tipo;
- limite de até cinco tarefas concorrentes por conta;
- quotas de uso e possibilidade de indisponibilidade temporária após exceder a quota;
- sem uso comercial, SLA ou suporte empresarial;
- autenticação configurada separadamente por email OTP, Google ou Microsoft;
- sem R ou Scala; usar Python;
- catálogo, schemas, volumes e host são diferentes do workspace Azure.

## Bundle e execução

O novo projeto deve ter seu próprio repositório e seu próprio `databricks.yml`. Não reutilizar diretamente o host, perfil, cluster ID ou nomes de volumes da Azure.

O bundle deverá declarar um recurso `pipeline` para a Silver e, quando suportado pelo workspace, configurar:

- `serverless: true`;
- `continuous: false`;
- modo de desenvolvimento durante a construção;
- catálogo e schema do novo workspace;
- bibliotecas Python do pipeline;
- log de eventos em local acessível;
- execução acionada manualmente ou por job.

A validação mínima esperada será:

```powershell
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run <pipeline-or-job> -t dev
```

Os comandos e o perfil de autenticação deverão ser reconfigurados depois que o workspace Free for criado.

## Checklist de criação

- [ ] Criar o workspace Databricks Free Edition.
- [ ] Configurar autenticação local para o novo host.
- [ ] Criar o repositório separado.
- [ ] Confirmar catálogo, schema e armazenamento disponíveis.
- [ ] Recriar os volumes gerenciados necessários.
- [ ] Copiar o produtor e adaptar os caminhos de saída.
- [ ] Criar ou migrar a Bronze.
- [ ] Implementar a Silver como Lakeflow Pipeline.
- [ ] Adicionar Expectations e quarentena.
- [ ] Configurar o pipeline no bundle.
- [ ] Validar métricas de qualidade e o event log.
- [ ] Atualizar o README do novo projeto com limitações e custos de uso.

## Decisão arquitetural

O projeto Azure continuará usando Jobs, PySpark e o cluster existente para manter o custo e o escopo sob controle. O projeto Free será usado para demonstrar a abordagem declarativa com Lakeflow Pipelines e Expectations.

O contrato funcional deve permanecer semelhante nos dois projetos, mas a implementação será específica de cada ambiente. Isso permite comparar as abordagens sem misturar credenciais, recursos ou configurações de nuvem.
