# Sentinel - New Machine Setup

This document explains how to prepare a new development machine and start working on the Sentinel project.

The document describes the current local development environment based on Linux, Docker, Minikube, and a locally hosted ClearML Server.

Update this document whenever the infrastructure or project requirements change.

---

# 1. Required Software

Install the following tools before starting the project.

## Git

Used for cloning and managing the project repository.

Verify:

```bash
git --version
```

## Python

Sentinel currently uses Python 3.11.

Verify:

```bash
python3 --version
```

## uv

Used for Python dependency management and virtual environments.

Verify:

```bash
uv --version
```

The project dependencies are defined in:

```text
pyproject.toml
uv.lock
```

Install the environment with:

```bash
uv sync
```

## Docker

Docker is required for local infrastructure and container builds.

Verify:

```bash
docker --version
docker ps
```

Docker should work without `sudo`.

## Docker Compose

Verify:

```bash
docker compose version
```

## Make

Verify:

```bash
make --version
```

Project commands:

```bash
make help
```

## kubectl

Verify:

```bash
kubectl version --client
```

## Minikube

Verify:

```bash
minikube version
```

## Helm

Verify:

```bash
helm version
```

---

# 2. Clone the Repository

```bash
git clone <SENTINEL_REPOSITORY_URL>
cd sentinel
```

Configure Git identity if needed:

```bash
git config --global user.name "YOUR_NAME"
git config --global user.email "YOUR_EMAIL"
```

Configure GitHub authentication using SSH or another appropriate GitHub authentication method.

Never store GitHub tokens inside the repository.

---

# 3. Install Python Dependencies

From the project root:

```bash
uv sync
```

Run the project checks:

```bash
make check
```

This runs Ruff, Pyright, and Pytest.

---

# 4. Start Docker

Verify Docker is running:

```bash
docker ps
```

If Docker is not running, start the Docker service before continuing.

---

# 5. Start the Local ClearML Server

Sentinel currently uses a locally hosted ClearML Server.

Current local endpoints:

```text
Web UI:     http://localhost:8080
API:        http://localhost:8008
Fileserver: http://localhost:8081
```

Current ClearML Docker Compose location used during development:

```text
/opt/clearml/docker-compose.yml
```

Start the existing ClearML Docker Compose deployment and verify the Web UI at:

```text
http://localhost:8080
```

---

# 6. Configure ClearML Credentials

A new machine needs ClearML API credentials.

Run:

```bash
clearml-init
```

The local configuration is normally stored at:

```text
~/clearml.conf
```

Expected local endpoints:

```text
API:        http://localhost:8008
Web:        http://localhost:8080
Fileserver: http://localhost:8081
```

Never commit ClearML access keys, secret keys, `~/clearml.conf`, or credentials copied from the ClearML Web UI.

---

# 7. Start Minikube

Use:

```bash
make minikube-up
```

Verify:

```bash
minikube status
kubectl get nodes
kubectl config current-context
```

The expected local context is:

```text
minikube
```

---

# 8. Kubernetes Secrets

The project requires credentials for services such as PostgreSQL, RabbitMQ, and ClearML.

These values must be stored in Kubernetes Secrets and must not be committed to Git.

Verify:

```bash
kubectl get secrets
kubectl get secret sentinel-service-secrets
```

If the Secret does not exist, recreate it using the project's expected environment variable names and credentials.

Never place real credentials directly inside tracked YAML files.

---

# 9. Deploy Sentinel Infrastructure

The Kubernetes manifests are organized as:

```text
k8s/raw/
├── 01-config/
├── 02-infra/
├── 03-apps/
└── 04-observability/
```

Apply the core manifests in order:

```bash
kubectl apply -f k8s/raw/01-config/
kubectl apply -f k8s/raw/02-infra/
kubectl apply -f k8s/raw/03-apps/
```

Check:

```bash
make k8s-status
```

Expected core components include PostgreSQL, Redis, RabbitMQ, Sentinel Worker, and Sentinel API.

---

# 10. ClearML Serving

Sentinel uses ClearML Serving together with Triton Inference Server.

ClearML Serving must be able to reach the ClearML Server running on the host machine.

From inside Minikube, `localhost` refers to the Pod itself, not the development machine.

Typical host-accessible configuration includes:

```text
API: http://host.minikube.internal:8008
Web: http://host.minikube.internal:8080
```

The Fileserver must also be reachable from Minikube.

Do not assume a machine-specific IP is valid on another computer. Verify connectivity first.

---

# 11. Important ClearML Artifact Rule

A ClearML artifact uploaded with:

```text
http://localhost:8081
```

cannot be downloaded by a ClearML Serving Pod because `localhost` inside Kubernetes refers to the Pod itself.

Before uploading ClearML Serving preprocess artifacts, use a Fileserver address that is reachable from Minikube.

Use the Minikube host alias when the artifact must be accessible from Kubernetes:

