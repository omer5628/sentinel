# MLOps Sentinel

MLOps Sentinel is an end-to-end MLOps project for building, serving, monitoring, and operating machine-learning models in a production-like environment.

The project currently includes data ingestion, feature storage, model serving, Kubernetes deployment, experiment/model management, and observability.

## Current Stack

### Development
- Python
- uv
- Ruff
- Pyright
- Pytest
- Git / GitHub

### Data & Messaging
- PostgreSQL
- Redis
- RabbitMQ

### MLOps & Model Serving
- ClearML
- ClearML Serving
- NVIDIA Triton Inference Server
- FastAPI
- gRPC

### Infrastructure
- Docker
- Docker Compose
- Kubernetes
- Minikube
- Helm

### Observability
- Prometheus
- Grafana
- OpenTelemetry
- Jaeger
- Loki
- Promtail

## Project Structure

```text
sentinel/
├── conf/
├── docs/
├── external/
├── k8s/
├── scripts/
├── serving/
├── src/
├── tests/
├── Dockerfile.api
├── Makefile
├── pyproject.toml
├── uv.lock
└── README.md

New Machine Setup

For complete instructions for setting up Sentinel on a new development machine, see:

New Machine Setup

The setup guide includes:

Required software
Git and GitHub setup
Python dependencies
Docker
ClearML Server
ClearML credentials
Minikube
Kubernetes Secrets
Sentinel deployment
ClearML Serving
Observability
Grafana dashboard persistence
Port forwarding
Basic validation
Common troubleshooting
Common Commands

Install Python dependencies:

uv sync

Run quality checks:

make check

Create or start Minikube:

make minikube-up

Show Kubernetes resources:

make k8s-status

Start port forwarding:

make k8s-ports

Stop port forwarding:

make k8s-ports-stop

Show all available Make commands:

make help
Grafana Dashboard

The Sentinel Grafana dashboard is stored in the repository and is provisioned automatically.

Dashboard files are located under:

k8s/raw/04-observability/grafana/

This prevents dashboards from being lost when Minikube is recreated or development moves to another machine.

Security

Never commit:

ClearML API credentials
GitHub access tokens
Docker Hub tokens
Kubernetes Secret values
Passwords
~/clearml.conf
.env files containing real credentials

Credentials should be stored using local configuration and Kubernetes Secrets.

Development Environment

The current documented local environment uses:

Linux
Docker
Minikube
Local ClearML Server

Cloud deployment instructions such as GCP/GKE will be added separately when the project reaches that stage.