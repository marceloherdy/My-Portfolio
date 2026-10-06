**English** | [Português](error-handling.pt-BR.md)

# Handling rescued and quarantined records

This document explains what the pipeline does with records that have problems, how data teams usually handle them after a daily load, and what is still missing in this project to close the loop. The last section is a design proposal that has **not** been implemented, and is a good starting point for anyone who wants to extend the project.

## Two different mechanisms

They are often confused, and they answer different questions.

| | `_rescued_data` | Quarantine (`silver.spotify_events_quarantine`) |
| --- | --- | --- |
| What it is | A **column** of the Bronze table | A **table** in the Silver schema |
| Filled by | Auto Loader (`schemaEvolutionMode = rescue`) | The Silver transformation (`normalize_batch`) |
| Trigger | The data does not match the schema: new column, different type, different case | The data breaks a business rule: empty `track_id`, negative duration, invalid timestamp |
| What happens to the record | It is **still ingested**; the offending value is kept as JSON in the column | It is **removed from the Silver table** and stored in the quarantine table with a `rejection_reason` |
| Question it answers | "Did the source change shape?" | "Is this record valid for the business?" |

Nothing is deleted in either case. Bronze is an append-only copy of what arrived, and the quarantine table is append-only as well.

## How teams usually handle it after the daily load

### 1. Who looks at it

Usually the data engineer who owns the pipeline, often on a rotation (on-call), together with the owner of the source system or a data steward when the cause is upstream. Nobody inspects the tables every day: the work is driven by alerts.

### 2. Detection

- Every run records its volumes: records read, rejected and with rescued data. In this project that is `ops.pipeline_audit`, `ops.file_audit` and `gold.data_quality_summary`.
- Thresholds trigger notifications (email, chat, ticket). For example: a quarantine rate above a set percentage, or any increase in `_rescued_data`.
- A dashboard shows the trend over time.
- Data quality tools (Lakeflow expectations, Great Expectations, Soda) cover part of this.

### 3. Triage

Mostly by queries, but guided: group by type of problem (rejection reason, field, source file, date) instead of reading record by record. The goal is to find the cause, which usually falls into one of three categories:

- **The source changed** (new field, different type): talk to the team that owns the data, or update the contract.
- **A bug in the pipeline or in a rule**: fix the code.
- **Genuinely bad data**: it stays rejected and is only monitored.

Example queries for this project (they use `your_catalog` as a placeholder for the catalog of the project; replace it with yours, in this repository `databricks_course_ws_new`):

```sql
-- Share of Bronze records with rescued data, per ingestion day
SELECT to_date(_ingested_at) AS ingestion_date,
       count(*) AS records,
       count_if(_rescued_data IS NOT NULL) AS rescued_records,
       round(100 * count_if(_rescued_data IS NOT NULL) / count(*), 2) AS rescued_pct
FROM your_catalog.bronze.spotify_events_raw
GROUP BY 1
ORDER BY 1 DESC;

-- Which files carry the rescued data
SELECT _source_file, count(*) AS rescued_records
FROM your_catalog.bronze.spotify_events_raw
WHERE _rescued_data IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC;

-- Quarantine by day and reason
SELECT to_date(rejected_at) AS rejected_date, rejection_reason, count(*) AS records
FROM your_catalog.silver.spotify_events_quarantine
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- Quarantine rate per ingestion day
SELECT q.event_date, q.quarantined, s.accepted,
       round(100 * q.quarantined / (q.quarantined + s.accepted), 2) AS quarantine_pct
FROM (SELECT to_date(_ingested_at) AS event_date, count(*) AS quarantined
      FROM your_catalog.silver.spotify_events_quarantine GROUP BY 1) q
JOIN (SELECT to_date(_ingested_at) AS event_date, count(*) AS accepted
      FROM your_catalog.silver.spotify_events GROUP BY 1) s USING (event_date)
ORDER BY 1 DESC;
```

### 4. Correction, and what happens to the records

**They are normally not deleted.** The usual pattern:

