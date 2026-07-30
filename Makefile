.PHONY: \
	help \
	check lint type-check test \
	compose-up compose-build compose-down compose-restart compose-logs \
	producer-local worker-local api-local \
	k8s-status k8s-worker-logs k8s-api-logs \
	k8s-rabbitmq-forward producer-k8s \
	k8s-postgres-count

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
	@echo "Kubernetes:"
	@echo "  make k8s-status              Show Sentinel Kubernetes resources"
	@echo "  make k8s-worker-logs         Follow Kubernetes worker logs"
	@echo "  make k8s-api-logs            Follow Kubernetes API logs"
	@echo "  make k8s-rabbitmq-forward    Forward localhost:5673 to RabbitMQ"
	@echo "  make producer-k8s            Send producer data to Kubernetes RabbitMQ"
	@echo "  make k8s-postgres-count      Count rows in feature_log"

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