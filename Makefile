.PHONY: \
	help \
	system-up \
	backup-runtime \
	docker-persistence-check minikube-network-check \
	check lint type-check test sync \
	compose-up compose-build compose-down compose-restart compose-logs \
	producer-local worker-local api-local \
	minikube-up minikube-stop minikube-delete \
	k8s-apply k8s-observability-apply k8s-serving-deploy \
	k8s-status k8s-worker-logs k8s-api-logs \
	k8s-rabbitmq-forward producer-k8s \
	k8s-postgres-count \
	grafana-dashboard-apply \
	k8s-ports k8s-ports-stop


help:
	@echo "Available commands:"
	@echo ""
	@echo "Environment:"
	@echo "  make sync                    Install Python dependencies with uv"
	@echo "  make docker-persistence-check Verify persistent Docker storage"
	@echo "  make minikube-network-check   Verify Kubernetes service networking"
	@echo ""
	@echo "Quality checks:"
	@echo "  make check                   Run Ruff, Pyright and Pytest"
	@echo "  make lint                    Run Ruff"
	@echo "  make type-check              Run Pyright"
	@echo "  make test                    Run Pytest"
	@echo ""
	@echo "Docker Compose:"
	@echo "  make compose-up              Start Docker Compose"
	@echo "  make compose-build           Build and start Docker Compose"
	@echo "  make compose-down            Stop Docker Compose"
	@echo "  make compose-restart         Restart Docker Compose"
	@echo "  make compose-logs            Show Docker Compose logs"
	@echo ""
	@echo "Local development:"
	@echo "  make producer-local          Start the producer locally"
	@echo "  make worker-local            Start the worker locally"
	@echo "  make api-local               Start the API locally"
	@echo ""
	@echo "Minikube:"
	@echo "  make minikube-up             Create or start Minikube"
	@echo "  make minikube-stop           Stop Minikube"
	@echo "  make minikube-delete         Delete Minikube"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make k8s-apply               Apply Sentinel Kubernetes manifests"
	@echo "  make k8s-observability-apply Apply observability stack"
	@echo "  make k8s-serving-deploy SERVING_TASK_ID=<id>"
	@echo "                               Deploy ClearML Serving with Helm"
	@echo "  make k8s-status              Show Sentinel Kubernetes resources"
	@echo "  make k8s-worker-logs         Follow Kubernetes worker logs"
	@echo "  make k8s-api-logs            Follow Kubernetes API logs"
	@echo "  make k8s-rabbitmq-forward    Forward localhost:5673 to RabbitMQ"
	@echo "  make producer-k8s            Send producer data to Kubernetes RabbitMQ"
	@echo "  make k8s-postgres-count      Count rows in feature_log"
	@echo ""
	@echo "Grafana:"
	@echo "  make grafana-dashboard-apply Apply the Sentinel Grafana dashboard"
	@echo ""
	@echo "Port forwarding:"
	@echo "  make k8s-ports               Start all project port forwards"
	@echo "  make k8s-ports-stop          Stop all project port forwards"
	@echo "Backup:"
	@echo "  make backup-runtime          Back up persistent runtime state"
	@echo ""
	@echo "System:"
	@echo "  make system-up               Start Minikube and all port forwards"
	@echo ""


# --------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------

sync:
	uv sync

docker-persistence-check:
	@./scripts/ensure_docker_persistence.sh

minikube-network-check:
	@./scripts/ensure_minikube_networking.sh


# --------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------

check:
	uv run ruff check .
	uv run pyright
	uv run pytest

lint:
	uv run ruff check .

type-check:
	uv run pyright

test:
	uv run pytest


# --------------------------------------------------------------------
# Docker Compose
# --------------------------------------------------------------------

compose-up:
	docker compose up -d

compose-build:
	docker compose up --build -d

compose-down:
	docker compose down

compose-restart:
	docker compose down
	docker compose up -d

compose-logs:
	docker compose logs -f


# --------------------------------------------------------------------
# Local development
# --------------------------------------------------------------------

producer-local:
	uv run python -m sentinel.producers.camera_feed

worker-local:
	uv run python -m sentinel.consumers.worker

api-local:
	uv run uvicorn sentinel.serving.api:app \
		--reload \
		--host 0.0.0.0 \
		--port 8000


# --------------------------------------------------------------------
# Minikube
# --------------------------------------------------------------------
MINIKUBE_CPUS ?= 10
MINIKUBE_MEMORY ?= 24576
MINIKUBE_RESERVED_CPUS ?= 6
MINIKUBE_RESERVED_MEMORY ?= 37Gi

