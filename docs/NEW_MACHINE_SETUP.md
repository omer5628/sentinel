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

Configure Git identity if needed. Repository-local configuration is recommended unless you intentionally want the same identity for every repository on the machine:

```bash
git config user.name "YOUR_NAME"
git config user.email "YOUR_EMAIL"
```

Verify:

```bash
git config user.name
git config user.email
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

Start the existing ClearML Docker Compose deployment:

```bash
docker compose -f /opt/clearml/docker-compose.yml up -d
```

Verify the containers:

```bash
docker ps
```

Verify the Web UI at:

```text
http://localhost:8080
```

Verify the API locally:

```bash
curl -fsS http://127.0.0.1:8008/debug.ping
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

Recommended local SDK endpoints:

```text
API:        http://127.0.0.1:8008
Web:        http://127.0.0.1:8080
Fileserver: http://127.0.0.1:8081
```

On a GCP Cloud Workstation, keep the ClearML SDK configured with these local endpoints. Browser-accessible Workstation URLs are separate from the SDK configuration.

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

The project uses Kubernetes Secrets for sensitive service credentials.

Core Sentinel credentials are stored in:

```text
sentinel-service-secrets
```

ClearML Serving credentials are stored separately in:

```text
clearml-serving-credentials
```

Verify:

```bash
kubectl get secrets
kubectl get secret sentinel-service-secrets
kubectl get secret clearml-serving-credentials
```

The ClearML Serving Secret is automatically created or updated by:

```bash
make k8s-serving-deploy SERVING_TASK_ID=YOUR_SERVING_TASK_ID
```

The deployment script reads the ClearML API credentials from:

```text
~/clearml.conf
```

and stores them in the Kubernetes Secret without printing the credential values.

Never place real credentials directly inside tracked Kubernetes YAML files, Helm values files, shell scripts, or documentation.

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

Apply the core manifests with:

```bash
make k8s-apply
```

This applies the configuration, infrastructure, and application manifests in order.

Check:

```bash
make k8s-status
```

Expected core components include PostgreSQL, Redis, RabbitMQ, Sentinel Worker, and Sentinel API.

---

# 10. ClearML Serving

Sentinel uses ClearML Serving together with Triton Inference Server.

The ClearML Server runs outside Minikube on the development machine, while ClearML Serving and Triton run inside Kubernetes.

Because of this, Kubernetes Pods must use host-accessible ClearML endpoints rather than `localhost`.

The project contains:

```text
serving/values-sentinel.yaml
scripts/deploy_clearml_serving.sh
scripts/helm-plugins/clearml-secret-postrenderer/
```

## Prepare the ClearML Helm repository

On a new machine, make sure the ClearML Helm repository exists:

```bash
helm repo add clearml https://clearml.github.io/clearml-helm-charts
helm repo update
```

If the repository already exists, Helm may report that it is already configured.

## Create the ClearML Serving control task

On a new ClearML Server, create the Serving control task:

```bash
uv run clearml-serving create \
  --name sentinel-serving \
  --project Sentinel
```

Save the returned task ID.

The Serving Task ID is server-specific and must not be hard-coded in tracked configuration.

## Deploy ClearML Serving

Use:

```bash
make k8s-serving-deploy SERVING_TASK_ID=YOUR_SERVING_TASK_ID
```

Do not literally use:

```text
<id>
```

because `<` and `>` are shell redirection operators.

The deployment script:

1. Detects the Minikube host address.
2. Determines a ClearML Fileserver URL reachable from Kubernetes.
3. Reads ClearML API credentials from `~/clearml.conf`.
4. Creates or updates the `clearml-serving-credentials` Kubernetes Secret.
5. Installs the project ClearML Helm post-renderer plugin if needed.
6. Deploys or upgrades ClearML Serving using Helm.
7. Replaces ClearML credential values with Kubernetes `secretKeyRef` references.
8. Waits for ClearML Serving and Triton to become ready.

Verify:

