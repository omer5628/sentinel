# ADR-0022: Adopt Event-Driven Automatic Inference Orchestration

* **Status:** Accepted
* **Date:** 2026-09-08
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel already supports real-time inference through the Sentinel Serving API.

Before automatic inference was introduced, the ingestion and inference flows were separate:

```text
Producer
  |
  v
RabbitMQ video_stream
  |
  v
Worker
  |
  +--> Redis
  |
  +--> PostgreSQL feature_log
```

Inference occurred only when a client explicitly called:

```text
POST /predict/{image_id}
```

This meant that images processed by the ingestion pipeline did not automatically receive:

* A model prediction.
* A prediction confidence.
* A model version.
* A persisted inference record.

The Sentinel monitoring UI therefore could display processed images before an inference result existed.

The project requires processed images to automatically enter the inference workflow while preserving separation between ingestion and model serving.

Inference must not be performed directly inside the Worker because ingestion and model serving must remain independently scalable and independently recoverable.

## Decision

Sentinel will use RabbitMQ to orchestrate automatic inference through a dedicated Inference Runner.

The resulting flow is:

```text
Producer
  |
  v
RabbitMQ
video_stream
  |
  v
Worker
  |
  +--> Redis
  |
  +--> PostgreSQL feature_log
  |
  v
RabbitMQ
inference_requests
  |
  v
Inference Runner
  |
  v
Sentinel API
  |
  v
ClearML Serving Canary
  |
  +--> Model v1
  |
  +--> Model v2
  |
  v
Prediction
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

The Worker does not invoke ClearML Serving directly.

Instead, after successful feature processing, it can publish an `InferenceRequestV1` message to:

```text
inference_requests
```

A dedicated service:

```text
sentinel.consumers.inference_runner
```

consumes the request and calls the existing Sentinel API:

```text
POST /predict/{image_id}
```

The API remains the single application entry point for model inference.

## Inference Request Contract

Automatic inference requests use the versioned contract:

```text
InferenceRequestV1
```

The request contains:

```text
schema_version
request_id
image_id
timestamp
```

The original ingestion event identifier is reused as:

```text
request_id
```

This allows the same logical operation to be correlated across:

```text
Ingestion Event
      |
      v
Inference Request
      |
      v
Sentinel API
      |
      v
Inference Event
      |
      v
inference_log
```

## Correlation and Idempotency

The Inference Runner sends the request identifier to the Sentinel API through:

```text
X-Inference-Request-ID
```

The API uses this identifier as the inference identifier when publishing the resulting inference event.

Therefore:

```text
request_id == inference_id
```

for automatic inference.

Manual API requests that do not provide the header continue to receive a newly generated UUID.

The PostgreSQL `inference_log` table uses:

```text
inference_id
```

as its primary key.

Persistence uses:

```sql
ON CONFLICT (inference_id) DO NOTHING
```

This prevents duplicate inference-event persistence when the same logical request is delivered more than once.

This idempotency guarantee applies to database persistence.

It does not guarantee that model computation itself will occur only once if a request is retried after an uncertain network failure.

## Retry Strategy

Temporary failures must not immediately discard an automatic inference request.

Sentinel therefore uses a dedicated RabbitMQ retry queue:

```text
inference_requests.retry
```

The retry delay is:

```text
5 seconds
```

The retry queue uses RabbitMQ message TTL and dead-letter routing to return messages to:

```text
inference_requests
```

after the delay expires.

Each retry carries:

```text
x-sentinel-retry-count
```

The maximum number of retry attempts is:

```text
3
```

The behavior is:

```text
Inference Request
      |
      v
Inference Runner
      |
      +--> 2xx
      |      |
      |      v
      |     ACK
      |
      +--> 408 / 429 / 5xx / Network Error
      |      |
      |      v
      |   Retry Queue
      |      |
      |   wait 5 sec
      |      |
      |      v
      | inference_requests
      |
      +--> Retry limit exceeded
      |      |
      |      v
      |     DLQ
      |
      +--> Permanent 4xx
             |
             v
            DLQ
