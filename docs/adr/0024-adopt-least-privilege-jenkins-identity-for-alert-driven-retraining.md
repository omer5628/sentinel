# ADR-0024: Adopt Least-Privilege Jenkins Identity for Alert-Driven Retraining

* **Status:** Accepted
* **Date:** 2026-09-09
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel is implementing an automated feedback loop for model retraining.

The current flow is:

```text
Sentinel API
    |
    v
Prometheus
    |
    v
Drift Detection Rule
    |
    v
AlertManager
    |
    v
Jenkins Retraining Pipeline
```

Prometheus is responsible for evaluating the configured drift policy.

AlertManager receives firing alerts and will route relevant drift alerts to Jenkins.

Jenkins already contains a dedicated retraining pipeline:

```text
sentinel-retraining
```

The retraining pipeline is protected by the Sentinel emergency brake:

```text
RETRAINING_ENABLED
```

However, Jenkins currently uses an authorization model where authenticated users receive broad permissions.

Using an administrator API token for AlertManager would therefore violate the principle of least privilege.

A compromised AlertManager credential could potentially provide access to unrelated Jenkins jobs, configuration, credentials, or administrative operations.

The AlertManager integration therefore requires a dedicated Jenkins identity with narrowly scoped permissions.

## Decision

Sentinel will use a dedicated Jenkins service identity for AlertManager-triggered retraining.

The identity will be restricted to the minimum permissions required to trigger the retraining pipeline.

The Jenkins Role Strategy Plugin will be used to implement fine-grained authorization.

The service identity will be assigned an item-specific role for:

```text
sentinel-retraining
```

The intended permissions are limited to:

```text
Job/Read
Job/Build
```

Additional permissions must not be granted unless a concrete operational requirement is identified.

The service identity must not receive Jenkins administrator permissions.

## Service Identity

The dedicated Jenkins identity will be named:

```text
sentinel-alertmanager
```

Its purpose is limited to triggering the Sentinel retraining pipeline.

The identity must not be reused by:

* Application pipelines.
* Deployment pipelines.
* Human users.
* Kubernetes workloads unrelated to drift-driven retraining.
* Production administration.

This separation allows the credential to be revoked or rotated independently.

## Credential Management

The Jenkins API token for the service identity is considered a secret.

It must not be stored in:

```text
Git
Helm values committed to Git
ConfigMaps
Jenkinsfiles
AlertManager ConfigMaps
container images
application source code
```

The credential will be stored in a Kubernetes Secret.

AlertManager will receive the credential through a mounted Secret or another Kubernetes-native secret reference.

The secret value must not appear in rendered Helm manifests committed to source control.

The credential should be independently rotatable without changing application code.

## Authorization Model

The Jenkins authorization model will separate administrative access from automated retraining access.

Conceptually:

```text
Administrator
    |
    +--> Jenkins administration
    +--> Pipeline management
    +--> All jobs

sentinel-alertmanager
    |
    +--> Read sentinel-retraining
    +--> Trigger sentinel-retraining
```

The service identity must not have permission to:

```text
configure jobs
delete jobs
manage plugins
manage Jenkins
read Jenkins credentials
modify users
trigger unrelated pipelines
deploy directly to Kubernetes
```

## Jenkins Role Strategy

The Role Strategy Plugin is selected because Sentinel requires permissions scoped to a specific Jenkins item.

A global authenticated-user permission model is too broad for machine-to-machine triggering.

The target design uses:

```text
Global role
    Minimal Jenkins access required for authentication

Item role
    Pattern matching sentinel-retraining
    Job/Read
    Job/Build
```

The exact Jenkins Configuration as Code representation will be maintained through the Jenkins Helm configuration.

Manual authorization changes through the Jenkins UI are not considered the source of truth.

## Jenkins Configuration Management

Jenkins is deployed through Helm.

Its project-managed configuration is located at:

```text
infra/jenkins/values.yaml
```

Security configuration and required plugins must therefore be introduced through the governed Jenkins Helm configuration.

Manual plugin installation through the Jenkins UI is rejected.

This keeps the Jenkins security model reproducible and auditable.

## AlertManager Integration

AlertManager will send an authenticated HTTP request to Jenkins when the configured drift alert reaches the firing state.

The target pipeline is:

```text
sentinel-retraining
```

The intended request flow is:

```text
Prometheus
    |
    | drift alert firing
    v
AlertManager
    |
    | authenticated request
    v
Jenkins
    |
    | sentinel-alertmanager identity
    v
sentinel-retraining
```