```bash
kubectl get deployment clearml-serving-inference
kubectl get deployment clearml-serving-triton
kubectl get pods
```

Both deployments should be Ready.

---

# 11. ClearML Dataset, Models, and Artifact URLs

A new ClearML Server does not contain the Dataset, Model Registry entries, or Serving configuration from another ClearML Server. Recreate the required resources when moving to a fresh server.

## Upload the MNIST dataset

The project dataset can be uploaded with:

```bash
uv run python -m sentinel.upload_data
```

Verify the Dataset in the ClearML Web UI.

## Why model artifact URLs matter

ClearML Serving must be able to download model artifacts from the ClearML Fileserver.

An artifact URL such as:

```text
http://localhost:8081/...
```

cannot be downloaded from inside Kubernetes because `localhost` inside a Pod refers to that Pod.

Do not hard-code a machine-specific Minikube host IP.

## Determine the Minikube host address

Use:

```bash
MINIKUBE_HOST_IP="$(
  minikube ssh -- \
    "getent hosts host.minikube.internal | awk 'NR==1 {print \$1}'" \
    | tr -d '\r'
)"

echo "$MINIKUBE_HOST_IP"
```

A common value is:

```text
192.168.49.1
```

but the value can differ between machines or Minikube installations.

## Register the serving models

Set a Fileserver address that is reachable from Minikube:

```bash
export CLEARML_FILES_HOST="http://${MINIKUBE_HOST_IP}:8081"
export CLEARML_DEFAULT_OUTPUT_URI="$CLEARML_FILES_HOST"
```

Register V1:

```bash
uv run python scripts/register_model.py --version v1
```

Register V2:

```bash
uv run python scripts/register_model.py --version v2
```

The repository contains local development model files under:

```text
artifacts/model-v1.pt
artifacts/model-v2.pt
```

After registration, verify in ClearML that the model artifact URLs do not point to `localhost:8081`.

The ClearML Model Registry entries created on one server are not automatically transferred to another ClearML Server.

## Serving endpoints

After recreating the control task and model entries on a fresh ClearML Server, recreate the project Serving endpoint configuration for V1 and V2 before expecting inference requests to succeed.

The current Sentinel serving design uses:

```text
sentinel-mnist / version 1
sentinel-mnist / version 2
```

with Triton as the serving engine.

---

# 12. Deploy Observability

Deploy the observability stack with:

```bash
make k8s-observability-apply
```

The current observability stack includes:

```text
Prometheus
Grafana
OpenTelemetry
Jaeger
Loki
Promtail
```

Check:

```bash
kubectl get pods
```

The observability Pods should be Running/Ready.

---

# 13. Grafana Dashboard Persistence

The Sentinel Grafana dashboard is stored in the repository under:

```text
k8s/raw/04-observability/grafana/dashboards/
```

Grafana provisioning configures the required data sources:

```text
Prometheus
Loki
Jaeger
```

This allows the dashboard to be recreated after deleting Minikube or moving to another development machine.

Do not rely only on the Grafana PVC for important dashboards.

A PVC protects data from Pod restarts inside the same cluster but does not move the dashboard to another computer.

---

# 14. Start Port Forwards

Start all Sentinel Kubernetes port forwards with:

```bash
make k8s-ports
```

This starts:

```text
Sentinel API         http://localhost:8000
Grafana              http://localhost:3000
Prometheus           http://localhost:9090
Jaeger               http://localhost:16686
Loki                 http://localhost:3100
ClearML Serving      http://localhost:18080
Triton HTTP          http://localhost:18000
RabbitMQ AMQP        localhost:5673
RabbitMQ Management  http://localhost:15672
```

ClearML Server itself runs separately through Docker:

```text
ClearML Web          http://localhost:8080
ClearML API          http://localhost:8008
ClearML Fileserver   http://localhost:8081
```

Stop all project port forwards with:

```bash
make k8s-ports-stop
```

The stop command also removes stale Sentinel port-forward processes that may have been started manually.

When `make k8s-ports` is active, there is no need to separately run:

