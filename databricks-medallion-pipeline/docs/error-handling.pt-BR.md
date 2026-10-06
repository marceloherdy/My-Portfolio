[English](error-handling.md) | **Português**

# Tratamento de registros resgatados e em quarentena

Este documento explica o que o pipeline faz com registros que têm problemas, como as equipes de dados costumam tratá-los depois da carga diária e o que ainda falta neste projeto para fechar o ciclo. A última seção é uma proposta de desenho que **não** foi implementada e é um bom ponto de partida para quem quiser estender o projeto.

## Dois mecanismos diferentes

Eles são frequentemente confundidos e respondem a perguntas diferentes.

| | `_rescued_data` | Quarentena (`silver.spotify_events_quarantine`) |
| --- | --- | --- |
| O que é | Uma **coluna** da tabela Bronze | Uma **tabela** no schema Silver |
| Preenchido por | Auto Loader (`schemaEvolutionMode = rescue`) | A transformação Silver (`normalize_batch`) |
| Gatilho | Os dados não batem com o schema: coluna nova, tipo diferente, caixa diferente | Os dados violam uma regra de negócio: `track_id` vazio, duração negativa, timestamp inválido |
| O que acontece com o registro | Ele **ainda é ingerido**; o valor problemático fica guardado como JSON na coluna | Ele é **removido da tabela Silver** e guardado na tabela de quarentena com um `rejection_reason` |
| Pergunta que responde | "A fonte mudou de formato?" | "Este registro é válido para o negócio?" |

Nada é apagado em nenhum dos casos. A Bronze é uma cópia append-only do que chegou, e a tabela de quarentena também é append-only.

## Como as equipes costumam tratar depois da carga diária

### 1. Quem olha

Geralmente o engenheiro de dados dono do pipeline, muitas vezes em escala de plantão (on-call), junto com o dono do sistema de origem ou um data steward quando a causa está a montante. Ninguém inspeciona as tabelas todos os dias: o trabalho é guiado por alertas.

### 2. Detecção

- Cada execução registra seus volumes: registros lidos, rejeitados e com dados resgatados. Neste projeto isso está em `ops.pipeline_audit`, `ops.file_audit` e `gold.data_quality_summary`.
- Limites disparam notificações (e-mail, chat, ticket). Por exemplo: uma taxa de quarentena acima de um percentual definido, ou qualquer aumento em `_rescued_data`.
- Um dashboard mostra a tendência ao longo do tempo.
- Ferramentas de qualidade de dados (expectations do Lakeflow, Great Expectations, Soda) cobrem parte disso.

### 3. Triagem

Principalmente por consultas, mas de forma guiada: agrupar por tipo de problema (motivo de rejeição, campo, arquivo de origem, data) em vez de ler registro por registro. O objetivo é encontrar a causa, que costuma cair em uma de três categorias:

- **A fonte mudou** (campo novo, tipo diferente): conversar com a equipe dona dos dados ou atualizar o contrato.
- **Um bug no pipeline ou em uma regra**: corrigir o código.
- **Dado realmente ruim**: ele permanece rejeitado e é apenas monitorado.

Consultas de exemplo para este projeto (elas usam `your_catalog` como marcador de posição para o catálogo do projeto; substitua pelo seu, neste repositório `databricks_course_ws_new`):

```sql
-- Proporção de registros Bronze com dados resgatados, por dia de ingestão
SELECT to_date(_ingested_at) AS ingestion_date,
       count(*) AS records,
       count_if(_rescued_data IS NOT NULL) AS rescued_records,
       round(100 * count_if(_rescued_data IS NOT NULL) / count(*), 2) AS rescued_pct
FROM your_catalog.bronze.spotify_events_raw
GROUP BY 1
ORDER BY 1 DESC;

-- Quais arquivos trazem os dados resgatados
SELECT _source_file, count(*) AS rescued_records
FROM your_catalog.bronze.spotify_events_raw
WHERE _rescued_data IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC;

-- Quarentena por dia e motivo
SELECT to_date(rejected_at) AS rejected_date, rejection_reason, count(*) AS records
FROM your_catalog.silver.spotify_events_quarantine
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- Taxa de quarentena por dia de ingestão
SELECT q.event_date, q.quarantined, s.accepted,
       round(100 * q.quarantined / (q.quarantined + s.accepted), 2) AS quarantine_pct
FROM (SELECT to_date(_ingested_at) AS event_date, count(*) AS quarantined
      FROM your_catalog.silver.spotify_events_quarantine GROUP BY 1) q
JOIN (SELECT to_date(_ingested_at) AS event_date, count(*) AS accepted
      FROM your_catalog.silver.spotify_events GROUP BY 1) s USING (event_date)
ORDER BY 1 DESC;
```

### 4. Correção, e o que acontece com os registros

**Normalmente eles não são apagados.** O padrão habitual:

