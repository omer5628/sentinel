# ADR-0025: Adopt an Immutable Golden Set for Model Promotion Decisions

* **Status:** Accepted
* **Date:** 2026-10-20
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel implements a feedback loop in which newly labeled production data can trigger retraining.

Retraining data may include erroneous human labels, changed input distributions, or other data-quality problems.

A successful training run does not establish that the resulting model is better or safe to promote.

The promotion decision must therefore use an evaluation dataset that is **independent of the candidate's training and validation data**.

The required decision path is:

```text
Original/Base Dataset + Eligible Human-Labeled Data
                       |
                       v
                 Retraining Job
                       |
                       v
                 Candidate Model
                       |
                       v
          Golden Set Evaluation
                       |
                       v
                   Gatekeeper
                       |
             +---------+---------+
             |                   |
           REJECT              ACCEPT
             |                   |
             v                   v
        No Promotion      Controlled Promotion
```

Sentinel is intended to be a generic MLOps platform. The shared Gatekeeper must not assume a fixed set of labels, a particular model family, or the MNIST dataset.

## Decision

Sentinel will use a **versioned, immutable Golden Set** as the common evaluation reference for the current model and each candidate model.

The Golden Set is a holdout: its samples must be excluded from candidate training, including the original/base dataset portion used during retraining.

The same Golden Set version, preprocessing contract, evaluation metric, and evaluation procedure must be used for both models in a comparison.

The Gatekeeper will decide promotion using configurable policy rather than treating successful training as approval.

For the current deployment the policy is:

```text
gatekeeper.enabled = true
gatekeeper.evaluation.metric = accuracy
gatekeeper.evaluation.direction = maximize
gatekeeper.policy.require_improvement = true
gatekeeper.policy.max_regression = 0.0
```

These values describe the current policy, not mandatory defaults for every Sentinel deployment.

## Golden Set Contract

A Golden Set version must define:

* A stable, identifiable set of evaluation examples and ground-truth labels.
* A dataset/version reference that can be traced and reproduced.
* A preprocessing and model-output interpretation contract.
* The expected number of usable evaluation samples.
* A manifest or equivalent mechanism for excluding those samples from training.
* The selected evaluation metric and its optimization direction.

For the current MNIST adapter, the relevant configuration and artifacts are:

```text
data/golden_set.csv
data/golden_set_manifest.json

gatekeeper.golden_set.path
gatekeeper.golden_set.required_samples
gatekeeper.adapters.golden_set
gatekeeper.adapters.model
gatekeeper.adapters.holdout
gatekeeper.evaluation.metric
gatekeeper.evaluation.direction
gatekeeper.policy
```

The current configuration requires 100 Golden Set examples.

These paths and class definitions are specific to the current MNIST deployment. Other datasets must supply their own compatible adapters and configuration.

## Immutable Holdout

Golden Set examples must not influence:

* Training or fine-tuning.
* Hyperparameter selection based on repeated inspection of Golden Set results.
* Human-labeled data selection intended to improve performance on this particular set.
* Post hoc modification of thresholds to approve a rejected candidate.

Sentinel excludes the current Golden Set examples from the original training dataset through an adapter-configured holdout filter.

The original/base dataset and accumulated eligible human-labeled data are combined for retraining, but **the immutable holdout remains excluded**.

The minimum-new-labels threshold (currently 1,000) is a trigger for attempting retraining, not a replacement for the original/base training data.

Changing the Golden Set requires a deliberate, versioned change reviewed separately from an individual candidate's promotion decision.

## Generic Evaluation Adapters

The platform's shared Gatekeeper orchestrates evaluation and applies policy.

Dataset- and model-specific behavior belongs in configuration and replaceable adapters.

The current deployment uses:

```text
sentinel.adapters.mnist:MNISTGoldenSetAdapter
sentinel.adapters.torchscript_classifier:TorchScriptArgmaxModelAdapter
sentinel.adapters.mnist:exclude_training_holdout_rows
sentinel.adapters.clearml_model:ClearMLModelArtifactResolver
```

These are implementation choices for the current deployment, **not** requirements for future users of Sentinel.

Adapters must provide comparable scores and reject incompatible or invalid evaluation inputs.

## Promotion Policy

For each candidate the Gatekeeper will:

1. Resolve the explicitly identified current and candidate model artifacts.
2. Evaluate both models against the same immutable Golden Set version.
3. Report their scores, score delta, and the decision reason.
4. Enforce the configured metric direction, thresholds, and improvement policy.
5. Return `ACCEPT` or `REJECT` as an auditable outcome.