```bash
make k8s-rabbitmq-forward
```

The separate RabbitMQ target remains useful when only the Producer connection is needed.

---

# 15. Basic Validation

## Kubernetes

```bash
make k8s-status
```

Pods should be Running/Ready.

## Sentinel API

```bash
curl -fsS http://localhost:8000/live
curl -fsS http://localhost:8000/health
```

Expected responses include:

```json
{"status":"alive"}
{"status":"healthy"}
```

## Triton

```bash
curl -fsS http://localhost:18000/v2/health/ready
```

A successful request returns HTTP 200 and may have an empty response body.

Model readiness can also be checked with:

```bash
curl -fsS http://localhost:18000/v2/models/sentinel-mnist_1/ready
curl -fsS http://localhost:18000/v2/models/sentinel-mnist_2/ready
```

## Prometheus

```bash
curl -fsS http://localhost:9090/-/ready
```

Expected:

```text
Prometheus Server is Ready.
```

The Sentinel API target should also be UP in Prometheus.

The API exposes metrics at:

```bash
curl -fsS http://localhost:8000/metrics
```

## Grafana

Check:

```bash
curl -fsS http://localhost:3000/api/health
```

Then open:

```text
http://localhost:3000
```

Verify that the `Sentinel Observability` dashboard exists.

## Jaeger

Check:

```bash
curl -fsS http://localhost:16686/api/services
```

After predictions have been performed, the service:

```text
sentinel-api
```

should appear.

## Loki

```bash
curl -fsS http://localhost:3100/ready
```

Expected:

```text
ready
```

## RabbitMQ

RabbitMQ Management is available at:

```text
http://localhost:15672
```

The Producer connects through:

```text
localhost:5673
```

## ClearML Serving

The ClearML Serving inference service is available at:

```text
http://localhost:18080
```

---

# 16. Producer and End-to-End Data Flow

With `make k8s-ports` already running, start the Producer:

```bash
make producer-k8s
```

The expected ingestion flow is:

```text
Producer
   |
   v
RabbitMQ
   |
   v
Sentinel Worker
   |
   +--> Redis
   |
   +--> PostgreSQL
```

Check Redis:

```bash
kubectl exec redis-0 -- \
  redis-cli --scan --pattern 'feat:*' | head
```

Check PostgreSQL:

```bash
make k8s-postgres-count
```

Then test prediction using an existing Redis image ID:

```bash
curl -X POST \
  http://localhost:8000/predict/IMAGE_ID
```

A successful response should include:

```text
predicted_class
predicted_label
confidence
model_version
```

The Sentinel API performs V1 inference and also executes V2 shadow inference.

The complete prediction flow is:

```text
Producer -> RabbitMQ -> Worker -> Redis
                               |
                               v
                         Sentinel API
                               |
                               v
                    ClearML Serving / Triton
```

---

# 17. Common Problems

## Port already in use

Symptom:

```text
Unable to listen on port
bind: address already in use
```

Cause:

An old `kubectl port-forward` process is still running.

Fix:

```bash
make k8s-ports-stop
```

Verify:

```bash
pgrep -af "kubectl port-forward" || echo "No port-forwards running"
```

Then restart:

```bash
make k8s-ports
```

## ClearML artifact points to localhost

Symptom:

```text
Artifact could not be downloaded
Connection refused
localhost:8081
```

Cause:

The artifact URL is only reachable from the host.

Fix:

Re-register or re-upload the artifact using a Fileserver URL reachable from Minikube.

Do not hard-code the Minikube host IP.

## ClearML Serving credentials fail

First verify that the local ClearML SDK authentication works.

Check that:

```text
~/clearml.conf
```

contains the correct local server configuration.

Do not print the actual credential values.

Re-run:

```bash
make k8s-serving-deploy SERVING_TASK_ID=YOUR_SERVING_TASK_ID
```

This creates or updates:

```text
clearml-serving-credentials
```

and redeploys ClearML Serving.

## ClearML Web UI shows API fetch errors

