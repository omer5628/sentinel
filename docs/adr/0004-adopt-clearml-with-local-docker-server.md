# 4. Adopt ClearML with a Local Docker-Based Server

## Status
Accepted

## Context
Project Sentinel requires reproducible experiment tracking, including training configuration, console output, Git metadata, metrics, and model artifacts.

Because the platform is designed as an on-premises MLOps system, experiment metadata and artifacts should remain under local control rather than depend on an external SaaS service.

We also need a repeatable and isolated way to run the ClearML infrastructure without manually installing and configuring each internal service.

## Decision
We will adopt `ClearML` as the experiment tracking platform for Project Sentinel.

ClearML Server will run locally using the official Docker Compose deployment. The Python SDK will connect to the local server through developer-specific credentials generated from the ClearML Web UI.

Default local endpoints:

- Web UI: `http://localhost:8080`
- API Server: `http://localhost:8008`
- File Server: `http://localhost:8081`

## Consequences
* **Experiment Tracking:** Training runs will record configuration, console output, Git metadata, metrics, and artifacts in ClearML.
* **Local Ownership:** Experiment data remains on the local machine and does not depend on an external SaaS platform.
* **Docker Requirement:** Developers must have Docker and Docker Compose installed and running.
* **Infrastructure Overhead:** The local ClearML stack consumes additional CPU, memory, and disk resources.
* **Reproducible Deployment:** Docker Compose provides a consistent way to start and stop the complete ClearML server stack.
* **Credential Management:** ClearML access and secret keys must remain outside Git and must never be committed to the repository.
* **Operational Responsibility:** The project team is responsible for local storage, backups, upgrades, and server availability.

## Alternatives Considered

### ClearML SaaS
Rejected for the primary environment because it sends experiment metadata and artifacts to an external service and does not match the on-premises goal of Project Sentinel.

### MLflow
Not selected because Project Sentinel requires more than experiment tracking and model registration.

ClearML provides built-in support for dataset versioning, remote execution, agents, job queues, and pipeline orchestration within the same platform. These capabilities align with the later phases of Project Sentinel, where training jobs will be scheduled, executed by workers, and connected to automated pipelines.

MLflow is strong in experiment tracking and model registry, but equivalent orchestration and worker-management capabilities would require additional external tools or integrations, increasing operational complexity and tool sprawl.

### Native Installation
Rejected because manually installing and maintaining every ClearML dependency would be slower, less isolated, and less reproducible than the official Docker Compose deployment.