minikube-up:
	@$(MAKE) docker-persistence-check
	@echo "Checking Minikube..."
	@if ! command -v minikube >/dev/null 2>&1; then \
		echo "ERROR: Minikube is not installed."; \
		echo "See docs/NEW_MACHINE_SETUP.md"; \
		exit 1; \
	fi
	@if ! minikube profile list -o json 2>/dev/null | grep -Eq '"Name"[[:space:]]*:[[:space:]]*"minikube"'; then \
		echo "Minikube cluster does not exist. Creating it..."; \
		minikube start \
			--driver=docker \
			--cpus=$(MINIKUBE_CPUS) \
			--memory=$(MINIKUBE_MEMORY) \
			--extra-config=kubelet.system-reserved=cpu=$(MINIKUBE_RESERVED_CPUS),memory=$(MINIKUBE_RESERVED_MEMORY) \
			--extra-config=kube-proxy.masquerade-all=true; \
	elif ! minikube status >/dev/null 2>&1; then \
		echo "Minikube cluster exists but is stopped. Starting it..."; \
		minikube start; \
	else \
		echo "Minikube is already running."; \
	fi
	@kubectl config use-context minikube >/dev/null
	@$(MAKE) minikube-network-check
	@echo ""
	@echo "Current Kubernetes context:"
	@kubectl config current-context

minikube-delete:
	@echo "Deleting Minikube cluster..."
	minikube delete


# --------------------------------------------------------------------
# Kubernetes deployment
# --------------------------------------------------------------------

k8s-apply:
	kubectl apply -f k8s/raw/01-config/
	kubectl apply -f k8s/raw/02-infra/
	kubectl apply -f k8s/raw/03-apps/

k8s-observability-apply:
	kubectl apply -f k8s/raw/04-observability/

k8s-serving-deploy:
	@if [ -z "$(SERVING_TASK_ID)" ]; then \
		echo "ERROR: SERVING_TASK_ID is required."; \
		echo "Usage:"; \
		echo "  make k8s-serving-deploy SERVING_TASK_ID=<task-id>"; \
		exit 1; \
	fi
	SERVING_TASK_ID="$(SERVING_TASK_ID)" \
		./scripts/deploy_clearml_serving.sh

k8s-status:
	kubectl get pods,services,statefulsets,deployments,pvc

k8s-worker-logs:
	kubectl logs deployment/sentinel-worker --follow

k8s-api-logs:
	kubectl logs deployment/sentinel-api --follow

k8s-rabbitmq-forward:
	kubectl port-forward -n sentinel-dev service/rabbitmq 5673:5672

producer-k8s:
	RABBITMQ_HOST=localhost \
	RABBITMQ_PORT=5673 \
	RABBITMQ_USERNAME="$$(kubectl get secret sentinel-service-secrets \
		-n sentinel-dev \
		-o jsonpath='{.data.RABBITMQ_USERNAME}' | base64 -d)" \
	RABBITMQ_PASSWORD="$$(kubectl get secret sentinel-service-secrets \
		-n sentinel-dev \
		-o jsonpath='{.data.RABBITMQ_PASSWORD}' | base64 -d)" \
	uv run python -m sentinel.producers.camera_feed

k8s-postgres-count:
	kubectl exec -n sentinel-dev postgres-0 -- \
		sh -c 'psql -U "$$POSTGRES_USER" \
		-d "$$POSTGRES_DB" \
		-tAc "SELECT COUNT(*) FROM feature_log;"'


# --------------------------------------------------------------------
# Grafana
# --------------------------------------------------------------------

grafana-dashboard-apply:
	kubectl create configmap grafana-dashboards \
		--from-file=sentinel-observability.json=k8s/raw/04-observability/grafana/dashboards/sentinel-observability.json \
		--dry-run=client \
		-o yaml \
		| kubectl apply -f -
	kubectl rollout restart deployment/grafana
	kubectl rollout status deployment/grafana

# --------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------

backup-runtime:
	@./scripts/backup_runtime_state.sh
# --------------------------------------------------------------------
# Port forwarding
# --------------------------------------------------------------------