```text
http://host.minikube.internal:8081
```

Do not assume `192.168.49.1` is valid on another machine.

After uploading an artifact, verify its URL:

Example:
CLEARML_FILES_HOST=http://host.minikube.internal:8081 \
CLEARML_DEFAULT_OUTPUT_URI=http://host.minikube.internal:8081 \
uv run python ...

Before uploading artifacts, verify that the Fileserver is reachable from inside Minikube:
kubectl exec -i deployment/clearml-serving-inference -- \
  python - <<'PY'
import urllib.request

url = "http://host.minikube.internal:8081"

with urllib.request.urlopen(url, timeout=5) as response:
    print(response.status)
PY
Expected:
200
```python
from clearml import Task

task = Task.get_task(task_id="TASK_ID")

for name, artifact in task.artifacts.items():
    print(name, artifact.url)
```

The URL must not point to `localhost:8081` if it needs to be accessed from Kubernetes.

---

# 12. Deploy Observability

Deploy:

```bash
kubectl apply -f k8s/raw/04-observability/
```

The current observability stack includes Prometheus, Grafana, OpenTelemetry, Jaeger, Loki, and Promtail.

Check:

```bash
kubectl get pods
```

---

# 13. Grafana Dashboard Persistence

The Sentinel Grafana dashboard is stored in the repository under:

```text
k8s/raw/04-observability/grafana/dashboards/
```

The dashboard ConfigMap is also stored as a Kubernetes manifest.

This allows the dashboard to be restored after recreating Minikube or moving to another development machine.

Grafana provisioning automatically configures Prometheus, Loki, and Jaeger data sources.

Do not rely only on the Grafana PVC for important dashboards. A PVC protects data from Pod restarts on the same cluster, but does not automatically move it to another computer.

---

# 14. Start Port Forwards

Use:

```bash
make k8s-ports
```

Current local endpoints:

```text
Sentinel API    http://localhost:8000
Grafana         http://localhost:3000
Prometheus      http://localhost:9090
Jaeger          http://localhost:16686
Loki            http://localhost:3100
ClearML Serving  http://localhost:18080
```

ClearML itself runs separately:

```text
ClearML Web     http://localhost:8080
ClearML API     http://localhost:8008
ClearML Files   http://localhost:8081
```

Stop the port forwards with:

```bash
make k8s-ports-stop
```

---

# 15. Basic Validation

## Kubernetes

```bash
make k8s-status
```

Pods should be Running/Ready.

## API

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
```

## Prometheus

```bash
curl http://localhost:8000/metrics
```

Prometheus should report the Sentinel API target as UP.

## Grafana

Open:

```text
http://localhost:3000
```

Verify that the `Sentinel Observability` dashboard exists.

## Jaeger

Open:

```text
http://localhost:16686
```

The service `sentinel-api` should appear after predictions are performed.

## Loki

```bash
curl http://localhost:3100/ready
```

Expected:

```text
ready
```

---

# 16. Producer and Redis Data

If the API reports that an image has not been processed yet, Redis may not contain feature data.

Start RabbitMQ forwarding:

```bash
make k8s-rabbitmq-forward
```

Then run the producer in another terminal:

```bash
make producer-k8s
```

Check Redis:

```bash
kubectl exec redis-0 -- redis-cli --scan --pattern 'feat:*' | head
```

---

# 17. Common Problems

## ClearML artifact points to localhost

Symptom:

```text
Artifact could not be downloaded
Connection refused
localhost:8081
```

Cause: the artifact was uploaded using a URL that is only valid on the host machine.

Fix: re-upload the artifact using a Fileserver URL accessible from Kubernetes.

## Grafana dashboard disappeared

Cause: the dashboard existed only inside the old Grafana PVC.

Solution: keep dashboards as JSON in the repository and provision them using ConfigMaps.

## Prometheus reports /metrics as 404

Possible cause: Kubernetes is running an older Sentinel API Docker image.

Check the routes inside the running Pod and verify the deployed image tag.

## Redis contains no feat:* keys

Run the Producer and make sure the Worker is consuming RabbitMQ messages.

## API returns 405 Method Not Allowed

The prediction endpoint uses:

```text
POST /predict/{image_id}
```

not GET.

---

# 18. Security Checklist

Never commit:

- ClearML API credentials
- GitHub access tokens
- Docker Hub tokens
- Kubernetes Secret values
- passwords
- `~/clearml.conf`
- `.env` files containing real credentials

Use Git ignore rules and Kubernetes Secrets where appropriate.

If credentials are accidentally exposed or committed, rotate them.

---

# 19. After Setup

Once the environment is ready:

```bash
make check
make minikube-up
make k8s-status
make k8s-ports
```

Then continue development from the current Sentinel phase.

---

# Future Updates

This document currently describes the local Minikube environment.

When Sentinel moves to a cloud environment such as GCP/GKE, add a separate cloud setup section instead of replacing the local development instructions.