Jenkins authorization determines whether the identity may trigger the job.

AlertManager does not receive deployment permissions.

## Emergency Brake

Jenkins authorization and the Sentinel emergency brake solve different problems.

Authorization answers:

```text
Who is allowed to request retraining?
```

The emergency brake answers:

```text
Is automated retraining currently allowed?
```

Both controls are required.

The full flow is therefore:

```text
Drift detected
    |
    v
AlertManager
    |
    v
Authenticated Jenkins request
    |
    v
Authorization check
    |
    v
sentinel-retraining
    |
    v
RETRAINING_ENABLED
    |
    +--> false -> abort
    |
    +--> true  -> continue
```

The system remains fail-closed.

If retraining is disabled, a valid AlertManager request must not bypass the emergency brake.

## Security Properties

This design provides several security properties.

### Least Privilege

AlertManager receives only the Jenkins permissions required for retraining.

### Credential Isolation

The AlertManager credential is separate from administrator and pipeline credentials.

### Revocation

The service identity or API token can be revoked without changing administrator credentials.

### Auditability

Jenkins can identify retraining requests as originating from:

```text
sentinel-alertmanager
```

rather than from a shared administrator account.

### Defense in Depth

A successful Jenkins authentication is still subject to:

```text
Jenkins authorization
+
Sentinel emergency brake
```

No single mechanism controls the entire retraining decision.

## Alternatives Considered

### Use Jenkins Administrator Credentials

Rejected.

This would provide AlertManager with far more permissions than required.

A leaked or compromised token could affect the entire Jenkins installation.

### Keep FullControlOnceLoggedIn Authorization

Rejected for automated service identities.

It does not provide sufficiently narrow permissions for machine-to-machine integration.

### Install Generic Webhook Trigger Plugin Only

Rejected as the primary security solution.

A webhook trigger mechanism does not replace authorization.

The core requirement is a dedicated identity with minimum permissions.

### Install Build Token Root Plugin

Rejected.

A build token alone does not provide the desired identity-based authorization model and introduces another plugin specifically for triggering jobs.

### Use matrix-auth

Considered.

Matrix Authorization can provide fine-grained permissions.

However, Sentinel needs a clear item-specific role dedicated to the retraining pipeline.

Role Strategy provides a more explicit model for assigning job-specific roles to a service identity.

### Use Kubernetes ServiceAccount Authentication Directly

Rejected.

Jenkins authentication and Kubernetes RBAC are independent security domains.

The `jenkins-deployer` Kubernetes ServiceAccount controls what Jenkins agents may do inside Kubernetes.

It must not be treated as a Jenkins user credential.

## Consequences

### Positive

* AlertManager does not require administrator credentials.
* Retraining permissions are isolated from deployment permissions.
* Jenkins access follows least privilege.
* Credentials can be independently rotated.
* Security configuration remains governed through Helm.
* Automated retraining remains protected by the emergency brake.

### Negative

* Jenkins requires an additional authorization plugin.
* Jenkins security configuration becomes more complex.
* A dedicated service identity and API token must be managed.
* Credential rotation procedures are required.

## Validation

The implementation will be considered successful when all of the following are verified:

1. `role-strategy` is installed through the Jenkins Helm configuration.
2. `sentinel-alertmanager` exists as a dedicated Jenkins identity.
3. The identity can read `sentinel-retraining`.
4. The identity can trigger `sentinel-retraining`.
5. The identity cannot trigger `sentinel-pipeline`.
6. The identity does not have Jenkins administrative permissions.
7. Its API token is stored in a Kubernetes Secret.
8. AlertManager can trigger `sentinel-retraining` through the internal Jenkins Service.
9. `RETRAINING_ENABLED=false` still causes the retraining pipeline to abort.
10. `RETRAINING_ENABLED=true` allows the pipeline to continue.

## Decision Summary

Sentinel adopts a dedicated least-privilege Jenkins identity for AlertManager-triggered retraining.

The final control path is:

```text
Prometheus Drift Detection
        |
        v
AlertManager
        |
        v
Dedicated Jenkins Identity
        |
        v
Role-Based Authorization
        |
        v
sentinel-retraining
        |
        v
Emergency Brake
        |
        v
Retraining Workflow
```

The platform therefore separates:

```text
Detection
Routing
Authentication
Authorization
Operational Enablement
Retraining
```

into independent controls.

This design reduces credential exposure while preserving the governed, automated feedback loop required by Project Sentinel.