k8s-ports:
	@echo "Starting Kubernetes port forwards..."
	@$(MAKE) k8s-ports-stop >/dev/null 2>&1 || true

	kubectl port-forward -n sentinel-dev service/grafana 3000:3000 \
		> /tmp/grafana-port.log 2>&1 & \
		echo $$! > /tmp/grafana-port.pid

	kubectl port-forward -n sentinel-dev service/prometheus 9090:9090 \
		> /tmp/prometheus-port.log 2>&1 & \
		echo $$! > /tmp/prometheus-port.pid

	kubectl port-forward -n sentinel-dev service/jaeger 16686:16686 \
		> /tmp/jaeger-port.log 2>&1 & \
		echo $$! > /tmp/jaeger-port.pid

	kubectl port-forward -n sentinel-dev service/sentinel-api 8000:8000 \
		> /tmp/sentinel-api-port.log 2>&1 & \
		echo $$! > /tmp/sentinel-api-port.pid

	kubectl port-forward -n sentinel-dev service/loki 3100:3100 \
		> /tmp/loki-port.log 2>&1 & \
		echo $$! > /tmp/loki-port.pid

	kubectl port-forward -n default service/clearml-serving-inference 18080:8080 \
		> /tmp/clearml-serving-port.log 2>&1 & \
		echo $$! > /tmp/clearml-serving-port.pid

	kubectl port-forward -n default deployment/clearml-serving-triton 18000:8000 \
		> /tmp/triton-port.log 2>&1 & \
		echo $$! > /tmp/triton-port.pid

	kubectl port-forward -n sentinel-dev service/rabbitmq 5673:5672 \
		> /tmp/rabbitmq-amqp-port.log 2>&1 & \
		echo $$! > /tmp/rabbitmq-amqp-port.pid

	kubectl port-forward -n sentinel-dev pod/rabbitmq-0 15672:15672 \
		> /tmp/rabbitmq-management-port.log 2>&1 & \
		echo $$! > /tmp/rabbitmq-management-port.pid

	kubectl port-forward -n jenkins service/jenkins 8082:8080 \
		> /tmp/jenkins-port.log 2>&1 & \
		echo $$! > /tmp/jenkins-port.pid

	@sleep 2
	@echo ""
	@echo "Port forwards started:"
	@echo "  Sentinel API:        http://localhost:8000"
	@echo "  Grafana:             http://localhost:3000"
	@echo "  Prometheus:          http://localhost:9090"
	@echo "  Jaeger:              http://localhost:16686"
	@echo "  Loki:                http://localhost:3100"
	@echo "  ClearML Serving:     http://localhost:18080"
	@echo "  Triton HTTP:         http://localhost:18000"
	@echo "  RabbitMQ AMQP:       localhost:5673"
	@echo "  RabbitMQ Management: http://localhost:15672"
	@echo "  Jenkins:             http://localhost:8082"
	@echo ""
	@echo "ClearML Server runs separately:"
	@echo "  Web:                 http://localhost:8080"
	@echo "  API:                 http://localhost:8008"
	@echo "  Files:               http://localhost:8081"

k8s-ports-stop:
	@echo "Stopping Kubernetes port forwards..."
	@for file in \
		/tmp/grafana-port.pid \
		/tmp/prometheus-port.pid \
		/tmp/jaeger-port.pid \
		/tmp/sentinel-api-port.pid \
		/tmp/loki-port.pid \
		/tmp/clearml-serving-port.pid \
		/tmp/triton-port.pid \
		/tmp/rabbitmq-amqp-port.pid \
		/tmp/rabbitmq-management-port.pid \
		/tmp/jenkins-port.pid; do \
		if [ -f "$$file" ]; then \
			kill "$$(cat "$$file")" 2>/dev/null || true; \
			rm -f "$$file"; \
		fi; \
	done
	@ps -eo pid=,args= | awk \
		'($$2 == "kubectl" && $$3 == "port-forward" && \
		($$4 == "service/grafana" || \
		 $$4 == "deployment/grafana" || \
		 $$4 == "service/prometheus" || \
		 $$4 == "deployment/prometheus" || \
		 $$4 == "service/jaeger" || \
		 $$4 == "deployment/jaeger" || \
		 $$4 == "service/sentinel-api" || \
		 $$4 == "deployment/sentinel-api" || \
		 $$4 == "service/loki" || \
		 $$4 ~ /^pod\/loki-/ || \
		 $$4 == "service/clearml-serving-inference" || \
		 $$4 == "deployment/clearml-serving-triton" || \
		 $$4 == "service/rabbitmq" || \
		 $$4 ~ /^pod\/rabbitmq-/)) || \
		($$2 == "kubectl" && $$3 == "port-forward" && \
		 $$4 == "-n" && $$5 == "jenkins" && \
		 $$6 == "service/jenkins") \
		{print $$1}' \
		| xargs -r kill 2>/dev/null || true
	@echo "Port forwards stopped."


system-up:
	@echo "Starting Sentinel system..."
	@$(MAKE) minikube-up
	@$(MAKE) k8s-ports
	@echo ""
	@echo "Sentinel system is up."
