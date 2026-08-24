# ADR-013: Future Migration Path for Offline Store

* **Status:** Accepted
* **Date:** 2026-08-23
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel currently uses PostgreSQL as the Offline Feature Store.

The Worker uses a dual-write strategy:

```text
Worker
  |
  +--> Redis
  |
  +--> PostgreSQL
```

Redis serves the low-latency online inference path, while PostgreSQL stores historical features for offline processing, analysis, and future model retraining.

PostgreSQL is appropriate for the current Sentinel project because the expected data volume is in the GB range.

It provides:

* Durable storage.
* SQL querying.
* Simple integration with Python.
* Persistent historical feature storage.
* Easy local and Kubernetes deployment.

However, PostgreSQL has scalability limits as the historical feature dataset grows.

At TB-scale, large training-data queries and repeated full-table scans can become increasingly expensive in terms of:

* Query latency.
* CPU usage.
* Disk I/O.
* Storage requirements.
* Database maintenance.

## Current Storage Projection

The Sentinel environment was measured with the following values:

```text
Producer rate:              ~5 events/sec
Average PostgreSQL row:     ~1816 bytes
PostgreSQL PVC:             2 GiB
Redis feature size:         ~3688 bytes
Redis TTL:                  3600 seconds
```

At approximately 5 events per second:

```text
5 * 86,400 = 432,000 rows/day
```

Estimated PostgreSQL growth:

```text
432,000 * 1816 bytes
≈ 784 MB/day
≈ 0.73 GiB/day
```

With the current 2 GiB PostgreSQL PVC:

```text
2 GiB / 0.73 GiB/day
≈ 2.7 days
```

Therefore, without retention or additional storage, the current PostgreSQL PVC could fill in less than three days under continuous ingestion.

A safer operational threshold is approximately 80% disk utilization, which would be reached after roughly two days.

## Decision

Continue using PostgreSQL as the Offline Feature Store for the current scale of Project Sentinel.

PostgreSQL is sufficient while the historical feature dataset remains in the GB range.

Redis will remain the Online Feature Store for low-latency inference.

The current architecture remains:

### Online Inference

```text
Redis
  |
  v
Sentinel API
  |
  v
Triton
```

### Offline Storage

```text
Worker
  |
  v
PostgreSQL
```

If the offline dataset grows toward TB-scale or PostgreSQL becomes a bottleneck for model retraining, Sentinel should migrate historical features to a storage system designed for large analytical datasets.

The preferred future options are:

* **Object Storage / Data Lake:** S3-compatible storage with Parquet files.
* **Data Warehouse:** BigQuery or Snowflake.

The future architecture would become:

### Online

```text
Redis
  |
  v
Sentinel API
  |
  v
Triton
```

### Offline / Retraining

```text
S3 + Parquet
      |
      v
Training Pipeline
```

or:

```text
BigQuery / Snowflake
          |
          v
   Training Pipeline
```

## Storage Retention Policy

### Redis

Redis is used only for hot online features.

Current TTL:

```text
3600 seconds
```

Therefore:

```text
Redis retention = 1 hour
```

At approximately 5 events per second:

```text
5 * 3600 = 18,000 active features
```

With approximately 3688 bytes per feature:

```text
18,000 * 3688
≈ 63 MiB
```

The TTL prevents Redis memory usage from growing indefinitely.

### PostgreSQL

PostgreSQL does not provide Redis-style TTL automatically.

For the current 2 GiB PVC and ingestion rate, the recommended development retention policy is approximately:

```text
2 days
```

Older data should be:

* Deleted.
* Archived.
* Or moved to long-term object storage.

This prevents the PostgreSQL PVC from reaching full capacity.

In a production environment, retention should be based on storage capacity, retraining requirements, compliance requirements, and business needs.

## Migration Triggers

Migration away from PostgreSQL should be considered when one or more of the following occur:

### 1. Dataset Size

Historical feature data approaches TB-scale.

### 2. Retraining Performance

