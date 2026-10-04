---
name: pipeline-check
description: Validates the project bundle (databricks bundle validate) and helps inspect the latest Bronze/Silver/Gold pipeline run through the audit tables in databricks_course_ws_new.ops. Use when the user asks to check the pipeline state, validate the bundle, or investigate recent runs and failures.
---

## Steps

1. Run `databricks bundle validate -t dev` from the project root. Report any validation errors to the user before continuing.

2. Ask the user whether they want to trigger a job (`medallion_pipeline`, `producer_simulator`, `bronze_ingestion`, `silver_transformation`, `gold_aggregation` or `gold_business`) with `databricks bundle run <job> -t dev`. **Never run one automatically without explicit confirmation**: the jobs write to real tables in the workspace.

3. To inspect the latest run:
   a. Run `databricks sql warehouses list` to check whether a SQL warehouse is available in this workspace.
   b. If there is one, use `databricks sql query --warehouse-id <id>` with the queries already documented in [docs/auditing.md](../../../docs/auditing.md) (latest executions, files processed in the latest execution, failures, executions with no new files).
   c. If there is no warehouse or the command fails, do not force it: print the queries from `docs/auditing.md` and tell the user to run them in a Databricks notebook or in the workspace SQL Editor, naming the tables `databricks_course_ws_new.ops.pipeline_audit` and `databricks_course_ws_new.ops.file_audit`.

4. Summarize at the end: whether the bundle validated, which job(s) were triggered (if any), and the status of the latest run (if obtained).
