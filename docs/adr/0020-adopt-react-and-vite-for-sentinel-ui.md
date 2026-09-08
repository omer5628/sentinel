# ADR-0020: Adopt React and Vite for the Sentinel UI

* **Status:** Accepted
* **Date:** 2026-09-03
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel requires an operational user interface that can grow beyond the existing Streamlit labeling cockpit.

The initial UI requirements include:

* Monitoring the Producer, RabbitMQ, Worker, and feature-store flow.
* Displaying recently processed images.
* Displaying the real image stored by the Worker.
* Displaying human-labeling state.
* Supporting a dedicated labeling workflow.
* Supporting Producer controls in a later iteration.
* Supporting additional operational pages in the future.

The existing Streamlit application is useful for a small labeling workflow, but the planned Sentinel UI requires richer navigation, reusable components, asynchronous API communication, and more control over the frontend behavior.

The serving API is dedicated to real-time inference and communicates with Redis and Triton. UI-specific database access should not be added to that inference path.

## Decision

Sentinel will use **React with JavaScript** for the primary frontend.

**Vite** will be used as the frontend development and build tool.

The frontend will live under:

```text
frontend/
```

UI-specific backend functionality will use a separate FastAPI application under:

```text
src/sentinel/ui/
```

The high-level architecture will be:

```text
React Frontend
      |
      | HTTP / REST
      v
Sentinel UI API
      |
      +--> PostgreSQL
      +--> Additional operational integrations when required
```

The React frontend must not connect directly to PostgreSQL, Redis, RabbitMQ, or other infrastructure services.

The existing Sentinel Serving API will remain focused on:

```text
Redis -> Triton -> Inference
```

The Sentinel UI API will initially provide access to processed event metadata and stored images from PostgreSQL.

During local development, Vite will proxy frontend API requests to the local Sentinel UI API.

The frontend will initially use standard CSS without introducing an additional CSS framework.

The UI will be containerized and deployed to Kubernetes in a later iteration.

## Alternatives Considered

### Continue with Streamlit

Rejected as the primary UI.

Streamlit is convenient for small Python-based internal tools, but the planned Sentinel UI requires more frontend control, reusable navigation, multiple operational pages, and richer interaction.

The existing Streamlit labeling implementation may remain temporarily while its functionality is migrated.

### Server-rendered HTML from FastAPI

Rejected.

This would reduce frontend tooling but would make the planned interactive monitoring and labeling experience harder to evolve.

### React with TypeScript

Not selected for the initial implementation.

JavaScript provides sufficient functionality for the current project and keeps the frontend learning curve and implementation scope smaller.

TypeScript can be reconsidered if frontend complexity grows significantly.

## Consequences

### Positive

* Clear separation between frontend and backend responsibilities.
* The inference API remains independent from PostgreSQL.
* The UI can grow into multiple pages and workflows.
* React components can be reused across monitoring and labeling views.
* Vite provides a fast local development workflow.
* The same frontend can later be built into a container and deployed to Kubernetes.

### Negative

* Node.js and npm become part of the project toolchain.
* The project now contains both Python and JavaScript dependency ecosystems.
* A separate frontend build and deployment process will eventually be needed.
* The existing Streamlit labeling functionality will require migration if it is retired.

## Validation

The decision is considered successfully implemented when:

1. The React frontend runs locally with Vite.
2. The Sentinel UI API runs independently from the Serving API.
3. React retrieves processed events through the UI API.
4. React displays the real image stored in PostgreSQL.
5. The frontend has no direct database or infrastructure-service connection.
6. The frontend can later be packaged for Kubernetes deployment.
