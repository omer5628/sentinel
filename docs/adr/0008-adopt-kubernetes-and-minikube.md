# ADR-008: Adoption of Kubernetes and Minikube

## Status

Accepted

## Date

2026-07-27

## Context

Sentinel currently runs as a distributed containerized system using Docker
Compose.

The system contains several independent components:

- RabbitMQ for asynchronous messaging.
- Redis for the online Feature Store.
- PostgreSQL for the offline Feature Store.
- An ingestion Worker.
- A FastAPI serving service.
- A Streamlit labeling application.
- Producer and batch-processing workloads.

Docker Compose is suitable for running and developing this stack on a single
machine. However, Sentinel now needs to simulate a production environment and
demonstrate operational behavior that goes beyond starting several containers
together.

The platform must support:

- Declarative workload management.
- Automatic recreation of failed workloads.
- Independent scaling of application services.
- Stable networking and service discovery.
- Persistent storage for stateful services.
- Separation between stateless and stateful workloads.
- Controlled application rollouts.
- External and internal service exposure.
- Configuration and secret injection.
- Resource requests, limits, scheduling, and workload isolation.
- A migration path toward CI/CD, observability, governance, and continuous
  training.

A local cluster implementation is also required so these capabilities can be
developed and tested on a single Linux workstation without requiring a public
cloud account.

## Decision

Sentinel will adopt Kubernetes as its container orchestration platform.

For local development and the Phase 3 learning environment, Sentinel will use
Minikube with the Docker driver.

All Sentinel Kubernetes resources will initially be written as raw YAML
manifests.

Helm and visual management platforms such as Rancher will not be used during
this phase. This ensures that the project first learns the native Kubernetes
resources and their relationships before introducing higher-level automation.

## Selection Rationale
### Why Kubernetes

Kubernetes was selected because Sentinel requires production-oriented
orchestration capabilities that Docker Compose and simpler orchestrators do not
provide in the same depth.

The project needs native support for:

- Deployments and StatefulSets.
- Automatic workload recovery.
- PersistentVolumeClaims and StorageClasses.
- Service discovery through Services and CoreDNS.
- ConfigMaps and Secrets.
- Readiness and liveness probes.
- Scheduling rules, affinity, taints, and tolerations.
- Integration with later project tools such as Prometheus, Helm, OPA
  Gatekeeper, Chaos Mesh, and Kubernetes-native CI/CD.

Docker Swarm is simpler, but it does not provide the same Kubernetes-native
ecosystem or the specific resources required by later Sentinel phases.

Nomad is a strong general-purpose orchestrator, but adopting it would require
redesigning the project around different networking, storage, scheduling, and
deployment concepts.

Therefore, Kubernetes was chosen because it best matches Sentinel's technical
requirements and the architecture planned for the later phases.

### Why Minikube

Minikube was selected as the local Kubernetes environment because it provides a
real Kubernetes cluster while remaining simple to run on a single Linux
workstation.

It supports the capabilities required by Sentinel, including:

- StatefulSets.
- Persistent storage.
- Services and NodePort.
- CoreDNS.
- Ingress addons.
- Local Docker integration.
- Easy cluster creation, deletion, and recovery.

Kind is especially suitable for CI and disposable automated test clusters, but
Minikube is more convenient for interactive local development and learning.

K3s is lightweight and suitable for edge devices, homelabs, and persistent
small servers, but it includes more bundled defaults and is less focused on the
disposable desktop learning workflow used in this phase.

Therefore, Minikube was chosen because it provides the best balance of
simplicity, Kubernetes feature coverage, local development convenience, and
compatibility with the existing Docker-based Linux environment.

## Consequences

### Positive

- Sentinel gains a production-oriented orchestration environment.
- Failed workloads can be recreated automatically.
- Stateful services can use persistent storage.
- Networking and service discovery become Kubernetes-native.
- The project gains a foundation for later observability, CI/CD, security,
  and governance phases.

### Negative

- Kubernetes introduces significantly more configuration than Docker Compose.
- Raw YAML manifests are verbose and may contain duplication.
- Networking, storage, and debugging become more complex.
- Minikube is a local development environment and does not provide true
  production high availability.

## Conclusion

Kubernetes was selected because Sentinel requires production-oriented
orchestration, stateful workload management, persistent storage, service
discovery, recovery, scheduling, and compatibility with the Kubernetes-native
tools used in later phases.

Minikube was selected because it provides these Kubernetes capabilities in a
simple, local, disposable environment that integrates well with Docker on
Linux.

In summary:

- Kubernetes was chosen for its orchestration capabilities and ecosystem.
- Minikube was chosen as the most convenient local environment for learning
  and developing those capabilities.