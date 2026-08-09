# ADR-012: Log Aggregation Strategy

- **Status:** Accepted
- **Date:** 2026-08-09
- **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel requires centralized log aggregation for Kubernetes workloads such as the API, Worker, Redis, RabbitMQ, and supporting observability services.

The logging solution must support:

- Kubernetes-native log collection.
- Structured JSON logs.
- Filtering by metadata such as application, namespace, pod, and container.
- Integration with Grafana.
- Correlation between logs and OpenTelemetry traces through `trace_id`.
- Persistent log storage.
- Low operational overhead for the current project scale.

Two main approaches were considered:

1. **Loki + Promtail + Grafana**
2. **ELK Stack (Elasticsearch + Logstash + Kibana)**

## Decision

Adopt **Loki** as the centralized log storage system, with **Promtail** as the Kubernetes log collector and **Grafana** as the query and visualization interface.

The resulting logging flow is:

```text
Kubernetes Containers
        |
        v
     Promtail
        |
        v
       Loki
        |
        v
     Grafana
```

Application logs are emitted as structured JSON and include OpenTelemetry `trace_id` and `span_id` values where a valid trace context exists.

## Why Loki Instead of ELK

### Loki

Loki primarily indexes labels and metadata rather than building a full-text index over every log line.

Examples of labels used in Sentinel:

```text
app="sentinel-api"
namespace="default"
pod="sentinel-api-..."
container="api"
```

This allows queries such as:

```logql
{app="sentinel-api"} |= "error"
```

Loki first selects the relevant log streams using indexed labels and then searches the matching log content.

### ELK

The ELK stack provides significantly more powerful full-text search and general-purpose log analytics.

However, Elasticsearch maintains much heavier indexes, which generally increases:

- Memory usage.
- CPU usage.
- Disk usage.
- Operational complexity.

For Sentinel's current requirements, that additional capability does not justify the extra infrastructure cost and maintenance burden.

## Rationale

Loki was selected for the following reasons:

### 1. Native Grafana Integration

Sentinel already uses Grafana for Prometheus metrics.

Using Loki allows metrics and logs to be investigated from the same interface instead of introducing Kibana as another operational UI.

### 2. Prometheus-Like Label Model

Loki uses labels similarly to Prometheus.

Prometheus example:

```promql
inference_requests_total{model="v1"}
```

Loki example:

```logql
{app="sentinel-api"}
```

This creates a consistent observability model across metrics and logs.

### 3. Kubernetes Integration

Promtail runs as a Kubernetes DaemonSet and reads container logs from the node.

Sentinel enriches log streams with Kubernetes metadata including:

- `app`
- `namespace`
- `pod`
- `container`

This makes it possible to isolate logs from individual services without relying on filename searches.

### 4. Lower Operational Overhead

Sentinel does not currently require advanced enterprise-scale full-text search or SIEM functionality.

Loki provides the required logging features with less infrastructure overhead than operating Elasticsearch, Logstash, and Kibana.

### 5. Trace-to-Log Correlation

Sentinel structured logs contain OpenTelemetry trace identifiers.

Example:

```json
{
  "level": "ERROR",
  "service": "sentinel-api",
  "message": "Prediction error",
  "trace_id": "ca7f0ed4298a4b4cf3561c298e4655d8",
  "span_id": "4d3ad4017566d5d7",
  "event": "feature_not_found",
  "status": "error"
}
```

Grafana configures the Loki `trace_id` field as a link to the Jaeger data source, allowing direct navigation from a log entry to the corresponding distributed trace.

## Consequences

### Positive

- Centralized Kubernetes logs.
- Lower infrastructure overhead than ELK for the current scale.
- Unified Grafana interface for metrics and logs.
- Natural integration with Prometheus-style labels.
- Structured LogQL queries.
- Direct trace-to-log correlation through OpenTelemetry `trace_id`.
- Promtail automatically enriches logs with Kubernetes metadata.

### Negative

- Loki is less suitable than Elasticsearch for advanced arbitrary full-text search.
- Good label design is important for efficient queries.
- High-cardinality values such as unique request IDs should not be used as Loki labels.
- Promtail and Loki add additional Kubernetes components that must be operated and monitored.

## Validation

The decision was validated in the Sentinel Kubernetes environment.

### Log Collection

Promtail successfully collects container logs and forwards them to Loki.

### Kubernetes Metadata

The following query successfully isolates the API logs:

```logql
{app="sentinel-api"}
```

### Error Search

A request for a nonexistent image generates a structured error log.

The following query returns the corresponding JSON log:

```logql
{app="sentinel-api"} |= "error"
```

The log contains:

```text
event="feature_not_found"
status="error"
http_status=404
```

### Trace Correlation

The API injects OpenTelemetry `trace_id` values into structured logs.

Searching Loki using the trace identifier returns the log corresponding to the same Jaeger trace:

```logql
{app="sentinel-api"} |= "<trace_id>"
```

Grafana also provides a derived-field link from the Loki `trace_id` directly to the Jaeger trace.

## Alternatives Considered

### ELK Stack

**Advantages:**

- Powerful full-text search.
- Rich general-purpose log analytics.
- Mature ecosystem.
- Strong fit for large search-heavy logging and SIEM use cases.

**Rejected because:**

- Higher RAM, CPU, and disk requirements.
- More operational components.
- Introduces Kibana in addition to Grafana.
- Full-text indexing is unnecessary for Sentinel's current Kubernetes observability requirements.

## Final Decision

Use **Promtail + Loki + Grafana** for centralized logging in Project Sentinel.

Loki provides the required Kubernetes log aggregation, structured log querying, and trace correlation while keeping resource usage and operational complexity appropriate for the scale and goals of the project.
