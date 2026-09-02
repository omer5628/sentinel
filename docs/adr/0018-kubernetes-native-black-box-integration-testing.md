# ADR-0018: Kubernetes-Native Black Box Integration Testing

* **Status:** Accepted
* **Date:** 2026-09-02
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel requires a black-box integration test after container image build and before deployment.

The integration test must verify that the built Sentinel API image can:

* Start successfully.
* Become healthy.
* Process a real image through the Sentinel ingestion path.
* Return a valid prediction response.

The generic implementation for this task suggests Docker Python SDK or Testcontainers.

However, the Sentinel Jenkins pipeline runs on ephemeral Kubernetes agents. Container images are built using rootless BuildKit, and the Jenkins agents do not have access to a Docker daemon.

Adding access to the Minikube Docker socket would give the CI workload broad control over the node container runtime.

Running Docker-in-Docker would introduce another privileged container runtime and additional operational complexity.

Sentinel also has a distributed inference path:

```text id="h1p7qk"
Image
  |
  v
RabbitMQ
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
Triton
```

The API does not accept image bytes directly. It performs inference for an `image_id` whose processed feature already exists in Redis.

## Decision

Project Sentinel will implement the CI black-box integration test using the **Kubernetes Python Client** instead of Docker Python SDK or Testcontainers.

The test will run from the Jenkins Kubernetes agent and will:

1. Create a temporary Pod from the exact Sentinel API image produced by the current Jenkins build.
2. Configure the Pod to use the Sentinel development Redis instance and the ClearML Triton serving endpoint.
3. Wait until the API `/health` endpoint returns HTTP 200.
4. Generate a valid 28x28 grayscale PNG image.
5. Publish the image as a valid Sentinel message to RabbitMQ.
6. Wait for the existing ingestion Worker to process the message and write the resulting feature to Redis.
7. Call `POST /predict/{image_id}` on the temporary API Pod.
8. Validate that the response is successful JSON with the expected prediction fields.
9. Delete the temporary Pod regardless of whether the test succeeds or fails.

The Jenkins pipeline will pass the exact immutable image tag produced by the current build to the integration test.

The integration test is a deployment gate. A failed integration test prevents deployment to the development and production environments.

## Why Kubernetes-Native Testing

Jenkins already executes inside Kubernetes.

Using the Kubernetes API allows the pipeline to test the built image in the same runtime environment used for deployment without introducing another container runtime.

The temporary test Pod is isolated from the Jenkins controller and uses namespace-scoped RBAC.

This preserves the existing least-privilege security model.

## Alternatives Considered

### Docker Python SDK

Rejected for the Jenkins integration test because the Kubernetes agent does not have a Docker daemon.

Providing the host Docker socket to Jenkins would grant excessive control over the node container runtime.

### Testcontainers

Testcontainers provides convenient container lifecycle management, but it still requires access to a compatible container runtime.

Using it would therefore require Docker socket access or Docker-in-Docker in the current Jenkins architecture.

### Docker-in-Docker

Rejected because it adds another container daemon and commonly requires elevated privileges.

The additional security and operational complexity is unnecessary when the pipeline already runs in Kubernetes.

### Testing the Existing Development API

Rejected because it would test the previously deployed image instead of the image produced by the current Jenkins build.

The integration gate must validate the exact artifact that may be deployed.

## Consequences

### Positive

* Tests the exact API image created by the current build.
* No Docker socket is exposed to Jenkins.
* No privileged Docker-in-Docker service is required.
* Exercises the real RabbitMQ → Worker → Redis → API → Triton path.
* Runs in the same container runtime environment as deployment.
* Failed tests block deployment automatically.
* Temporary test resources are removed after execution.

### Negative

* The integration test depends on the development infrastructure being available.
* The test requires Kubernetes API access.
* The test is more complex than a single standalone Docker container test.
* Failures in RabbitMQ, Redis, the Worker, or Triton can cause the integration gate to fail even when the API image itself is healthy.

## Validation

The decision is considered successfully implemented when:

1. Jenkins builds a new Sentinel API image.
2. The integration test starts a temporary Pod using that exact image tag.
3. `/health` returns HTTP 200.
4. A valid PNG image is published to RabbitMQ.
5. The Worker processes the image.
6. `POST /predict/{image_id}` returns HTTP 200.
7. The response contains valid prediction JSON.
8. The temporary test Pod is removed.
9. A failed integration test prevents the `Deploy Dev` stage from running.
