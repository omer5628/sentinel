# ADR-014: Rejection of Direct-DB Access for Inference

* **Status:** Accepted
* **Date:** 2026-08-24
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel uses two feature stores with different responsibilities:

```text
Worker
  |
  +--> Redis
  |
  +--> PostgreSQL
```

Redis acts as the **Online Feature Store** and provides features to the real-time inference API.

PostgreSQL acts as the **Offline Feature Store** and stores historical features for:

* Analysis.
* Auditing.
* Labeling.
* Model retraining.
* Long-term feature history.

The normal online inference path is:

```text
Client
  |
  v
Sentinel API
  |
  v
Redis
  |
  v
Triton
  |
  v
Prediction
```

An anti-pattern experiment was performed to determine whether Redis is actually necessary or whether the API could query PostgreSQL directly for every prediction.

The experimental architecture was:

```text
Client
  |
  v
Sentinel API
  |
  v
PostgreSQL
  |
  v
Triton
  |
  v
Prediction
```

The purpose of the experiment was to measure the effect of direct PostgreSQL access on:

* End-to-end prediction latency.
* P95 and P99 latency.
* Request failures.
* PostgreSQL CPU usage.
* Separation between online and offline workloads.

---

## Experiment

The Sentinel API was temporarily modified to bypass Redis.

Instead of:

```text
GET feat:<image_id>
```

from Redis, every prediction executed:

```sql
SELECT vector
FROM feature_log
WHERE image_id = %s
ORDER BY timestamp DESC
LIMIT 1;
```

The PostgreSQL table already contained an index on:

```text
image_id
```

Therefore, the experiment did not intentionally use an unindexed or inefficient query.

A reusable PostgreSQL connection pool was also used.

This avoided creating a new database connection for every request and made the comparison more representative of a realistic implementation.

The remaining inference pipeline was unchanged.

Both versions used:

* The same Sentinel API.
* The same feature data.
* The same Triton inference service.
* The same V1 model.
* The same V2 shadow inference.
* The same load test.

---

## Load Test

The test generated approximately:

```text
50 requests/second
```

for:

```text
30 seconds
```

Total:

```text
1500 prediction requests
```

The load-test tool measured full HTTP request latency, including feature lookup and inference.

Metrics recorded:

* Successful requests.
* Failed requests.
* Achieved RPS.
* Average latency.
* P95 latency.
* P99 latency.

---

## Redis Baseline

The first Redis baseline produced:

```text
Total requests:      1500
Successful requests: 1500
Failed requests:     0
Achieved RPS:        49.96

Average latency:     38.84 ms
P95 latency:         71.28 ms
P99 latency:         161.02 ms
```

This established the normal Online Feature Store behavior before the experiment.

---

## PostgreSQL Bad Version

During the direct PostgreSQL experiment, the most significant 50 RPS run produced:

```text
Total requests:      1500
Successful requests: 1493
Failed requests:     7
Achieved RPS:        49.98

Average latency:     122.97 ms
P95 latency:         668.75 ms
P99 latency:         937.89 ms
```

Compared with the initial Redis baseline:

```text
Redis P99:       161.02 ms
PostgreSQL P99:  937.89 ms
```

The PostgreSQL version therefore exhibited substantially worse tail latency during this run.

P95 also increased significantly:

```text
Redis P95:       71.28 ms
PostgreSQL P95:  668.75 ms
```

Additionally, seven requests failed during the PostgreSQL test, while the Redis baseline completed all requests successfully.

---

## PostgreSQL CPU Observation

PostgreSQL CPU usage was measured using Kubernetes Metrics Server.

Idle PostgreSQL usage was approximately:

```text
CPU:    4-5m
Memory: 36 MiB
```

During the 50 RPS direct-database experiment, observed PostgreSQL CPU usage increased to approximately:

```text
CPU:    11m
Memory: 37 MiB
```

Therefore, database CPU usage increased by roughly:

```text
2.2x - 2.75x
```

The database was **not CPU saturated** in this development environment.

However, the experiment demonstrated that online prediction traffic directly consumes resources from the Offline Feature Store.

At larger production scale, this creates contention between:

```text
Online inference
        +
Historical queries
        +
Model retraining
        +
Data analysis
```

---

## Recovery Test

After the experiment, the PostgreSQL lookup was removed and the API was restored to Redis.

The recovery test used the same:

```text
50 RPS
30 seconds
1500 requests
```

Results:

```text
Total requests:      1500
Successful requests: 1500
Failed requests:     0
Achieved RPS:        49.96

Average latency:     73.78 ms
P95 latency:         266.91 ms
P99 latency:         377.08 ms
```

Compared with the PostgreSQL bad version:

```text
PostgreSQL P99: 937.89 ms
Redis P99:      377.08 ms
```

The recovery also eliminated the seven request failures observed in the PostgreSQL run.

---

## Run-to-Run Variability

Not every experimental run produced identical latency.

One earlier direct-PostgreSQL run completed successfully with:

```text
Average latency: 32.17 ms
P95 latency:     53.05 ms
P99 latency:     118.20 ms
Failed requests: 0
```

