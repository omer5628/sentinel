# ADR-0026: Adopt Jenkins for Alert-Driven Retraining Orchestration

* **Status:** Accepted
* **Date:** 2026-10-20
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel needs a governed workflow that can react to detected model drift without automatically deploying an unverified model.

The workflow coordinates different concerns:

* Receiving a relevant drift alert.
* Enforcing the operational retraining emergency brake.
* Fetching eligible human-labeled examples and maintaining a reproducible cutoff.
* Validating data and training a candidate model.
* Comparing current and candidate models through Gatekeeper.
* Promoting an accepted candidate through controlled Canary and Git workflows.
* Recording a checkpoint only after the required preceding steps succeed.
* Preserving logs, artifacts, and an audit trail.

Sentinel already uses Jenkins for its application CI/CD, Helm packaging, Kubernetes deployments, image scanning, and approval gates.

The retraining workflow must fit that existing governance model without introducing a second orchestration control plane unnecessarily.

## Decision

Sentinel will use **Jenkins Pipeline** as the orchestrator for alert-driven model retraining.

The dedicated job is:

```text
sentinel-retraining
```

Prometheus and AlertManager are responsible for detecting and routing drift alerts. Jenkins is responsible for the governed execution of the retraining workflow.

Individual computation stages run as short-lived Kubernetes Jobs, rendered from the project's Helm chart.

Jenkins coordinates the jobs and retains pipeline logs and artifacts; it does not replace the underlying training, experiment tracking, or serving systems.

## Architecture

The intended orchestration path is:

```text
Sentinel Serving API
         |
         v
Prometheus Drift Rule
         |
         v
AlertManager
         |
         v
Jenkins: sentinel-retraining
         |
         v
Emergency Brake
         |
     +---+---+
     |       |
   false    true
     |       |
     v       v
   ABORT   Fetch / Validate Data
                     |
                     v
              Train Candidate
                     |
                     v
                 Gatekeeper
                     |
               +-----+-----+
               |           |
             REJECT      ACCEPT
               |           |
               v           v
             Stop     Governed Canary
                           |
                           v
                   Git Reference Update
                           |
                           v
                     Checkpoint
```

No alert may bypass the emergency brake.

No training success may bypass Gatekeeper or the required promotion policy.

## Responsibility Boundaries

### Prometheus and AlertManager

Prometheus evaluates configurable drift metrics and alert rules.

AlertManager routes a firing alert to the dedicated Jenkins retraining endpoint.

Neither system receives authorization to promote a model directly.

### Jenkins

Jenkins is responsible for:

* Pipeline ordering, stage conditions, timeouts, and failure handling.
* Invocation and observation of Kubernetes Jobs.
* Controlled use of Git, registry, and deployment credentials.
* Compliance with CI/CD and promotion gates.
* Logging, artifacts, and actionable failure information.

### Kubernetes and Helm

Kubernetes executes containerized retraining work as Jobs.

Helm templates describe the Jobs and their required configuration and secrets.

Deployment-related mutations remain within the governed Jenkins workflow, rather than ad hoc local `kubectl apply` operations.

### ClearML

ClearML stores experiment and model artifacts and supplies immutable model references.

Jenkins invokes work that uses ClearML; Jenkins is not the model registry.

### Hydra and Adapters

Hydra/configuration controls model-, dataset-, and environment-specific behavior.

Shared pipeline logic should stay generic; implementation-specific preprocessing, evaluation, and dataset contracts belong to replaceable adapters/configuration.

## Emergency Brake and Security

The operational control is:

```text
RETRAINING_ENABLED
```

For ordinary alert-driven retraining, `false` means Jenkins must stop before any Fetch, Train, Canary, Git update, or checkpoint stage.

Alert-triggering permissions belong to the dedicated Jenkins service identity documented in **ADR-0024**.

Authorization to invoke a pipeline is distinct from permission to perform retraining.

Secrets must be supplied through approved credential and Kubernetes Secret mechanisms, not committed to source control.

Production deployment and approvals remain subject to the existing governance requirements.

## Immutable Execution and Data Consistency

Jenkins should use explicit, immutable container image tags and model artifact references.

Retraining must use:

* The original/base training dataset.
* Accumulated eligible human-labeled examples available at a defined cutoff.
* Exclusion of discarded labels.
* Exclusion of Golden Set holdout examples from training.

The minimum new-row threshold decides whether retraining may start; it is not an instruction to train only on the latest rows.

The retraining cutoff and successful checkpoint provide the boundaries needed to avoid accidental reprocessing.

The checkpoint must **not** advance when validation, training, Gatekeeper, Canary, or required Git synchronization fails.

## Promotion and Reconciliation

Promotion is a governed operation, not a direct side effect of an alert.

The current Jenkins implementation coordinates:

```text
Gatekeeper ACCEPT
        |
        v
Canary Promotion
        |
        v
Update Canary Reference in Git
        |
        v
Update Retraining Checkpoint
```

The Git update checks the expected previous reference, verifies branch freshness, performs a commit and push, and confirms the remote SHA.

If the Git push fails after Canary routing changes, Jenkins reports a critical reconciliation condition and does not advance the checkpoint.

This reduces silent inconsistency but does **not** provide an atomic transaction between Serving and Git.

A successful Git push also does not, by itself, prove that a separate deployment pipeline picked up and deployed that reference.

Production deployment requires its own independently verified controls.

## Isolated End-to-End Tests

Sentinel uses a separate logical database and credentials for destructive/synthetic retraining tests:

```text
Database: sentinel_e2e
User: sentinel_e2e_user
```

