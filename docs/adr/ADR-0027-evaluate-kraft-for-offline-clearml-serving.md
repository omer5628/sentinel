# ADR-0027: Evaluate Kafka KRaft for Offline ClearML Serving

* **Status:** Proposed — pending compatibility and integration tests
* **Date:** 2026-10-28
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Sentinel uses RabbitMQ for its main ingestion flow. Separately, the bundled ClearML Serving Helm chart (`external/helm-charts/clearml-serving`, version 1.6.2) enables Kafka for serving-related messaging and statistics. Its bundled Kafka subchart is Bitnami Kafka chart 21.4.0 (originally aligned to Kafka 3.4), with ZooKeeper enabled by default.

The target air-gapped environment does not provide the required ZooKeeper image. The internal image inventory includes `bitnamilegacy/kafka:3.9.0` as a candidate Kafka image, but a compatible image pull and runtime test have not yet been performed in that environment.

## Options Considered

1. Keep ZooKeeper mode and replace both images with compatible Bitnami images: lower configuration change, but ZooKeeper image remains unavailable.
2. Replace ZooKeeper with a Confluent container: not a drop-in replacement for the bundled Bitnami ZooKeeper subchart due to different container conventions and configuration.
3. Run Kafka 3.9 using KRaft mode: removes the ZooKeeper runtime dependency, but requires validating compatibility with the older Kafka Helm chart and its startup scripts.
4. Replace Kafka deployment with a separate modern chart: potentially cleaner long-term, but adds more migration work and may alter service naming/contracts.

## Proposed Decision

Evaluate option 3 in a **new, disposable Kubernetes namespace** using a temporary Kafka subchart override. Keep the main Sentinel ingestion architecture unchanged. Do not migrate or reuse existing ZooKeeper-backed Kafka PVCs in place.

Target values:

```yaml
kafka:
  enabled: true
  image:
    repository: bitnamilegacy/kafka
    tag: "3.9.0"
  replicaCount: 1
  kraft:
    enabled: true
    processRoles: broker,controller
  zookeeper:
    enabled: false
```

The parent Helm chart uses nested `kafka` values; the Kafka subchart takes the same settings without the outer key.

## Acceptance Criteria

- Helm chart renders a Kafka workload using the exact candidate tag, and no ZooKeeper Pod is rendered.
- Fresh Kafka broker starts in KRaft mode without a ZooKeeper connection.
- Controller quorum initializes; a topic can be created; produce/consume round trip passes.
- ClearML Serving inference and statistics components connect using their configured Kafka service URL.
- No unexpected image pulls are required by the air-gapped environment.
- No existing PVCs or deployed production services are modified.

## Risks and Mitigations

- **Chart/image version mismatch:** chart 21.4.0 targets older Kafka; verify boot logs and runtime rather than relying on `helm template` alone. Upgrade chart or use a separate compatible Kafka deployment if necessary.
- **Data migration:** ZooKeeper-to-KRaft is not a simple image swap; test using fresh storage. Plan any real migration separately.
- **Supply-chain risk:** Bitnami Legacy images are no longer maintained. Treat this as an interim compatibility measure, scan and mirror images internally, and plan a maintained replacement.
- **Registry access:** Docker Hub and the internal JFrog registry are not interchangeable. An image that works locally is not proof that the air-gapped image is available or trusted.
- **Cluster identity:** set a unique, stable KRaft cluster ID for each real deployment and preserve it with the cluster's persisted data.

## Decision Status

This ADR will be marked **Accepted** only after the runtime and ClearML Serving integration checks pass. Otherwise, revert the override and select a compatible standalone Kafka deployment or updated Helm chart.
