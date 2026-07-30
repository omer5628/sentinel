# ADR-007: Schema Evolution Strategy — Fail Fast vs. Flexible

## Status

Accepted

## Date

2026-07-27

## Context

Sentinel receives image events from a Producer through RabbitMQ and processes
them in the ingestion Worker.

The Producer and Worker are deployed independently. This means the Producer
may change the structure or meaning of an event before the Worker is updated.

Some changes cause an immediate application error, but other changes are more
dangerous because the system continues running while processing incorrect data.

Examples include:

- Changing `timestamp` from a numeric Unix timestamp to a string.
- Changing image dimensions from `28x28` to `32x32`.
- Sending an RGB image instead of a grayscale image.
- Changing pixel representation from integer values in the range `0-255` to
  normalized floating-point values in the range `0.0-1.0`.
- Adding or removing required fields without coordinating the Consumer update.

These changes can create training-serving skew, corrupt the Feature Store, or
silently reduce model quality.

Sentinel therefore requires an explicit schema evolution strategy.

## Decision

Sentinel will use a fail-fast schema validation strategy at the ingestion
boundary.

Every RabbitMQ message must:

1. Include a `schema_version` field.
2. Reference an active schema version in the Schema Registry.
3. Pass strict Pydantic validation.
4. Pass semantic image-quality validation before preprocessing.
5. Be rejected to a Dead Letter Queue when validation fails.

The Worker must not automatically coerce incompatible values.

For example, a string timestamp must not be silently converted into a float.

Unknown, inactive, malformed, or unsupported schema versions will be rejected.

Rejected messages will be sent to:

- Dead Letter Exchange: `sentinel.dlx`
- Dead Letter Queue: `video_stream.dlq`
- Routing Key: `video_stream.invalid`

The Worker will continue consuming subsequent messages after rejecting an
invalid event.

## Schema Versioning Rules

Schema versions are immutable after publication.

A published schema such as `v1` must not be modified in a way that changes its
existing meaning.

A new schema version must be created when a change is incompatible with an
existing Consumer.

Examples:

- `v1` expects a numeric Unix timestamp.
- `v2` may introduce an ISO 8601 timestamp string.

Both versions may remain active temporarily during migration.

The Worker must contain an explicit mapping between supported schema versions
and their Pydantic models.

Example:

```python
SCHEMA_MODELS = {
    "v1": ImageMessageV1,
    "v2": ImageMessageV2,
}