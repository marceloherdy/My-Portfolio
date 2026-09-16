---
name: pipeline-check
description: Valida o bundle do projeto (databricks bundle validate) e ajuda a inspecionar a última execução do pipeline Bronze/Silver via as tabelas de auditoria em databricks_course_ws_new.ops. Use quando o usuário pedir para checar o estado do pipeline, validar o bundle, ou investigar falhas/execuções recentes.
---

## Passos

1. Rode `databricks bundle validate -t dev` na raiz do projeto. Reporte erros de validação ao usuário antes de prosseguir.

2. Pergunte ao usuário se deseja disparar algum job (`producer_simulator`, `bronze_ingestion`, `silver_transformation`) via `databricks bundle run <job> -t dev`. **Nunca rode automaticamente sem confirmação explícita** — os jobs escrevem em tabelas reais do workspace.

3. Para inspecionar a última execução:
   a. Rode `databricks sql warehouses list` para checar se há um SQL warehouse disponível neste workspace.
   b. Se houver um warehouse: use `databricks sql query --warehouse-id <id>` com as queries já documentadas em [docs/auditoria.md](../../../docs/auditoria.md) (últimas execuções, arquivos processados na última execução, falhas, execuções sem novos arquivos).
   c. Se não houver warehouse configurado ou o comando falhar: não force — imprima as queries de `docs/auditoria.md` e instrua o usuário a rodá-las no notebook do Databricks ou no SQL Editor do Workspace, citando as tabelas `databricks_course_ws_new.ops.pipeline_audit` e `databricks_course_ws_new.ops.file_audit`.

4. Resuma ao final: bundle validado (sim/não), job(s) disparado(s) (se algum), e status da última execução (se obtido).
