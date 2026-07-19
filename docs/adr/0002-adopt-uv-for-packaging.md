# 2. Adopt uv for Packaging and Dependency Management

## Status
Accepted

## Context
Project Sentinel demands enterprise-grade stability and reproducibility ("Trust nothing"). Traditional Python packaging tools (like pip or poetry) can be slow during CI/CD builds and occasionally introduce non-deterministic environment states due to transient dependency updates. We need faster dependency resolution, reproducible environments, and strict locking via cryptographically verified SHA hashes.

## Decision
We will adopt `uv` as the exclusive tool for Python version management, package installation, environment isolation, and dependency locking.

## Consequences
* **Developer Environment:** All developers working on Project Sentinel must install `uv` globally on their local machines. Traditional `pip install` or `poetry` commands are banned.
* **Locking:** The `uv.lock` file is the absolute source of truth for dependencies and must be committed to the repository.
* **CI/CD Pipelines:** DevOps pipelines must be updated to use `uv`. To maximize build speeds, CI workflows must explicitly cache the `uv` global cache directory.