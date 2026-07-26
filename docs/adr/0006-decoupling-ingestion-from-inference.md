# ADR-0006: Decoupling Ingestion from Inference

- **Status:** Accepted
- **Date:** 2026-07-26
- **Decision Owners:** Project Sentinel Engineering Team
- **Related ADRs:** ADR-0005 — Dual-Write Strategy for the Feature Store

## Context

Project Sentinel has two workloads with different performance and scaling characteristics:

- **Ingestion:** Receives image events from RabbitMQ, validates and decodes messages, applies shared preprocessing, and writes features to Redis and PostgreSQL.
- **Inference:** Receives synchronous user requests, reads a prepared feature from Redis, runs the model, and returns a prediction.

It would be possible to run model inference directly inside the ingestion worker. That design would combine queue consumption, preprocessing, storage, and prediction in one process. However, ingestion and inference do not have the same resource requirements or service-level objectives.

Ingestion is primarily asynchronous and CPU/I/O oriented. Real-time inference is latency-sensitive and may require independent CPU, GPU, or memory scaling. Coupling them would make each service compete for resources and would prevent independent deployment and scaling.

## Decision

Project Sentinel will separate ingestion from inference.

The architecture will use:

- RabbitMQ to decouple the Producer from the ingestion worker.
- An ingestion Worker for validation, preprocessing, and dual-write storage.
- Redis as the handoff point between the asynchronous write path and synchronous read path.
- FastAPI as the real-time Serving API.
- A model loaded once by the Serving API for prediction.

The Worker must not perform the user-facing prediction. Its responsibility ends after producing and storing the feature representation.

The Serving API must not consume RabbitMQ messages and must not perform ingestion responsibilities. It reads only prepared features from Redis.

## Why Not Predict Inside the Worker

Prediction is kept outside the Worker so the two workloads can scale independently:

- More Workers can be added when image ingestion or preprocessing becomes CPU-bound.
- More Serving instances or GPU-backed inference processes can be added when prediction traffic increases.
- A temporary queue backlog does not directly block synchronous API requests for features already available in Redis.
- Model deployment and rollback can occur without changing the ingestion pipeline.
- Failures in the prediction service do not stop data capture and archival.

This separation follows the project principle:

> Async ingest, sync serve.

## Online and Offline Workload Boundary

The FastAPI service is intended for low-latency, individual prediction requests. It is not the correct interface for large offline workloads.

For bulk prediction, `batch_predict.py` loads the model directly, preprocesses images locally, performs inference in batches of 32, and writes results directly to PostgreSQL without HTTP.

## Performance Evidence

A local benchmark processed 1,000 MNIST images using both approaches.

| Execution path | Total measured time | Throughput | Average latency |
|---|---:|---:|---:|
| Direct batch inference, batch size 32 | 0.32 seconds | 3,131.10 images/second | Not measured per HTTP request |
| Sequential FastAPI requests | 1.81 seconds | 551.37 requests/second | 1.81 ms/request |

Using the internal timings, direct batch inference was approximately **5.66 times faster** than sending 1,000 sequential requests through the Serving API.

The measurements are evidence of the architectural distinction, but they are not perfectly equivalent. The batch timer measured the main processing section and excluded some startup work such as model loading and image discovery, while the API benchmark used features already available in Redis. Future benchmark reports should also record end-to-end wall-clock time for both paths.

The conclusion remains that HTTP serving should be reserved for synchronous online requests, while high-volume offline work should load the model directly and use batched inference.

## Alternatives Considered

### Prediction Inside the Ingestion Worker

Rejected because ingestion throughput and prediction capacity could not be scaled independently. A slow or memory-intensive model would reduce queue-consumption throughput and increase the RabbitMQ backlog.

### One Monolithic Service

Rejected because deployment, failure handling, resource allocation, testing, and scaling would all be coupled. A failure in any part of the process could stop both data ingestion and prediction.

### Calling FastAPI for Batch Jobs

Rejected because repeated HTTP routing, serialization, Redis access, response generation, and single-item inference add overhead and can consume capacity needed by real-time users.

### Reading PostgreSQL Directly from the API

Rejected because the offline store is optimized for durable history rather than predictable online latency. PostgreSQL outages or latency spikes must not break the online path.

## Consequences

### Positive

- Ingestion and inference scale independently.
- Different CPU, GPU, and memory profiles can be assigned to each service.
- Model deployment is separated from queue processing.
- Batch workloads avoid unnecessary HTTP overhead.
- Real-time serving capacity is protected from large offline jobs.
- Failures are isolated to smaller parts of the system.

### Negative

- More services and deployment definitions must be maintained.
- Redis becomes a required contract boundary between the Worker and API.
- Feature shape, dtype, serialization, and model expectations must remain synchronized.
- Observability must correlate events across RabbitMQ, Worker, Redis, API, and PostgreSQL.

## Validation

The decision is correctly implemented when:

1. The Producer publishes to RabbitMQ without calling the API.
2. The Worker preprocesses and stores features without performing the user-facing prediction.
3. FastAPI reads `feat:{image_id}` from Redis and returns a prediction.
4. FastAPI returns `404 Image not processed yet` when the Redis key is missing.
5. The API does not query PostgreSQL for inference.
6. `batch_predict.py` loads the model directly and processes images in batches of 32 without HTTP.
7. Ingestion and API processes can be started, stopped, and scaled independently.