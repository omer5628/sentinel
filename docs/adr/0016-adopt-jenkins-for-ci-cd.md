# ADR-0016: Adopt Jenkins for CI/CD

* **Status:** Accepted
* **Date:** 2026-08-25
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel previously relied on manual Kubernetes deployment commands.

Phase 5 requires a governed CI/CD process where deployments are executed through a controlled pipeline rather than manually from an engineer's terminal.

The platform needs to support:

* Automated testing.
* License compliance validation.
* Container image builds.
* Container vulnerability scanning.
* Image publishing.
* Helm-based Kubernetes deployments.
* Automatic deployment to development.
* Manual approval before production deployment.
* Kubernetes-based build agents.
* Pipeline definitions stored in Git.
* Namespace-scoped deployment permissions.

## Decision

Project Sentinel will use **Jenkins** as the CI/CD orchestrator.

Jenkins is deployed inside Kubernetes using the official Jenkins Helm chart.

The Jenkins controller runs in the `jenkins` namespace and uses persistent storage for Jenkins configuration and job data.

Pipeline workloads run on dynamic Kubernetes agents instead of directly on the Jenkins controller.

Two Kubernetes ServiceAccounts are used:

* `jenkins-controller` for operating the Jenkins controller and scheduling agents.
* `jenkins-deployer` for deployment operations executed by pipeline agents.

The `jenkins-deployer` ServiceAccount follows the principle of least privilege.

It receives namespace-scoped deployment permissions in:

* `sentinel-dev`
* `sentinel-prod`

The pipeline automatically deploys successful builds to `sentinel-dev`.

Deployment to `sentinel-prod` requires a Jenkins human approval gate before the production Helm deployment is executed.

The production flow is:

```text
Test
  ↓
Compliance
  ↓
Build Images
  ↓
Security Scan
  ↓
Push Images
  ↓
Deploy Dev
  ↓
Human Approval
  ↓
Deploy Prod
```

Jenkins does not receive permission to create Kubernetes namespaces or cluster-wide RBAC resources.

Creation of target namespaces and other cluster-scoped platform resources remains a platform bootstrap responsibility.

Cluster-scoped Promtail RBAC also remains a platform bootstrap responsibility and is not managed by the Jenkins deployment account.

The Jenkins deployment RBAC configuration is managed declaratively through:

```text
infra/jenkins/values.yaml
```

using the Jenkins Helm chart `extraObjects`.

The previous standalone:

```text
infra/jenkins/deployer-rbac.yaml
```

is no longer used, avoiding multiple sources of truth for Jenkins deployment permissions.

## Production Promotion

Development deployments are automatic after all pipeline quality and security gates succeed.

Production deployment requires explicit human approval using a Jenkins Declarative Pipeline `input` step.

The approval gate protects deployment intent rather than replacing automated validation.

A build cannot reach the production deployment stage unless:

1. Tests succeed.
2. License compliance succeeds.
3. Container images build successfully.
4. Trivy security scanning succeeds.
5. Images are pushed successfully.
6. Development deployment succeeds.
7. A human explicitly approves production promotion.

Production runtime secrets must already exist in the `sentinel-prod` namespace before deployment.

Jenkins consumes those Kubernetes Secrets through the Sentinel Helm chart but does not embed secret values in the `Jenkinsfile`.

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
* Jenkins runs dynamic build agents in Kubernetes.
* Development deployments are automated.
* Production deployments require explicit human approval.
* Helm provides consistent deployment packaging between environments.
* Deployment permissions are isolated by Kubernetes namespace.
* Jenkins does not require cluster-admin permissions.
* Pipeline configuration is version controlled through the `Jenkinsfile`.
* Jenkins RBAC has a single declarative source of truth.

### Negative

* Jenkins requires operational maintenance.
* Plugins and Jenkins versions must be managed.
* Persistent storage is required for controller state.
* Jenkins introduces additional infrastructure and security responsibilities.
* Target namespaces and production secrets require separate bootstrap management.
* Human approval can delay production deployment.

## Security

The Jenkins deployment ServiceAccount is restricted to namespace-level permissions.

It can manage the Kubernetes resources required for Sentinel deployment inside:

```text
sentinel-dev
sentinel-prod
```

It is explicitly not allowed to create cluster-wide RBAC resources such as `ClusterRole`.

It is also not granted responsibility for creating deployment namespaces.

This follows the principle of least privilege and limits the blast radius of a compromised Jenkins agent.

Production secrets are stored as Kubernetes Secrets in the production namespace and are not stored directly in the `Jenkinsfile`.

## Validation

Verify that the Jenkins controller is running:

```bash
kubectl get pods -n jenkins
```

Verify that the Jenkins PVC is bound:

```bash
kubectl get pvc -n jenkins
```

Verify development deployment permissions:

```bash
kubectl auth can-i create deployments.apps \
  --namespace sentinel-dev \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
yes
```

Verify production deployment permissions:

```bash
kubectl auth can-i create deployments.apps \
  --namespace sentinel-prod \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
yes
```

Verify production Secret access:

```bash
kubectl auth can-i get secrets \
  --namespace sentinel-prod \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
yes
```

Verify that cluster-wide RBAC remains denied:

```bash
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io \
  --as=system:serviceaccount:jenkins:jenkins-deployer
```

Expected result:

```text
no
```

Finally, execute the Jenkins pipeline and verify that it pauses at:

```text
Promote to Prod?
```

Production deployment must not begin until a human explicitly approves the promotion.