- Os dados brutos na Bronze são imutáveis e retidos, justamente para poderem ser reprocessados.
- Os registros em quarentena permanecem e carregam um status, por exemplo `PENDING`, `RESOLVED` ou `DISCARDED`, às vezes com a data da resolução e a pessoa ou o job responsável.
- Depois que o problema é corrigido, os registros rejeitados são **reaplicados** (replayed): lidos novamente, validados com a regra corrigida e incorporados à Silver com um `MERGE` idempotente, para que nada seja duplicado. Como o arquivo já foi lido, a carga regular não pega esses registros de novo (a ingestão e o stream da Silver controlam o que já processaram); por isso, reaplicá-los exige um processo de reprocessamento separado.
- A exclusão acontece apenas por uma política de retenção (por exemplo, após 90 dias) ou por exigência legal, nunca porque o registro foi corrigido.

### 5. Encerramento

O incidente é registrado (ticket) com a causa, o que foi reprocessado e a confirmação de que as métricas voltaram ao normal. Quando a causa está a montante, o ideal é corrigir na origem, para que o paliativo não vire permanente.

### Quem marca um registro como resolvido

Na maioria das vezes, o próprio job de reprocessamento, e não uma pessoa:

1. O job lê as linhas da quarentena que estão `PENDING`.
2. Aplica a elas as regras **atuais**.
3. As que agora passam são incorporadas à Silver.
4. Essas mesmas linhas são atualizadas para `RESOLVED`, com `resolved_at` e o id da execução.
5. As que ainda falham permanecem `PENDING`, geralmente com um contador de tentativas.

Uma pessoa decide **quando** executá-lo, normalmente logo depois de implantar a correção, ou por agendamento quando a causa é transitória (por exemplo, dados de referência que ainda não tinham chegado). Uma pessoa também marca um registro como `DISCARDED` quando ele é realmente um dado ruim, registrando quem decidiu e por quê.

Uma alternativa mais simples é não ter coluna de status e derivar o conjunto pendente: as linhas da quarentena cujo `event_id` ainda não está na Silver. Ela não pode ficar inconsistente, mas perde quem resolveu um registro, quando e por quê, e não distingue "resolvido" de "descartado".

## O que este projeto faz hoje, e a lacuna

Implementado:

- `_rescued_data` é preservado da Bronze até a Silver, de modo que o schema drift nunca é descartado silenciosamente.
- Registros inválidos vão para a quarentena com um `rejection_reason`, mantendo os valores brutos originais (`duration_played_sec` e `timestamp` são guardados como strings).
- Os volumes são auditados por lote e por arquivo, e `gold.field_quality` mostra quais campos causam mais perdas.
- Nada é apagado.

Não implementado:

- A tabela de quarentena **não tem status**, então não há como distinguir um registro já tratado de um pendente.
- **Não há job de reprocessamento.** A Silver lê a Bronze como stream com checkpoint, então não lê de novo o que já processou. Depois de corrigir uma regra, as linhas já rejeitadas não voltam sozinhas. Aplicar a correção ao passado exige um job dedicado (abaixo) ou o reset do checkpoint da Silver, que é muito mais pesado.

## Proposta: `reprocess_quarantine`

Não implementado. Esboço de um desenho:

**Mudança de schema** em `silver.spotify_events_quarantine`: `status STRING` (`PENDING` por padrão), `resolved_at TIMESTAMP`, `resolved_run_id STRING`, `attempts INT`.

**Novo job** `reprocess_quarantine`, com a lógica em `src/pipeline/` e um notebook fino, como as outras etapas:

1. Ler as linhas `PENDING`.
2. Passá-las novamente por `normalize_batch` (elas carregam os valores brutos que ele espera).
3. Separar em linhas que agora passam e linhas que ainda falham.
4. Fazer `MERGE` das linhas aprovadas em `silver.spotify_events`, usando `dedupe_valid_records` e a mesma atualização condicional do job Silver principal.
5. Só depois disso, atualizar as linhas da quarentena para `RESOLVED` (ou incrementar `attempts` nas demais).
6. Gravar uma linha em `pipeline_audit` para a execução.

**Pontos de desenho a acertar:**

- **Ordem e idempotência.** O Delta não oferece transação entre duas tabelas; portanto, faça o merge na Silver primeiro e a atualização do status depois. Se o job morrer no meio, executá-lo de novo é seguro, porque o `MERGE` é idempotente.
- **Manter o `_ingested_at` e o `_source_file` originais.** O `MERGE` da Silver só sobrescreve uma linha quando a que chega é mais recente; por isso, um registro reaplicado não pode parecer mais novo que uma versão posterior do mesmo evento que já chegou à Silver.
- **Linhas que nunca se recuperam.** Acrescentar um status `DISCARDED` e uma regra como "após N tentativas, parar de tentar e sinalizar para revisão", para que o job não tente para sempre.
- **Gatilho.** Começar com uma execução manual depois de uma correção, que é a mais simples de raciocinar. Adicionar um agendamento apenas para causas transitórias.
- **Testes.** A parte pura (separar em recuperados e ainda com falha) pode ser testada sem cluster, como o restante de `src/pipeline/`.

Uma verificação de aceitação para uma implementação: rejeitar um registro de propósito (por exemplo, um `track_id` vazio), alterar a regra para que ele agora passe, executar o job e verificar que o registro está na Silver, está `RESOLVED` na quarentena e que uma segunda execução não muda nada.
