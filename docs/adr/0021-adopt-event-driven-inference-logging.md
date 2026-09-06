# ADR-0021: Adopt Event-Driven Inference Logging

* **Status:** Accepted
* **Date:** 2026-09-06
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel performs real-time inference through the Sentinel Serving API.

The current inference path is:

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
ClearML Serving Canary
  |
  v
Model v1 / Model v2
```

For operational monitoring, model evaluation, auditing, and future labeling workflows, Sentinel must also persist the result of every successful inference.

The persisted inference record must contain:

* A unique inference identifier.
* The processed image identifier.
* The model version selected by the canary router.
* The predicted class.
* The prediction confidence.
* The inference timestamp.

Writing directly from the Serving API to PostgreSQL would introduce the offline database into the synchronous inference path.

This would increase coupling between online inference and durable persistence and could cause PostgreSQL latency or availability problems to directly affect inference requests.

Sentinel already uses RabbitMQ as its messaging infrastructure and can use it to decouple inference execution from durable inference-event persistence.

## Decision

Sentinel will use an event-driven architecture for inference-result persistence.

After a successful model prediction, the Sentinel API creates a versioned inference event using the `InferenceEventV1` data contract.

The event contains:

```text
schema_version
inference_id
image_id
timestamp
model_version
predicted_class
confidence
```

The high-level flow is:

```text
Client
  |
  v
Sentinel API
  |
  +--> Redis
  |
  +--> ClearML Serving Canary
          |
          v
      Prediction
          |
          v
   InferenceEventV1
          |
          v
      RabbitMQ
   inference_events
          |
          v
   Inference Logger
          |
          v
      PostgreSQL
    inference_log
```

The Sentinel API does not write inference records directly to PostgreSQL.

Instead, it publishes the inference event to the durable RabbitMQ queue:

```text
inference_events
```

Messages are published as persistent RabbitMQ messages.

A dedicated consumer:

```text
sentinel.consumers.inference_logger
```

consumes the events and writes them to the PostgreSQL `inference_log` table.

## Delivery and Persistence Semantics

The Inference Logger validates each message against `InferenceEventV1` before writing it to PostgreSQL.

The consumer follows this processing order:

```text
Receive message
      |
      v
Validate schema
      |
      v
Insert into PostgreSQL
      |
      v
Commit transaction
      |
      v
ACK RabbitMQ message
```

A RabbitMQ message is acknowledged only after the PostgreSQL transaction commits successfully.

If PostgreSQL persistence fails, the message is negatively acknowledged and requeued.

Invalid inference events are rejected and are not requeued.

The current implementation does not yet route rejected inference events to a dedicated dead-letter queue. A dedicated inference-event DLQ may be added in a later iteration.

## Idempotency

Every inference event receives a unique UUID:

```text
inference_id
```

The `inference_log` table uses `inference_id` as its primary key.

The consumer inserts records using conflict-safe behavior:

```sql
ON CONFLICT (inference_id) DO NOTHING
```

This makes repeated delivery of the same inference event safe.

RabbitMQ may redeliver a message when a consumer fails before acknowledgement, but the same `inference_id` will not create duplicate database rows.

Different inference requests for the same image receive different `inference_id` values.

Therefore this is valid:

```text
image_id = image-123
inference_id = A
model_version = v1

image_id = image-123
inference_id = B
model_version = v2
```

Each row represents a separate inference operation.

## Database Schema

Inference events are persisted in:

```text
inference_log
```

The table contains:

```text
inference_id
image_id
model_version
predicted_class
confidence
created_at
```

Indexes are maintained for:

```text
image_id
model_version
created_at
```

Database schema changes are managed through the Sentinel Helm deployment.

Existing PostgreSQL environments are upgraded by a Helm `pre-upgrade` migration Job before application deployment continues.

This prevents application components from depending on a database schema that has not yet been created.

## Failure Behavior

### PostgreSQL Unavailable

The Inference Logger does not acknowledge the event.

The message is requeued so persistence can be attempted again.

The Serving API remains separated from the PostgreSQL connection.

### Invalid Inference Event

The message fails schema validation and is rejected without requeueing.

A future DLQ will provide durable inspection of rejected messages.

### Inference Logger Unavailable

RabbitMQ retains queued inference events until a consumer becomes available again, subject to the broker's persistence and retention configuration.

### RabbitMQ Unavailable

The current API publisher cannot deliver the inference event.

Inference execution and inference-event persistence are separate responsibilities, but the current publisher uses a synchronous Pika client when publishing the event.

Therefore RabbitMQ connection behavior may still add latency to the HTTP request.

The publishing path should not be described as fully asynchronous.

Future iterations may introduce a bounded background publisher, transactional outbox, or another reliability mechanism if stronger delivery guarantees are required.

## Alternatives Considered

### Write Directly from the Sentinel API to PostgreSQL

Rejected.

The flow would become:

```text
API
 |
 +--> Redis
 +--> ClearML Serving
 +--> PostgreSQL
```

This would couple real-time inference directly to the offline database.

PostgreSQL latency, connection exhaustion, or temporary unavailability could directly increase inference latency or cause inference requests to fail.

### Persist Inference Results Inside the Worker

Rejected.

The Worker handles ingestion and feature generation.

Prediction occurs only when the Serving API receives an inference request, so the Worker does not necessarily know which model version was selected or what prediction was returned.

Persisting inference results in the Worker would also mix ingestion and inference responsibilities.

### Do Not Persist Inference Events

Rejected.

Without durable inference history, Sentinel would lose information required for:

* Model-version comparison.
* Canary analysis.
* Operational auditing.
* Prediction monitoring.
* Future labeling workflows.
* Model evaluation.
* Drift analysis.
* Retraining decisions.

## Consequences

### Positive

* PostgreSQL is removed from the direct inference database-write path.
* Inference logging can scale independently from the Serving API.
* RabbitMQ buffers inference events when the consumer is temporarily unavailable.
* Each inference operation is independently traceable using `inference_id`.
* Duplicate message delivery does not create duplicate database records.
* Model versions selected by ClearML canary routing are persisted.
* Inference history becomes available for monitoring, evaluation, and future UI functionality.
* Database schema changes are reproducible through Helm migrations.

### Negative

* RabbitMQ becomes an additional dependency of inference-event persistence.
* Another long-running service, the Inference Logger, must be deployed and monitored.
* Eventual persistence introduces a short delay between prediction and database visibility.
* Invalid events currently have no dedicated DLQ.
* The current synchronous RabbitMQ publisher may add request latency during broker problems.
* Additional monitoring is required for queue depth, consumer health, failed events, and database errors.

## Validation

The decision is considered successfully implemented when:

1. A successful API prediction creates an `InferenceEventV1`.
2. The event is published to the `inference_events` RabbitMQ queue.
3. The Inference Logger consumes the event.
4. The event is validated before database persistence.
5. PostgreSQL commit occurs before RabbitMQ acknowledgement.
6. The result appears in the `inference_log` table.
7. Reprocessing the same `inference_id` does not create a duplicate row.
8. The deployed Inference Logger has an active RabbitMQ consumer.
9. The `inference_events` queue returns to zero pending messages after successful processing.
10. The database migration is applied automatically during Helm upgrades.
11. The complete flow is validated in both development and production environments.

The production validation completed successfully on 2026-09-06 using the flow:

```text
Producer
  |
  v
RabbitMQ video_stream
  |
  v
Worker
  |
  v
Redis
  |
  v
Sentinel API
  |
  v
ClearML Canary
  |
  v
RabbitMQ inference_events
  |
  v
Inference Logger
  |
  v
PostgreSQL inference_log
```
