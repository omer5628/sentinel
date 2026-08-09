.PHONY: \
	help \
	check lint type-check test \
	compose-up compose-build compose-down compose-restart compose-logs \
	producer-local worker-local api-local \
	minikube-up minikube-stop minikube-delete \
	k8s-status k8s-worker-logs k8s-api-logs \
	k8s-rabbitmq-forward producer-k8s \
	k8s-postgres-count \
	k8s-ports k8s-ports-stop

help:
	@echo "Available commands:"
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
	@echo "  make minikube-up             Create or start the Minikube cluster"
	@echo "  make minikube-stop           Stop the Minikube cluster"
	@echo "  make minikube-delete         Delete the Minikube cluster"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make k8s-status              Show Sentinel Kubernetes resources"
	@echo "  make k8s-worker-logs         Follow Kubernetes worker logs"
	@echo "  make k8s-api-logs            Follow Kubernetes API logs"
	@echo "  make k8s-rabbitmq-forward    Forward localhost:5673 to RabbitMQ"
	@echo "  make producer-k8s            Send producer data to Kubernetes RabbitMQ"
	@echo "  make k8s-postgres-count      Count rows in feature_log"
	@echo "  make k8s-ports               Start observability/API port forwards"
	@echo "  make k8s-ports-stop          Stop observability/API port forwards"

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

producer-local:
	uv run python -m sentinel.producers.camera_feed

worker-local:
	uv run python -m sentinel.consumers.worker

api-local:
	uv run uvicorn sentinel.serving.api:app \
		--reload \
		--host 0.0.0.0 \
		--port 8000

minikube-up:
	@echo "Checking Minikube..."
	@if ! command -v minikube >/dev/null 2>&1; then \
		echo "ERROR: Minikube is not installed."; \
		echo "Install Minikube before running this command."; \
		exit 1; \
	fi
	@if ! minikube profile list -o json 2>/dev/null | grep -q '"Name": "minikube"'; then \
		echo "Minikube cluster does not exist. Creating it..."; \
		minikube start; \
	elif ! minikube status >/dev/null 2>&1; then \
		echo "Minikube cluster exists but is stopped. Starting it..."; \
		minikube start; \
	else \
		echo "Minikube is already running."; \
	fi
	@echo ""
	@kubectl config use-context minikube >/dev/null
	@echo "Current Kubernetes context:"
	@kubectl config current-context

minikube-stop:
	@echo "Stopping Minikube..."
	minikube stop

minikube-delete:
	@echo "Deleting Minikube cluster..."
	minikube delete

k8s-status:
	kubectl get pods,services,statefulsets,deployments,pvc

k8s-worker-logs:
	kubectl logs deployment/sentinel-worker --follow

k8s-api-logs:
	kubectl logs deployment/sentinel-api --follow

k8s-rabbitmq-forward:
	kubectl port-forward pod/rabbitmq-0 5673:5672

producer-k8s:
	RABBITMQ_HOST=localhost \
	RABBITMQ_PORT=5673 \
	RABBITMQ_USERNAME="$$(kubectl get secret sentinel-service-secrets \
		-o jsonpath='{.data.RABBITMQ_USERNAME}' | base64 -d)" \
	RABBITMQ_PASSWORD="$$(kubectl get secret sentinel-service-secrets \
		-o jsonpath='{.data.RABBITMQ_PASSWORD}' | base64 -d)" \
	uv run python -m sentinel.producers.camera_feed

k8s-postgres-count:
	kubectl exec postgres-0 -- \
		sh -c 'psql -U "$$POSTGRES_USER" \
		-d "$$POSTGRES_DB" \
		-tAc "SELECT COUNT(*) FROM feature_log;"'

k8s-ports:
	@echo "Starting Kubernetes port forwards..."
	kubectl port-forward deployment/grafana 3000:3000 > /tmp/grafana-port.log 2>&1 & echo $$! > /tmp/grafana-port.pid
	kubectl port-forward deployment/prometheus 9090:9090 > /tmp/prometheus-port.log 2>&1 & echo $$! > /tmp/prometheus-port.pid
	kubectl port-forward deployment/jaeger 16686:16686 > /tmp/jaeger-port.log 2>&1 & echo $$! > /tmp/jaeger-port.pid
	kubectl port-forward deployment/sentinel-api 8000:8000 > /tmp/sentinel-api-port.log 2>&1 & echo $$! > /tmp/sentinel-api-port.pid
	kubectl port-forward service/loki 3100:3100 > /tmp/loki-port.log 2>&1 & echo $$! > /tmp/loki-port.pid
	@echo ""
	@echo "Port forwards started:"
	@echo "  Grafana:      http://localhost:3000"
	@echo "  Prometheus:   http://localhost:9090"
	@echo "  Jaeger:       http://localhost:16686"
	@echo "  Sentinel API: http://localhost:8000"
	@echo "  Loki:         http://localhost:3100"
	
k8s-ports-stop:
	@echo "Stopping Kubernetes port forwards..."
	@kill `cat /tmp/grafana-port.pid` 2>/dev/null || true
	@kill `cat /tmp/prometheus-port.pid` 2>/dev/null || true
	@kill `cat /tmp/jaeger-port.pid` 2>/dev/null || true
	@kill `cat /tmp/sentinel-api-port.pid` 2>/dev/null || true
	@rm -f \
		/tmp/grafana-port.pid \
		/tmp/prometheus-port.pid \
		/tmp/jaeger-port.pid \
		/tmp/sentinel-api-port.pid
	@echo "Port forwards stopped."