Training-data `SELECT` queries become too slow for acceptable retraining times.

### 3. Database Resource Pressure

Large analytical queries create significant:

* CPU pressure.
* Memory pressure.
* Disk I/O.
* Query contention.

### 4. Storage Growth

PostgreSQL storage requirements become expensive or operationally difficult to manage.

### 5. Analytical Workloads

The system requires large distributed scans, aggregations, or repeated processing of historical datasets.

## Why S3 + Parquet

S3-compatible object storage with Parquet is a strong future option for ML training datasets.

Advantages include:

* Cheap scalable object storage.
* Efficient columnar storage.
* Compression.
* Support for very large datasets.
* Integration with distributed processing tools.
* Good fit for immutable historical ML data.

Instead of repeatedly querying millions or billions of PostgreSQL rows, training jobs could read partitioned Parquet datasets directly from object storage.

## Why BigQuery or Snowflake

A Data Warehouse becomes useful when Sentinel requires large-scale analytical SQL workloads.

Advantages include:

* Managed infrastructure.
* Distributed query execution.
* Large-scale analytical queries.
* Separation of storage and compute.
* Reduced operational database management.

The tradeoff is increased cloud dependency and cost.

## Consequences

### Positive

* PostgreSQL keeps the current Sentinel architecture simple.
* No unnecessary Big Data infrastructure is introduced at the current scale.
* Redis remains optimized for low-latency online inference.
* Historical data remains durable.
* A clear migration path exists as the dataset grows.
* Storage growth and retention limits are explicitly documented.

### Negative

* PostgreSQL storage grows continuously without retention.
* The current 2 GiB PVC is too small for long-term continuous ingestion.
* Retention or archival must be implemented.
* PostgreSQL will eventually become inefficient for very large ML datasets.
* Future migration will require changes to the offline training-data pipeline.

## Alternatives Considered

### Keep PostgreSQL Indefinitely

**Advantages:**

* Simple architecture.
* Existing SQL tooling.
* No migration work.

**Rejected because:**

* Large historical feature datasets can create expensive scans.
* Storage and query performance become increasingly difficult at TB-scale.
* PostgreSQL is not intended to act as a large-scale Data Lake.

### S3 + Parquet Immediately

**Advantages:**

* Highly scalable.
* Low storage cost.
* Good fit for ML training data.

**Rejected for now because:**

* Adds unnecessary infrastructure complexity.
* Current Sentinel data volume does not justify it.
* PostgreSQL is sufficient for the current GB-scale project.

### BigQuery / Snowflake Immediately

**Advantages:**

* Excellent analytical scalability.
* Managed distributed query engine.

**Rejected for now because:**

* Additional cloud cost.
* Vendor dependency.
* Unnecessary for the current project scale.

## Validation

The decision was validated using the current Sentinel environment.

Measured values:

```text
PostgreSQL rows:             301
Average row size:            1816 bytes
PostgreSQL PVC:              2 GiB
Estimated growth:            ~0.73 GiB/day
Estimated PVC fill time:     ~2.7 days

Redis TTL:                   1 hour
Redis feature memory usage:  ~3688 bytes
Estimated Redis feature set: ~63 MiB
```

These measurements confirm that:

* Redis TTL successfully bounds online feature storage.
* PostgreSQL requires an explicit retention or archival policy.
* PostgreSQL remains suitable for the current project scale but is not the intended long-term solution for TB-scale historical datasets.

## Final Decision

Continue using **PostgreSQL as the Offline Feature Store** while Project Sentinel operates at GB-scale.

Use:

```text
Redis TTL:             1 hour
PostgreSQL retention:  approximately 2 days
```

for the current development environment and storage allocation.

If the historical feature dataset approaches TB-scale or retraining queries become a significant bottleneck, migrate the Offline Feature Store to:

```text
S3-compatible Object Storage + Parquet
```

or a managed analytical warehouse such as:

```text
BigQuery / Snowflake
```

Redis will remain the Online Feature Store for low-latency inference.
