# ADR-009: StatefulSets vs Deployments

## Status

Accepted

## Context

Sentinel runs PostgreSQL, Redis, and RabbitMQ inside Kubernetes.

These services are stateful infrastructure components. They require stable network identities and, for persistent services, stable storage across Pod restarts.

A standard Deployment creates interchangeable Pods with dynamically generated names. For example:

```text
redis-7d8f9c6f4b-x2k9m
```

When a Deployment Pod is replaced, its name and identity may change.

This behavior is suitable for stateless application components such as the Sentinel API and Worker, but it is not ideal for databases and message brokers.

The infrastructure services require stable DNS names such as:

```text
postgres-0.postgres-headless.default.svc.cluster.local
redis-0.redis-headless.default.svc.cluster.local
rabbitmq-0.rabbitmq-headless.default.svc.cluster.local
```

PostgreSQL also requires its persistent data volume to remain attached after the Pod is deleted and recreated.

## Decision

We will deploy PostgreSQL, Redis, and RabbitMQ using Kubernetes StatefulSets.

Each StatefulSet will use a Headless Service to provide stable network identities.

Persistent services will use PersistentVolumeClaims so their data survives Pod deletion and recreation.

The Sentinel API and Worker will continue to use Deployments because they are stateless application workloads and their Pods can be replaced without preserving identity or local storage.

## Reasons

### Stable Pod Identity

StatefulSets create Pods with predictable and stable names:

```text
postgres-0
redis-0
rabbitmq-0
```

These names remain consistent after Pod recreation.

### Stable Network Identity

Headless Services provide stable DNS records for each StatefulSet Pod.

For example:

```text
redis-0.redis-headless.default.svc.cluster.local
```

This allows Sentinel services to connect to infrastructure components using predictable addresses.

### Stable Storage

StatefulSets maintain a consistent relationship between a Pod and its PersistentVolumeClaim.

When `postgres-0` is deleted, Kubernetes recreates the Pod and reconnects it to the same persistent volume.

The Phase 3 Kill Test confirmed this behavior. The row count in the `feature_log` table remained unchanged after deleting and recreating `postgres-0`.

### Ordered Lifecycle

StatefulSets provide ordered Pod creation, deletion, and updates.

This behavior is useful for stateful systems where startup order and stable identities may be important.

## Alternatives Considered

### Kubernetes Deployment

A Deployment was considered for PostgreSQL, Redis, and RabbitMQ.

It was rejected because Deployment Pods are interchangeable and use dynamically generated names.

A Deployment does not provide the same stable relationship between a specific Pod identity and its storage.

This would make direct Pod DNS names unpredictable and could complicate persistent storage management.

### Running Infrastructure Outside Kubernetes

Running PostgreSQL, Redis, and RabbitMQ outside the cluster was also possible.

This was rejected for the local Phase 3 environment because the goal was to practice Kubernetes-native deployment, service discovery, persistent storage, and recovery behavior.

## Consequences

### Positive

- Stable Pod names.
- Stable DNS addresses.
- Persistent data survives Pod recreation.
- Clear separation between stateful infrastructure and stateless applications.
- Easier recovery and troubleshooting.

### Negative

- StatefulSets are more complex than Deployments.
- PersistentVolumeClaims must be managed carefully.
- Scaling stateful services requires more planning than scaling stateless Pods.
- Deleting a StatefulSet does not automatically mean its PersistentVolumeClaims should be deleted.

## Verification

The following Phase 3 checks passed:

1. PostgreSQL Kill Test:
   - More than 100 records were written to `feature_log`.
   - `postgres-0` was deleted.
   - Kubernetes recreated the Pod automatically.
   - The record count remained unchanged.

2. Kubernetes DNS Test:
   - `redis-0.redis-headless.default.svc.cluster.local` resolved successfully.
   - The Sentinel Worker resolved both the full and shortened Redis DNS names.

3. StatefulSet Identity:
   - PostgreSQL, Redis, and RabbitMQ use predictable Pod names.
   - Each service is exposed using a Headless Service.

## Conclusion

StatefulSets are the correct workload type for Sentinel's PostgreSQL, Redis, and RabbitMQ services because they require stable network identities and persistent storage.

Deployments remain the correct workload type for the API and Worker because those services are stateless and interchangeable.