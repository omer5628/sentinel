# ADR-0023: Adopt Configurable Drift Detection and Alert-Driven Retraining

* **Status:** Accepted
* **Date:** 2026-09-09
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel is entering the continuous-training feedback-loop phase.

The Serving API now exposes prediction-distribution metrics through Prometheus:

```text
model_predictions_total{class_name="0"}
model_predictions_total{class_name="1"}
...
```

Prometheus can use these metrics to observe how prediction behavior changes over time.

For example, a model whose normal prediction distribution is approximately:

```text
Class 0 -> 10%
Class 1 -> 10%
...
Class 9 -> 10%
```

may later produce:

```text
Class 7 -> 80%
```

Such a change can indicate prediction-distribution drift and should be investigated.

However, Sentinel is intended to remain a generic MLOps platform.

Different models can have:

* Different output classes.
* Different baseline distributions.
* Different traffic volumes.
* Different acceptable drift levels.
* Different observation windows.
* Different drift-detection strategies.

A drift rule that is hard-coded for MNIST or for a specific class distribution would prevent Sentinel from being reused safely with other models.

The platform therefore needs a configurable drift-detection mechanism.

The system must also separate drift detection from retraining execution.

Detection should produce an operational alert.

Alert routing should then trigger the continuous-training workflow.

The retraining workflow must remain protected by the existing emergency brake:

```text
RETRAINING_ENABLED
```

## Decision

Sentinel will adopt configurable drift detection with Prometheus-based alerting and AlertManager-based routing.

The feedback path will be:

```text
Sentinel API
      |
      v
Prediction Metrics
      |
      v
Prometheus
      |
      v
Configurable Drift Rule
      |
      v
AlertManager
      |
      v
Jenkins Retraining Pipeline
      |
      v
Emergency Brake
      |
      v
Retraining Workflow
```

Prometheus is responsible for evaluating operational drift rules.

AlertManager is responsible for routing active drift alerts.

Jenkins is responsible for executing the retraining workflow.

Jenkins does not determine whether drift exists.

## Configurable Drift Policy

Drift-detection behavior must not be hard-coded inside the Sentinel API.

The Helm configuration will expose drift-related settings.

The initial prediction-distribution strategy will support configuration such as:

```text
enabled
observation window
minimum prediction volume
distribution threshold
alert duration
```

For example:

```text
window = 15m
minimum predictions = 100
maximum class share = 40%
alert duration = 10m
```

These values are examples only.

They are not Sentinel platform defaults that apply universally to every model.

A user deploying a model through Sentinel is responsible for selecting drift thresholds appropriate for that model and workload.

## Initial Detection Strategy

The first drift strategy will monitor prediction-distribution concentration.

Prometheus can calculate the prediction share for each class using the prediction counter.

Conceptually:

```text
prediction rate for class
-------------------------
prediction rate for all classes
```

produces the current prediction distribution.

A configured alert can fire when a class exceeds the allowed distribution threshold for a configured duration.

The rule must also require sufficient traffic so that a small number of predictions does not trigger a false drift alert.

For example:

```text
Only 2 predictions
Class 7 = 100%
```

must not automatically be treated the same as:

```text
10,000 predictions
Class 7 = 80%
```

## Generic Platform Requirement

Sentinel must not contain model-specific drift assumptions such as:

```text
Class 7 must be approximately 10%
```

or:

```text
MNIST classes must be uniformly distributed
```

Such assumptions belong to the deployed model's drift policy.

The platform provides the mechanism.

The model owner provides the policy.

This separation allows Sentinel to support models with:

* Binary classification.
* Multi-class classification.
* Highly imbalanced classes.
* Non-uniform production traffic.
* Future regression or other model types.

## Drift Types

The initial metric detects prediction or output distribution drift.

This means Sentinel observes changes in:

```text
P(prediction)
```

This is useful as an operational signal but does not prove that the underlying model is incorrect.

Prediction-distribution changes can occur because:

* Input traffic changed.
* User behavior changed.
* Data distribution changed.
* The model behavior changed.

Therefore, the initial alert is considered a drift signal rather than proof of model degradation.