- The raw data in Bronze is immutable and retained, precisely so it can be reprocessed.
- Quarantined records stay and carry a status, for example `PENDING`, `RESOLVED` or `DISCARDED`, sometimes with the resolution date and the person or job responsible.
- Once the problem is fixed, the rejected records are **replayed**: read again, validated with the corrected rule and merged into Silver with an idempotent `MERGE`, so nothing is duplicated. Because the file has already been read, the regular load does not pick these records up again (ingestion and the Silver stream track what they have processed), so replaying them needs a separate reprocessing process.
- Deletion happens only through a retention policy (for example after 90 days) or a legal requirement, never because the record was fixed.

### 5. Closing

The incident is recorded (ticket) with the cause, what was reprocessed and confirmation that the metrics are back to normal. When the cause is upstream, the ideal outcome is a fix at the source, so the workaround does not become permanent.

### Who marks a record as resolved

Mostly the reprocessing job itself, not a person:

1. The job reads the quarantine rows that are `PENDING`.
2. It applies the **current** rules to them.
3. The ones that now pass are merged into Silver.
4. Those same rows are updated to `RESOLVED`, with `resolved_at` and the run id.
5. The ones that still fail stay `PENDING`, usually with an attempt counter.

A person decides **when** to run it, normally right after deploying the fix, or on a schedule when the cause is transient (for example reference data that had not arrived yet). A person also marks a record `DISCARDED` when it is genuinely bad data, recording who decided and why.

A simpler alternative is to have no status column and derive the pending set: quarantine rows whose `event_id` is not yet in Silver. It cannot be inconsistent, but it loses who resolved a record, when and why, and cannot tell "resolved" from "discarded".

## What this project does today, and the gap

Implemented:

- `_rescued_data` is preserved from Bronze through Silver, so schema drift is never silently dropped.
- Invalid records go to quarantine with a `rejection_reason`, keeping the original raw values (`duration_played_sec` and `timestamp` are stored as strings).
- Volumes are audited per batch and per file, and `gold.field_quality` shows which fields cause the most loss.
- Nothing is deleted.

Not implemented:

- The quarantine table has **no status**, so there is no way to tell a handled record from a pending one.
- There is **no reprocessing job**. Silver reads Bronze as a stream with a checkpoint, so it does not read again what it already processed. After fixing a rule, rows already rejected do not come back by themselves. Applying the fix to the past needs a dedicated job (below) or a reset of the Silver checkpoint, which is much heavier.

## Proposal: `reprocess_quarantine`

Not implemented. Sketch of a design:

**Schema change** on `silver.spotify_events_quarantine`: `status STRING` (`PENDING` by default), `resolved_at TIMESTAMP`, `resolved_run_id STRING`, `attempts INT`.

**New job** `reprocess_quarantine`, with logic in `src/pipeline/` and a thin notebook, like the other stages:

1. Read the `PENDING` rows.
2. Feed them through `normalize_batch` again (they carry the raw values it expects).
3. Split into rows that now pass and rows that still fail.
4. `MERGE` the passing rows into `silver.spotify_events` using `dedupe_valid_records` and the same conditional update as the main Silver job.
5. Only after that, update the quarantine rows to `RESOLVED` (or increment `attempts` for the others).
6. Write a `pipeline_audit` row for the run.

**Design points to get right:**

- **Order and idempotency.** Delta does not offer a transaction across two tables, so merge into Silver first and update the status second. If the job dies in between, running it again is safe because the `MERGE` is idempotent.
- **Keep the original `_ingested_at` and `_source_file`.** The Silver `MERGE` only overwrites a row when the incoming one is newer, so a replayed record must not look newer than a later version of the same event that already reached Silver.
- **Rows that never recover.** Add a `DISCARDED` status and a rule such as "after N attempts, stop retrying and flag for review", so the job does not retry forever.
- **Triggering.** Start with a manual run after a fix, which is the simplest to reason about. Add a schedule only for transient causes.
- **Tests.** The pure part (split into recovered and still failing) can be tested without a cluster, like the rest of `src/pipeline/`.

An acceptance check for an implementation: reject a record on purpose (for example an empty `track_id`), change the rule so it now passes, run the job, and verify that the record is in Silver, is `RESOLVED` in quarantine and that a second run changes nothing.
