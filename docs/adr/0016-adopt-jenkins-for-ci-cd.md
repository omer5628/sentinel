# ADR-0016: Adopt Jenkins for CI/CD

* **Status:** Accepted
* **Date:** 2026-08-25
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel previously relied on manual Kubernetes deployment commands.

Phase 5 requires a governed CI/CD process where deployments are executed automatically through a pipeline rather than manually from an engineer's terminal.

The platform needs to support:

* Automated testing.
* Container image builds.
* Security and compliance gates.
* Helm-based Kubernetes deployments.
* Manual approval before production deployment.
* Kubernetes-based build agents.
* Pipeline definitions stored in Git.

## Decision

Project Sentinel will use **Jenkins** as the CI/CD orchestrator.

Jenkins is deployed inside Kubernetes using the official Jenkins Helm chart.

The Jenkins controller runs in the `jenkins` namespace and uses persistent storage for Jenkins configuration and job data.

Pipeline workloads will run on Kubernetes agents instead of directly on the Jenkins controller.

Two Kubernetes ServiceAccounts are used:

* `jenkins-controller` for operating the Jenkins controller and scheduling agents.
* `jenkins-deployer` for deployment operations executed by pipeline agents.

The `jenkins-deployer` ServiceAccount follows the principle of least privilege.

It can manage the Kubernetes resources required to deploy Sentinel in the `default` namespace, but it does not receive cluster-admin privileges.

Cluster-scoped Promtail RBAC remains a platform bootstrap responsibility and is not managed by the Jenkins deployment account.

## Alternatives Considered

### GitHub Actions

GitHub Actions integrates directly with GitHub and requires less infrastructure management.

However, Jenkins provides a self-hosted CI/CD environment that allows us to explicitly learn and manage agents, credentials, deployment permissions, approval gates, and pipeline infrastructure.

### GitLab CI

GitLab CI provides similar integrated CI/CD functionality when GitLab is used as the source control platform.

Project Sentinel currently uses GitHub, so adopting GitLab CI would introduce an unnecessary platform dependency.

### Tekton

Tekton provides Kubernetes-native CI/CD primitives.

It is powerful for cloud-native pipelines but introduces more Kubernetes-specific complexity than required for the current project.

## Consequences

### Positive

* CI/CD infrastructure is self-hosted and fully controlled.
* Jenkins can run dynamic build agents in Kubernetes.
* Deployments can be automated using Helm.
* Manual approval gates can be added before production.
* Deployment permissions can be restricted using Kubernetes RBAC.
* Pipeline configuration can be stored in Git using a `Jenkinsfile`.

### Negative

* Jenkins requires operational maintenance.
* Plugins and Jenkins versions must be managed.
* Persistent storage is required for controller state.
* Jenkins introduces additional infrastructure and security responsibilities.

## Security

The Jenkins deployment ServiceAccount is restricted to namespace-level permissions.

It is allowed to manage resources required for Sentinel deployment in the `default` namespace.

It is explicitly not allowed to create cluster-wide RBAC resources such as `ClusterRole`.

This follows the principle of least privilege.

## Validation

The Jenkins controller must be running successfully:

```bash
kubectl get pods -n jenkins
```

The Jenkins PVC must be bound:

```bash
kubectl get pvc -n jenkins
```

The deployment ServiceAccount must be able to deploy applications:

```bash
kubectl auth can-i create deployments.apps \
  --namespace default \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
yes
```

The deployment ServiceAccount must not have permission to create cluster-wide RBAC resources:

```bash
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
no
```
