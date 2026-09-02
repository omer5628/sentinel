# ADR-0019: Immutable Artifacts Strategy

* **Status:** Accepted
* **Date:** 2026-09-02
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel builds container images for the API and Worker as part of the Jenkins CI/CD pipeline.

Each Jenkins build produces a specific version of the application that passes automated tests, license compliance checks, security scanning, and integration testing before deployment.

Using a mutable image tag such as:

```text
omer5628/sentinel-api:latest
```

would make it difficult to determine which exact Jenkins build produced the image currently running in an environment.

The meaning of `latest` changes whenever a new image is pushed. As a result, the same Kubernetes configuration could point to different image contents at different times.

This creates problems for:

* Traceability.
* Incident investigation.
* Rollbacks.
* Auditing.
* Reproducibility.

Production deployments must be linked to a specific CI/CD execution.

## Decision

Sentinel container images will be tagged using the Jenkins `${BUILD_NUMBER}`.

For example, Jenkins Build 20 produces:

```text
omer5628/sentinel-api:20
omer5628/sentinel-worker:20
```

The Jenkins pipeline then deploys these exact tags through Helm:

```text
--set-string api.image.tag=${BUILD_NUMBER}
--set-string worker.image.tag=${BUILD_NUMBER}
```

Each build number is treated as an immutable artifact identifier.

An existing build tag must not be reused for different image contents.

The `latest` tag will not be used for Sentinel deployments.

## Rationale

Using `${BUILD_NUMBER}` creates a direct relationship between:

```text
Git Commit
    |
    v
Jenkins Build
    |
    v
Container Image
    |
    v
Kubernetes Deployment
```

If Production is running:

```text
omer5628/sentinel-api:20
```

we can determine that the image was created by Jenkins Build 20 and inspect the exact source commit, test results, security scan, integration test, and deployment logs associated with that build.

This significantly improves traceability compared with a moving tag such as `latest`.

## Alternatives Considered

### `latest`

Rejected.

`latest` is a mutable moving target. The same tag can reference different image contents over time.

This makes troubleshooting and rollback ambiguous.

### Git Commit SHA

A Git commit SHA would also provide strong traceability.

However, Sentinel already uses Jenkins as the controlled artifact creation pipeline, and `${BUILD_NUMBER}` provides a simple direct mapping between the container image and the Jenkins execution that created and validated it.

A commit SHA may be added as additional image metadata in the future.

### Container Image Digest

Deploying directly by image digest provides the strongest technical immutability because the digest identifies the exact image content.

This is a valid future improvement.

For the current Sentinel environment, unique Jenkins build tags provide the required traceability while keeping Helm values and operational workflows simple.

## Consequences

### Positive

* Every deployed Sentinel image can be traced back to a specific Jenkins build.
* Production incidents can be correlated with the exact CI/CD execution that created the deployed artifact.
* Rollback targets are explicit. For example:

```text
sentinel-api:20
sentinel-api:19
sentinel-api:18
```

rather than different historical versions all being represented by `sentinel-api:latest`.

* Dev and Production deployments can also be compared using their image build numbers.

### Negative

* Container registries will accumulate multiple image versions over time.
* A future image retention policy will therefore be required to remove old artifacts while preserving versions needed for rollback and auditing.
* The build-number convention also depends on the pipeline never overwriting an existing `${BUILD_NUMBER}` tag.

## Verification

The Sentinel Jenkins pipeline currently builds and pushes images using the current Jenkins build number.

For example, Jenkins Build 20 produced and deployed:

```text
omer5628/sentinel-api:20
omer5628/sentinel-worker:20
```

The same build number was passed to the Helm deployment for the Production environment.

This establishes the required traceability chain:

```text
Jenkins Build 20
        |
        v
sentinel-api:20
sentinel-worker:20
        |
        v
sentinel-prod
```

## Decision Summary

Sentinel uses Jenkins `${BUILD_NUMBER}` tags instead of `latest` because production artifacts must be traceable to the exact CI/CD execution that created them.

`latest` is ambiguous and mutable.

Build-specific tags provide a clear and auditable deployment history and allow reliable identification and rollback of deployed versions.
