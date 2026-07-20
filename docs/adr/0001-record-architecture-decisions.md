# 1. Record Architecture Decisions

## Status
Accepted

## Context
We need a way to document the architectural decisions made for Project Sentinel. As the project evolves, understanding the "why" behind past decisions becomes critical for maintenance, onboarding, and scaling.

## Decision
We will use Architecture Decision Records (ADRs) to document all major technical and architectural decisions. These records will be stored in the codebase under `docs/adr/` in Markdown format.

## Consequences
* Every major technical change or tool adoption must be accompanied by a new ADR.
* Future developers can track the evolution of the system by reading these documents chronologically.
* Code reviews will include checking if the implementation aligns with the accepted ADRs.