A dedicated Protection Test mode may execute the required E2E stages even when normal retraining is disabled, but must remain explicitly isolated and must not reach regular Canary, Git, or checkpoint stages.

This test bypass is **not** a way to enable normal automated retraining.

Test fixtures must be identified precisely and removed when the test ends.

This design avoids corrupting normal feedback-loop data or Production resources.

## Alternatives Considered

### Apache Airflow

Considered but not selected for the current phase.

Airflow provides scheduling, DAG-based orchestration, retries, and visibility for recurring data pipelines.

However, Sentinel's current retraining control path is largely alert-driven and closely coupled to governed container builds, security checks, Kubernetes deployment operations, and approval workflows already present in Jenkins.

Introducing Airflow now would duplicate orchestration infrastructure, credentials, operational monitoring, and pipeline governance.

Airflow may be reconsidered if scheduled, multi-dependency, data-heavy workflows become dominant.

### Dagster

Considered but not selected for the current phase.

Dagster offers asset-aware orchestration, lineage concepts, software-defined assets, and strong data-pipeline development workflows.

These capabilities could be valuable if Sentinel evolves into a broader data platform with many datasets and materializations.

For the current alert-driven retraining flow, they do not justify replacing the already governed Jenkins execution path.

Dagster may be reconsidered when asset orchestration and lineage become first-class requirements.

### Trigger Retraining Directly From AlertManager

Rejected.

AlertManager should deliver alerts, not execute privileged training and deployment steps.

A direct trigger without a governed pipeline would weaken authorization, auditability, stage ordering, and recovery behavior.

### Run Everything Inside a Single Jenkins Agent

Rejected.

Long-running model training should run as an isolated Kubernetes Job with explicit resources and an immutable image.

Jenkins should coordinate work, not act as the shared execution environment for all model computation.

### Adopt a Second Orchestrator Alongside Jenkins Immediately

Rejected.

Two orchestration systems introduce duplicated schedules, secrets, monitoring, and failure handling before a demonstrated need exists.

## Consequences

### Positive

* Reuses Sentinel's existing CI/CD, Helm, Git, and security governance.
* Supports alert-driven retraining with a clearly auditable stage sequence.
* Keeps expensive computation inside Kubernetes Jobs.
* Separates drift detection, retraining authorization, model evaluation, and promotion.
* Preserves traceability through Jenkins logs and ClearML artifacts.
* Avoids deploying and operating an additional orchestration service.

### Negative

* Jenkins Pipeline is less naturally suited to complex dataset/asset dependency graphs than dedicated data orchestrators.
* A large Jenkinsfile can become difficult to maintain and may face Groovy compilation/size limits.
* Pipeline-as-code needs careful structure, reusable scripts, and tests to prevent control-flow regressions.
* Jenkins remains a critical operational dependency for retraining.
* Failure after Canary promotion but before Git synchronization requires explicit reconciliation.

## Validation

The decision is considered implemented when:

1. A dedicated `sentinel-retraining` Jenkins job is defined in source control.
2. Drift alerts can trigger that job through the governed AlertManager integration.
3. `RETRAINING_ENABLED=false` prevents ordinary retraining from proceeding.
4. Fetch, validation, training, and Gatekeeper run as Kubernetes Jobs under Jenkins orchestration.
5. Job image tags, model references, and retraining cutoff values are explicit and traceable.
6. Gatekeeper rejection prevents Canary promotion and checkpoint progression.
7. An isolated Protection Test cannot update normal Canary, Git, or checkpoint state.
8. An accepted candidate is subject to governed Canary, Git, and checkpoint controls.
9. Git synchronization errors are surfaced, and the checkpoint is not advanced.
10. An end-to-end deployment claim is made only after the downstream deployment pipeline has actually been verified.

### Recorded Phase 6 Evidence

**Protection Test — `sentinel-retraining` Build #49**

* Jenkins orchestrated seed, fetch, validation, training, and Gatekeeper against the isolated E2E database.
* The corrupted candidate scored 0.69 against the current model's 0.96 and was rejected.
* Canary, Git update, and checkpoint did not run.
* The 1,000 synthetic corrupted records were cleaned up.

**Drift Gun — `sentinel-retraining` Build #50**

* 1,000 prediction requests succeeded for the same image and predicted class.
* Prometheus raised `SentinelPredictionDistributionDrift` with `alertstate=firing` and `class_name=1`.
* AlertManager triggered `sentinel-retraining` Build #50.
* Jenkins reported `RETRAINING_ENABLED=false` and terminated with the intended `ABORTED` status before retraining.

**GitOps Status**

* The Preflight and Git-update safety checks were reviewed in `Jenkinsfile.retraining`.
* Earlier isolated Canary and Git workflow checks were conducted.
* A complete automatic Git-push-to-deployment round trip has **not** been demonstrated as part of these final Phase 6 checks.
* Therefore, production GitOps deployment must not be represented as fully end-to-end verified.

## Decision Summary

Sentinel adopts Jenkins as the orchestrator for alert-driven retraining because it integrates with the existing security, CI/CD, Kubernetes, and promotion governance.

```text
Prometheus / AlertManager
           |
           v
 Jenkins Retraining Pipeline
           |
           v
 Kubernetes Training Jobs
           |
           v
   Gatekeeper Decision
           |
           v
 Governed Promotion Path
```

Airflow or Dagster can be reconsidered when complex data scheduling, dependency graphs, or asset lineage create a concrete need for a specialized data orchestrator.

The retraining pipeline remains **fail-closed**, with operational enablement, performance evaluation, and deployment governance enforced as separate controls.