Redis measurements also varied between runs.

For example:

```text
Redis baseline P99: 161.02 ms
Redis recovery P99: 377.08 ms
```

Therefore, the experiment does **not** prove that PostgreSQL will be slower than Redis on every individual run in this small local environment.

Instead, it demonstrates that direct PostgreSQL access introduces additional variability, tail-latency risk, database resource consumption, and coupling between online and offline workloads.

The architectural decision is therefore based on both measured behavior and workload isolation.

---

## Decision

Sentinel will continue using **Redis as the Online Feature Store**.

The real-time inference path remains:

```text
Client
  |
  v
Sentinel API
  |
  v
Redis
  |
  v
Triton
  |
  v
Prediction
```

PostgreSQL will remain the **Offline Feature Store**:

```text
Worker
  |
  v
PostgreSQL
  |
  +--> Historical Analysis
  +--> Labeling
  +--> Retraining
  +--> Auditing
```

The Sentinel API must not query PostgreSQL directly for features on the normal synchronous inference path.

---

## Why Redis Is Preferred

### Low-Latency Access

Redis keeps online features in memory and is designed for low-latency key-based access.

The API can retrieve a feature using:

```text
feat:<image_id>
```

without executing an SQL query.

### Workload Isolation

Using Redis separates:

```text
Online traffic
```

from:

```text
Offline analytical traffic
```

Without this separation, every prediction request adds workload to PostgreSQL.

### Reduced Tail-Latency Risk

The direct PostgreSQL experiment produced a P99 as high as:

```text
937.89 ms
```

while Redis measurements produced lower P99 values during the validated baseline and recovery tests.

### Database Protection

PostgreSQL should remain available for:

* Historical storage.
* Training dataset generation.
* Labeling.
* Data analysis.
* Administrative queries.

Inference traffic should not compete with these workloads for the same database resources.

### Independent Scaling

With separate stores:

```text
Redis
```

can be scaled for online inference traffic while:

```text
PostgreSQL
```

can be scaled according to historical storage and analytical requirements.

This allows the two workloads to evolve independently.

---

## Consequences

### Positive

* Low-latency online feature access.
* Better isolation between online and offline workloads.
* Reduced pressure on PostgreSQL.
* Lower tail-latency risk.
* Independent scaling of online and offline stores.
* PostgreSQL remains focused on durable historical storage.
* Redis TTL bounds the size of the online feature set.

### Negative

* Features must be written to two systems.
* Redis adds additional infrastructure.
* Redis data is temporary and must not be treated as historical storage.
* Dual-write logic requires monitoring and error handling.
* Additional memory is required for Redis.

These costs are accepted because they provide a clearer separation between real-time and offline workloads.

---

## Alternatives Considered

### Direct PostgreSQL Access

Architecture:

```text
API
 |
 v
PostgreSQL
 |
 v
Triton
```

**Advantages:**

* Simpler infrastructure.
* No Redis dependency.
* Only one feature storage system.

**Rejected because:**

* Every prediction produces database traffic.
* Online and offline workloads become coupled.
* PostgreSQL CPU usage increases with inference traffic.
* Tail latency can become significantly worse under load.
* Database queries used for analysis or retraining may interfere with inference.
* The experiment produced request failures under 50 RPS.

---

### Redis Online Store

Architecture:

```text
API
 |
 v
Redis
 |
 v
Triton
```

**Advantages:**

* In-memory feature lookup.
* Low-latency access.
* Clear online/offline separation.
* Independent scaling.
* PostgreSQL is protected from inference traffic.

Selected as the preferred architecture.

---

## Evidence

Experiment configuration:

```text
Target load:         50 RPS
Duration:            30 seconds
Requests per run:    1500
PostgreSQL index:    image_id
DB connection:       reusable connection pool
```

Initial Redis baseline:

```text
Average: 38.84 ms
P95:     71.28 ms
P99:     161.02 ms
Errors:  0
```

PostgreSQL stressed run:

```text
Average: 122.97 ms
P95:     668.75 ms
P99:     937.89 ms
Errors:  7
```

Redis recovery:

```text
Average: 73.78 ms
P95:     266.91 ms
P99:     377.08 ms
Errors:  0
```

PostgreSQL resource observation:

```text
Idle CPU:       approximately 4-5m
Load CPU:       approximately 11m
Idle memory:    36 MiB
Load memory:    37 MiB
```

---

## Final Decision

Reject direct PostgreSQL access from the real-time prediction path.

Use:

```text
Redis = Online Feature Store
PostgreSQL = Offline Feature Store
```

The anti-pattern experiment demonstrated that direct PostgreSQL access can introduce:

* Higher P95/P99 latency.
* Request failures.
* Additional PostgreSQL CPU usage.
* Greater latency variability.
* Coupling between online and offline workloads.

Even though the small local environment did not show PostgreSQL performing worse in every individual run, the stressed experiment demonstrated the operational risk of using the Offline Feature Store directly for synchronous inference.

Redis therefore remains mandatory in the normal Sentinel online inference architecture.
