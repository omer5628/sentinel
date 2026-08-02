# ADR-016: Decoupled Inference Architecture

## Status

Accepted

## Context

In the earlier architecture, the FastAPI application loaded and executed the
TorchScript model directly.

This tightly coupled the application layer with model inference.

As traffic increased, the API was responsible for both:

- Request handling.
- Model execution.

This made it harder to scale application traffic and inference workloads
independently.

It also meant that every application instance needed to load the model and
allocate the resources required for inference.

During Phase 3.5, the serving architecture was redesigned so that model
execution is handled by a dedicated serving layer.

## Decision

Adopt ClearML Serving with Triton Inference Server as the dedicated inference
platform.

The application no longer executes the model directly.

Instead, inference requests are sent to the serving layer over gRPC.

The architecture becomes:

```text
Application / Worker
        |
        | gRPC
        v
ClearML Serving
        |
        v
Triton Inference Server
        |
        v
Model