```

Retryable failures include:

* HTTP 408.
* HTTP 429.
* HTTP 5xx responses.
* HTTP connection failures.
* HTTP timeouts.

Permanent client errors are not retried.

## Dead-Letter Queue

Requests that cannot be processed successfully are routed through the RabbitMQ dead-letter exchange:

```text
sentinel.dlx
```

and stored in:

```text
inference_requests.dlq
```

This prevents permanently failing requests from entering an infinite retry loop.

The DLQ also provides a location for later inspection and operational recovery.

## Feature Flag

Automatic inference is controlled through:

```text
AUTO_INFERENCE_ENABLED
```

The default Helm value is:

```text
false
```

This provides a safe rollout mechanism.

Development currently overrides the value:

```text
sentinel-dev
AUTO_INFERENCE_ENABLED=true
```

Production continues to inherit:

```text
AUTO_INFERENCE_ENABLED=false
```

until automatic inference is separately validated and approved for production.

This allows the Inference Runner to be deployed and observed before automatic request production is enabled.

## Separation of Responsibilities

The architecture maintains clear service boundaries.

### Worker

Responsible for:

* Consuming ingestion events.
* Processing images.
* Writing online features to Redis.
* Writing durable feature history to PostgreSQL.
* Optionally creating an inference request.

The Worker does not execute model inference.

### Inference Runner

Responsible for:

* Consuming `InferenceRequestV1`.
* Calling the Sentinel API.
* Applying retry policy.
* Routing permanently failed requests to the DLQ.

The Runner does not access ClearML Serving directly.

### Sentinel API

Responsible for:

* Fetching online features.
* Calling ClearML Serving.
* Returning predictions.
* Publishing inference events.

### Inference Logger

Responsible for:

* Consuming inference events.
* Persisting inference history to PostgreSQL.

## Worker Delivery Trade-Off

The ingestion path is intentionally prioritized over automatic inference.

The Worker acknowledges successful ingestion independently of the later inference request.

Publishing the inference request is therefore a best-effort secondary operation.

This prevents RabbitMQ or inference-system problems from blocking the primary ingestion pipeline.

The trade-off is that a process failure between successful ingestion and inference-request publication could leave an image without an automatic inference request.

A transactional outbox could be introduced later if stronger delivery guarantees are required.

## Alternatives Considered

### Perform Inference Inside the Worker

Rejected.

The Worker would become responsible for both ingestion and inference:

```text
Worker
  |
  +--> Feature Processing
  |
  +--> Model Serving
```

This would couple CPU-oriented ingestion scaling with inference scaling.

Failures or latency in ClearML Serving could also directly reduce ingestion throughput.

### Call ClearML Serving Directly from the Inference Runner

Rejected.

This would create two separate model-serving clients:

```text
Sentinel API --> ClearML
Inference Runner --> ClearML
```

Inference behavior, request formatting, canary routing integration, metrics, tracing, and inference-event publishing would need to be duplicated.

The Runner therefore reuses the existing Sentinel API.

### Immediately Requeue Failed Messages

Rejected.

Immediate requeueing can create a hot retry loop:

```text
Fail
 |
 v
Requeue
 |
 v
Fail
 |
 v
Requeue
```

This can consume CPU and RabbitMQ resources while the downstream dependency is unavailable.

A delayed retry queue introduces controlled backoff.

### Retry Forever

Rejected.

A permanently invalid or failing request could remain in the system indefinitely.

Sentinel therefore limits retries and moves exhausted requests to a DLQ.

### Use the RabbitMQ Delayed Message Plugin

Not selected for the current implementation.

The required delay can be achieved using standard RabbitMQ TTL and dead-letter capabilities without introducing an additional broker plugin.

### Use a Transactional Outbox

Deferred.

A transactional outbox could provide stronger guarantees between feature persistence and inference-request creation.

The current implementation prioritizes architectural simplicity and ingestion availability.

An outbox may be introduced if Sentinel later requires guaranteed creation of an inference request for every persisted image.

## Consequences

### Positive

* Ingestion and inference scale independently.
* The Worker remains independent from ClearML Serving.
* Existing Sentinel API inference logic is reused.
* Automatic inference is asynchronous from ingestion.
* Temporary API failures receive bounded retries.
* Permanent failures are isolated in a DLQ.
* Request identifiers provide end-to-end correlation.
* Database persistence remains idempotent.
* Development rollout can be controlled using a feature flag.
* The UI receives prediction, confidence, and model-version information automatically.

### Negative

* Another long-running component must be deployed and monitored.
* RabbitMQ now carries an additional inference-request workflow.
* Automatic inference is eventually consistent.
* A short delay can exist between ingestion and prediction visibility.
* Database idempotency does not prevent repeated model computation.
* Best-effort request publication creates a small delivery gap after successful ingestion.
* Retry queues and DLQs require operational monitoring.

## Validation

The decision is considered successfully implemented when:

1. The Inference Runner is deployed and healthy.
2. The Runner has an active consumer on `inference_requests`.
3. The retry queue `inference_requests.retry` exists.
4. The dead-letter queue `inference_requests.dlq` exists.
5. The Runner can reach `sentinel-api:8000`.
6. Automatic inference can be enabled independently per environment.
7. A processed image automatically creates an inference request.
8. The Runner invokes the Sentinel API without manual intervention.
9. ClearML Canary selects the serving model.
10. The resulting inference event is persisted through the Inference Logger.
11. `inference_log` contains the inference ID, image ID, model version, prediction, confidence, and timestamp.
12. Retryable failures are delayed and retried a bounded number of times.
13. Exhausted requests are routed to the DLQ.
14. Duplicate inference-event persistence does not create duplicate database rows.
15. The monitoring UI displays automatic inference results.

Development validation completed successfully on 2026-09-08.

Before automatic inference was enabled:

```text
inference_log rows = 7
```

After running the Producer:

```text
inference_log rows = 61
```

This produced 54 new automatically generated inference records.

The persisted results included predictions from both:

```text
Model v1
Model v2
```

confirming that the automatic inference path continued to use ClearML Canary routing.

The Sentinel monitoring UI displayed:

```text
Inference Model
Prediction
Confidence
```

for the automatically processed images.
