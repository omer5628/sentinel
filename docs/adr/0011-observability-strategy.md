# ADR-011: Observability Strategy

## Status

Accepted

## Context

Sentinel needs a reliable observability system for collecting metrics from the inference API.

Two common approaches are:

- Pull-based metrics collection, where the monitoring system periodically scrapes metrics from the application.
- Push-based metrics collection, where the application actively sends metrics to the monitoring system.

Prometheus uses the pull model, while systems such as Graphite commonly rely on pushed metrics.

For Sentinel, observability must not become a dependency that can affect the availability of the inference API.

## Decision

Use Prometheus with a pull-based metrics collection model.

The Sentinel API exposes metrics through:

```text
/metrics