Future drift detectors may additionally evaluate:

```text
Data Drift
P(X)
```

and:

```text
Concept Drift
P(Y|X)
```

when appropriate ground-truth data becomes available.

## Advanced Drift Detection

Sentinel reserves:

```text
src/sentinel/drift/detector.py
```

for more advanced drift-detection logic.

Future strategies may compare a production distribution against a stored baseline using statistical methods such as:

```text
Population Stability Index
Jensen-Shannon divergence
Kolmogorov-Smirnov tests
```

The same operational flow will remain:

```text
Drift Detector
      |
      v
Metric or Alert
      |
      v
Prometheus
      |
      v
AlertManager
      |
      v
Jenkins
```

This allows the detection algorithm to evolve without redesigning the retraining workflow.

## AlertManager Responsibility

AlertManager does not detect drift.

Its responsibility is to receive alerts that Prometheus has already evaluated and route them to the appropriate destination.

The initial destination will later be the Sentinel Jenkins retraining job.

Conceptually:

```text
Prometheus
  |
  | DriftDetected
  v
AlertManager
  |
  | webhook
  v
sentinel-retraining
```

AlertManager also provides a future location for alert grouping, deduplication, silencing, and routing policies.

## Retraining Safety

A drift alert must never automatically guarantee that retraining will execute.

The Jenkins retraining pipeline must first read:

```text
RETRAINING_ENABLED
```

from:

```text
sentinel-ops-flags
```

The workflow is therefore:

```text
Drift Alert
    |
    v
Jenkins
    |
    v
RETRAINING_ENABLED?
    |
    +--> false -> ABORT
    |
    +--> true  -> Continue
```

This preserves an operational kill switch between automated detection and automated model changes.

## Alternatives Considered

### Hard-Code Drift Thresholds in the API

Rejected.

The Serving API should expose telemetry but should not contain model-specific operational policy.

Hard-coded thresholds would make Sentinel dependent on the current MNIST workload.

### Let Jenkins Detect Drift

Rejected.

Jenkins is a workflow-execution system, not a metrics-monitoring system.

Polling production metrics from Jenkins would mix monitoring and pipeline responsibilities.

### Let AlertManager Detect Drift

Rejected.

AlertManager routes and manages alerts.

Prometheus evaluates the alert expressions.

### Trigger Retraining Directly from Prometheus

Rejected.

AlertManager provides a dedicated routing layer between monitoring and downstream automation.

It also allows future deduplication, silencing, routing, and additional notification destinations.

### Use Only a Fixed Prediction Percentage Threshold

Not selected as the final platform design.

A configurable percentage threshold is sufficient for the initial implementation, but Sentinel must allow more advanced drift strategies later.

## Consequences

### Positive

* Drift policy remains independent from the Sentinel API.
* Sentinel remains reusable across different model types.
* Model owners can select thresholds appropriate to their workloads.
* Prometheus remains responsible for monitoring.
* AlertManager provides a dedicated alert-routing layer.
* Jenkins remains responsible for workflow execution.
* Retraining remains protected by an emergency brake.
* More advanced statistical detectors can be added later without redesigning the feedback loop.

### Negative

* Users must understand their model's expected production behavior.
* Incorrect thresholds can create false positives or missed drift.
* Prediction-distribution drift alone cannot prove model degradation.
* AlertManager introduces another operational component.
* Advanced drift detection may require additional baseline storage and computation.

## Validation

The decision is considered successfully implemented when:

1. Prediction distribution is exposed through Prometheus metrics.
2. Drift thresholds are configurable rather than hard-coded in application code.
3. The drift observation window is configurable.
4. A minimum traffic requirement prevents alerts on insufficient samples.
5. Prometheus can evaluate the configured drift rule.
6. A drift condition changes the Prometheus alert state to firing.
7. AlertManager receives the firing alert.
8. AlertManager can route the alert to the continuous-training workflow.
9. Jenkins checks `RETRAINING_ENABLED` before retraining.
10. Disabling retraining prevents a drift alert from starting training.
11. Drift policy can be changed without modifying the Sentinel API source code.
