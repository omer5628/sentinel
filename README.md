# MLOps Sentinel

**MLOps Sentinel** is an end-to-end MLOps platform designed for building, serving, monitoring, and operating machine learning models in a production-like environment.

The project incorporates data ingestion, feature storage, model serving, Kubernetes deployment, experiment/model management, and full observability.

---

## 🛠️ Tech Stack

| Category | Technologies |
| :--- | :--- |
| **Development** | Python, `uv`, Ruff, Pyright, Pytest, Git, GitHub |
| **Data & Messaging** | PostgreSQL, Redis, RabbitMQ |
| **MLOps & Serving** | ClearML, ClearML Serving, NVIDIA Triton Inference Server, FastAPI, gRPC |
| **Infrastructure** | Docker, Docker Compose, Kubernetes, Minikube, Helm |
| **Observability** | Prometheus, Grafana, OpenTelemetry, Jaeger, Loki, Promtail |

---

## 📁 Project Structure

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
```

---

## 🚀 New Machine Setup

For detailed instructions on setting up Sentinel on a fresh development machine, please refer to the **[New Machine Setup Guide](docs/setup.md)**.

<details>
<summary><b>📋 What's covered in the setup guide?</b></summary>

* Required software dependencies
* Git and GitHub setup
* Python dependencies management
* Docker & Minikube initialization
* ClearML Server & Credentials setup
* Kubernetes Secrets configuration
* Sentinel application & ClearML Serving deployment
* Observability stack & Grafana dashboard persistence
* Port forwarding setup
* Basic validation & troubleshooting steps
</details>

---

## ⚡ Common Commands

Quick access to everyday commands using `make`:

```bash
# Install Python dependencies
uv sync

# Run quality checks (linting, typing, tests)
make check

# Create or start Minikube cluster
make minikube-up

# Check Kubernetes resources status
make k8s-status

# Deploy the observability stack (Prometheus, Grafana, Loki, etc.)
make k8s-observability-apply

# Apply and provision the Grafana dashboard
make grafana-dashboard-apply

# Start port forwarding for local access
make k8s-ports

# Stop port forwarding
make k8s-ports-stop

# List all available Make commands
make help
```

---

## 📊 Grafana Dashboards

The Sentinel Grafana dashboards are version-controlled and provisioned automatically.

* **Location:** `k8s/raw/04-observability/grafana/`

> **Note:** Dashboard configurations are persistent and will not be lost when recreating the Minikube cluster or switching machines.

---

## 🔒 Security Best Practices

> ⚠️ **IMPORTANT:** Never commit sensitive credentials or secret configuration files to the repository!

Ensure the following items remain uncommitted:
* ClearML API credentials & `~/clearml.conf`
* GitHub access tokens & Docker Hub tokens
* Kubernetes Secret values & Passwords
* Local `.env` files containing actual secrets

Use **local configuration files** and **Kubernetes Secrets** for secure environment management.

---

## 💻 Environment & Infrastructure

The current local development setup is documented for:
* **OS:** Linux
* **Containerization:** Docker
* **Kubernetes:** Minikube
* **MLOps Core:** Local ClearML Server

*Cloud deployment manifests and workflows (e.g., GCP / GKE) will be added in a future release.*