Under the current policy, equal scores do **not** constitute improvement.

For a metric that must be maximized:

```text
candidate_score > current_score  -> eligible for ACCEPT
candidate_score <= current_score -> REJECT
```

Eligibility for `ACCEPT` also depends on all additional configured gates passing. This comparison is not a substitute for data validation, security gates, or operational approval.

The Gatekeeper must fail closed if the Golden Set, model artifact, adapter contract, or required score is unavailable or invalid.

A technical failure must not be reported as a successful proof of performance regression.

## Separation of Responsibilities

The feedback loop separates different decisions:

```text
Data Validation
    |  Is the retraining data acceptable?
    v
Training
    |  Can a candidate model be produced?
    v
Golden Set Gatekeeper
    |  Does the candidate satisfy promotion policy?
    v
Promotion Workflow
    |  May the approved candidate be deployed?
    v
Serving
```

Drift detection is a reason to investigate or retrain; drift alone does not authorize model promotion.

An accepted candidate may still be subject to Canary and governed deployment checks.

## Alternatives Considered

### Evaluate Only on the Training Dataset

Rejected.

Training accuracy is not an independent estimate of generalization and can hide overfitting or label corruption.

### Use Each Retraining Run's Random Validation Split

Rejected as the sole promotion criterion.

Different validation splits make comparisons across model versions inconsistent.

A per-run split may still support training diagnostics, but is not the common promotion reference.

### Automatically Rebuild the Golden Set After Every Retraining Run

Rejected.

Changing the evaluation reference alongside the candidate makes scores difficult to compare and creates a risk of feedback contamination.

### Hard-Code MNIST Evaluation Into the Gatekeeper

Rejected.

It would couple the shared MLOps platform to a single dataset and model-output format.

Sentinel instead uses configurable adapters.

### Require Improvement Without a Common Holdout

Rejected.

A strict comparison rule cannot provide a reliable decision if the two scores come from different evaluation data.

## Consequences

### Positive

* Current and candidate models are evaluated on comparable data.
* Known holdout examples are excluded from training.
* Regressions and lack of improvement can block automatic promotion.
* The decision is auditable through model references, scores, and reasons.
* Shared platform behavior remains configurable and adapter-driven.

### Negative

* The Golden Set must be curated, versioned, and protected from leakage.
* A small or stale holdout may not represent real-world performance.
* Repeated optimization against a fixed holdout can overfit the evaluation process.
* Maintaining adapters and evaluation contracts adds implementation work.
* Golden Set performance alone cannot guarantee safety for every input distribution.

## Validation

The decision is considered implemented when all of the following are verified:

1. A fixed Golden Set and its manifest are available and versioned.
2. Golden Set samples are excluded from the base training data.
3. Both model references use the same evaluation configuration.
4. Gatekeeper scores, action, reason, and model references are logged.
5. A candidate with equal scores is rejected under `require_improvement=true`.
6. A measurably worse candidate is rejected without promotion.
7. Missing or invalid evaluation inputs fail closed.
8. A rejected candidate does not update Canary routing, Git references, or the retraining checkpoint.

### Recorded Phase 6 Evidence

The isolated Protection Test in `sentinel-retraining` Build **#49** used a deliberately corrupted labeled dataset and an `e2e_fast` candidate training profile:

```text
Base samples: 1000
Human-labeled samples: 1000
Combined samples: 2000
Epoch 1/1

current_score=0.960000
candidate_score=0.690000
gatekeeper_action=REJECT
```

This demonstrated a **27-percentage-point regression**, a Gatekeeper rejection, and no Canary, Git, or checkpoint progression.

The E2E fixtures were removed after the test. The normal retraining emergency brake remained disabled (`RETRAINING_ENABLED=false`).

This evidence validates the specific corrupted-label scenario; it does not prove detection of every possible corruption or guarantee the representativeness of the Golden Set.

## Decision Summary

Sentinel adopts a versioned, immutable Golden Set as the independent reference for model-promotion decisions.

```text
Versioned Holdout + Configurable Adapters
                    |
                    v
       Comparative Gatekeeper
                    |
           ACCEPT / REJECT
                    |
                    v
       Governed Promotion Path
```

A candidate model is promoted only after independent evaluation and all required policy gates; successful retraining alone is insufficient.