If the ClearML API container was restarted and its Docker IP changed, the ClearML webserver may still use a stale upstream address.

Restart the ClearML webserver:

```bash
docker restart clearml-webserver
```

Then refresh the Web UI.

## ClearML Elasticsearch does not start

A possible cause is incorrect ownership of the Elasticsearch bind-mounted data directory.

For the current development deployment, the relevant directory is:

```text
/opt/clearml/data/elastic_7
```

Check its ownership before making changes.

If the deployment uses Elasticsearch UID 1000 and the directory ownership is incorrect, the ownership can be repaired with:

```bash
sudo chown -R 1000:0 /opt/clearml/data/elastic_7
```

Only run this after confirming that this is the ClearML Elasticsearch data directory for the current machine.

Restart the affected ClearML containers after fixing the ownership.

## GCP Cloud Workstation returns 401 PERMISSION_DENIED

When opening a Cloud Workstation URL in a browser, make sure the browser is authenticated with the Google account that has permission to use that Workstation.

For example, this can affect browser access to forwarded ClearML ports.

The local ClearML Python SDK should continue to use local endpoints such as:

```text
http://127.0.0.1:8008
http://127.0.0.1:8080
http://127.0.0.1:8081
```

The ClearML Web UI can proxy API requests through its Web endpoint, so direct browser access to the ClearML API port is not required for normal Web UI use.

## Grafana dashboard disappeared

Cause:

The dashboard existed only inside an old Grafana PVC.

Solution:

Keep the dashboard JSON and Grafana provisioning configuration in Git.

## Prometheus reports /metrics as 404

Possible cause:

Kubernetes is running an older Sentinel API Docker image.

Verify the deployed image and the routes exposed by the running API Pod.

## Redis contains no feat:* keys

Run:

```bash
make producer-k8s
```

and verify that the Worker is consuming RabbitMQ messages.

## API returns 405 Method Not Allowed

The prediction endpoint uses:

```text
POST /predict/{image_id}
```

not GET.

---

# 18. Security Checklist

Never commit:

- ClearML API access keys
- ClearML API secret keys
- GitHub access tokens
- Docker Hub tokens
- Kubernetes Secret values
- passwords
- `~/clearml.conf`
- `.env` files containing real credentials

ClearML Serving credentials must be stored in:

```text
clearml-serving-credentials
```

The Helm deployment uses the project post-renderer to convert ClearML credential environment values into Kubernetes `secretKeyRef` references.

The tracked Helm configuration must contain placeholders rather than real ClearML credentials.

If credentials are accidentally exposed, rotate them before continuing.

Before committing infrastructure changes, inspect the staged diff:

```bash
git diff --cached
```

Never paste real credentials into documentation, commits, or logs.

---

# 19. Recommended Startup Order

For an existing development environment:

```bash
make sync
make check
make minikube-up
make k8s-apply
make k8s-observability-apply
make k8s-serving-deploy SERVING_TASK_ID=YOUR_SERVING_TASK_ID
make k8s-status
make k8s-ports
```

On a completely new ClearML Server, recreate the required ClearML resources first:

```text
MNIST Dataset
V1 model
V2 model
ClearML Serving control task
V1 and V2 Serving endpoints
```

Then deploy ClearML Serving using the newly created Serving Task ID.

After the environment is running, validate the application flow:

```text
Producer -> RabbitMQ -> Worker -> Redis/PostgreSQL
                                |
                                v
                         Sentinel API
                                |
                                v
                       ClearML Serving/Triton
```

Also verify the observability flow:

```text
Metrics -> Prometheus -> Grafana
Logs    -> Loki       -> Grafana
Traces  -> Jaeger     -> Grafana
```

---

# Future Updates

This document describes the current Sentinel development environment using Docker and Minikube.

The project can run inside a GCP Cloud Workstation, but Minikube is still the Kubernetes environment used by this setup.

If Sentinel later moves from Minikube to a managed Kubernetes platform such as GKE, add a separate GKE deployment section rather than replacing the local Minikube instructions.
