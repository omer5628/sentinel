# ADR-0015: Adopt Helm for Kubernetes Packaging

* **Status:** Accepted
* **Date:** 2026-08-25
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel was originally deployed to Kubernetes using raw YAML manifests.

This approach worked during the Kubernetes learning phase, but introduced duplicated and hardcoded configuration such as:

* Container image repositories and tags.
* Replica counts.
* CPU and memory resources.
* Persistent volume sizes.
* Service ports.
* Environment-specific configuration.
* Kubernetes namespaces.

Managing separate YAML manifests for development and production would require modifying multiple files for every deployment.

Phase 5 introduces an automated and governed deployment pipeline, so the Kubernetes configuration needs to be reusable and parameterized.

## Decision

Project Sentinel will use **Helm** to package the Kubernetes resources.

The Sentinel Helm chart is located at:

```text
charts/sentinel/
```

The chart uses:

* `Chart.yaml` for chart metadata.
* `values.yaml` for default configuration.
* `values-prod.yaml` for production overrides.
* `templates/` for Kubernetes resource templates.
* `.Release.Namespace` for namespace-independent deployments.

Environment-specific values such as replica counts, resources, image tags, ports, and storage sizes are defined in Helm values rather than duplicated across Kubernetes manifests.

Secrets are not stored directly in Helm values. The chart references existing Kubernetes Secrets.

## Alternatives Considered

### Raw Kubernetes YAML

Raw YAML is simple and transparent, but requires duplicated manifests and manual changes between environments.

This becomes difficult to maintain and error-prone as the number of services and deployment environments grows.

### Kustomize

Kustomize provides overlays and patches without introducing template syntax.

It is a strong option when the main requirement is modifying existing Kubernetes YAML across environments.

However, Project Sentinel requires reusable parameterization of values such as:

* Image tags.
* Replica counts.
* Resource limits.
* Storage sizes.
* Service configuration.

Helm provides a more suitable packaging and templating model for this deployment workflow.

## Consequences

### Positive

* One Kubernetes package can represent multiple environments.
* Production-specific configuration is separated from defaults.
* Image versions can be changed by CI/CD without editing manifests.
* Kubernetes namespaces are no longer hardcoded.
* The chart can later be deployed automatically by Jenkins.
* Deployment configuration is version-controlled with application code.

### Negative

* Developers must understand Helm templating syntax.
* Rendered Kubernetes YAML is less immediately visible than raw manifests.
* Incorrect Helm values can affect multiple generated resources.
* Helm introduces another tool into the deployment workflow.

## Validation

The chart must pass:

```bash
helm lint charts/sentinel
```

Both development and production configurations must render successfully using `helm template`.

Production rendering must not contain hardcoded `namespace: default` values or unresolved `.Values` / `.Release` expressions.
