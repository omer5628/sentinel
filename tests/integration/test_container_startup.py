import base64
import json
import os
import time
from io import BytesIO
from typing import cast
from uuid import uuid4

import httpx
import pika
import pytest
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from PIL import Image, ImageDraw


DEFAULT_NAMESPACE = "sentinel-dev"
DEFAULT_API_DEPLOYMENT = "sentinel-api"
DEFAULT_RABBITMQ_HOST = (
    "rabbitmq.sentinel-dev.svc.cluster.local"
)
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_SECRET_NAME = "sentinel-service-secrets"

QUEUE_NAME = "video_stream"

POD_START_TIMEOUT_SECONDS = 180
HEALTH_TIMEOUT_SECONDS = 120
PREDICTION_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2


def load_kubernetes_configuration() -> None:
    """Load Kubernetes configuration inside or outside the cluster."""

    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()


def decode_secret_value(
    secret: client.V1Secret,
    key: str,
) -> str:
    """Decode one Kubernetes Secret value."""

    if secret.data is None or key not in secret.data:
        raise AssertionError(
            f"Required secret key '{key}' is missing."
        )

    return base64.b64decode(
        secret.data[key]
    ).decode("utf-8")


def create_test_image() -> bytes:
    """Create a valid 28x28 grayscale PNG image."""

    image = Image.new(
        mode="L",
        size=(28, 28),
        color=0,
    )

    draw = ImageDraw.Draw(image)

    draw.line(
        [(7, 5), (20, 5), (13, 23)],
        fill=255,
        width=3,
    )

    buffer = BytesIO()

    image.save(
        buffer,
        format="PNG",
    )

    return buffer.getvalue()


def build_message(
    image_id: str,
    image_bytes: bytes,
) -> bytes:
    """Build a valid Sentinel v1 image message."""

    event_id = str(uuid4())

    message = {
        "schema_version": "v1",
        "event_id": event_id,
        "image_id": image_id,
        "timestamp": time.time(),
        "image_format": "png",
        "image_base64": base64.b64encode(
            image_bytes
        ).decode("ascii"),
    }

    return json.dumps(message).encode("utf-8")


def build_test_pod(
    apps_api: client.AppsV1Api,
    namespace: str,
    image_name: str,
    pod_name: str,
) -> client.V1Pod:
    """Build a temporary API Pod from the dev deployment settings."""

    deployment = cast(
        client.V1Deployment,
        apps_api.read_namespaced_deployment(
            name=DEFAULT_API_DEPLOYMENT,
            namespace=namespace,
        ),
    )

    if (
        deployment.spec is None
        or deployment.spec.template.spec is None
    ):
        raise AssertionError(
            "Sentinel API deployment has no Pod specification."
        )

    pod_spec = deployment.spec.template.spec

    if not pod_spec.containers:
        raise AssertionError(
            "Sentinel API deployment has no containers."
        )

    source_container = pod_spec.containers[0]

    test_container = client.V1Container(
        name="sentinel-api",
        image=image_name,
        image_pull_policy="Always",
        command=source_container.command,
        args=source_container.args,
        env=source_container.env,
        env_from=source_container.env_from,
        ports=source_container.ports,
        resources=source_container.resources,
        security_context=source_container.security_context,
        volume_mounts=source_container.volume_mounts,
        working_dir=source_container.working_dir,
    )

    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            labels={
                "app.kubernetes.io/name": (
                    "sentinel-api-integration"
                ),
                "sentinel.integration-test": "true",
            },
        ),
        spec=client.V1PodSpec(
            containers=[test_container],
            restart_policy="Never",
            affinity=pod_spec.affinity,
            node_selector=pod_spec.node_selector,
            tolerations=pod_spec.tolerations,
            image_pull_secrets=pod_spec.image_pull_secrets,
            service_account_name=(
                pod_spec.service_account_name
            ),
            security_context=pod_spec.security_context,
            volumes=pod_spec.volumes,
            dns_policy=pod_spec.dns_policy,
            dns_config=pod_spec.dns_config,
        ),
    )


def wait_for_pod_ip(
    core_api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
) -> str:
    """Wait until the temporary Pod is running and has an IP."""

    deadline = (
        time.monotonic()
        + POD_START_TIMEOUT_SECONDS
    )

    while time.monotonic() < deadline:
        pod = cast(
            client.V1Pod,
            core_api.read_namespaced_pod(
                name=pod_name,
                namespace=namespace,
            ),
        )

        if pod.status is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        phase = pod.status.phase

        if phase == "Failed":
            raise AssertionError(
                "Integration API Pod entered Failed state."
            )

        if (
            phase == "Running"
            and pod.status.pod_ip
        ):
            return pod.status.pod_ip

        time.sleep(POLL_INTERVAL_SECONDS)

    raise AssertionError(
        "Timed out waiting for integration API Pod."
    )


def wait_for_health(
    pod_ip: str,
) -> None:
    """Wait until the temporary API reports healthy."""

    health_url = (
        f"http://{pod_ip}:8000/health"
    )

    deadline = (
        time.monotonic()
        + HEALTH_TIMEOUT_SECONDS
    )

    with httpx.Client(
        timeout=3.0
    ) as http_client:
        while time.monotonic() < deadline:
            try:
                response = http_client.get(
                    health_url
                )

                if response.status_code == 200:
                    assert response.json() == {
                        "status": "healthy"
                    }

                    return

            except httpx.HTTPError:
                pass

            time.sleep(
                POLL_INTERVAL_SECONDS
            )

    raise AssertionError(
        "Timed out waiting for /health to return 200."
    )


def publish_image(
    core_api: client.CoreV1Api,
    namespace: str,
    image_id: str,
    image_bytes: bytes,
) -> None:
    """Publish one real PNG image to Sentinel RabbitMQ."""

    secret_name = os.getenv(
        "INTEGRATION_SECRET_NAME",
        DEFAULT_SECRET_NAME,
    )

    secret = cast(
        client.V1Secret,
        core_api.read_namespaced_secret(
            name=secret_name,
            namespace=namespace,
        ),
    )

    username = decode_secret_value(
        secret,
        "RABBITMQ_USERNAME",
    )

    password = decode_secret_value(
        secret,
        "RABBITMQ_PASSWORD",
    )

    rabbitmq_host = os.getenv(
        "INTEGRATION_RABBITMQ_HOST",
        DEFAULT_RABBITMQ_HOST,
    )

    rabbitmq_port = int(
        os.getenv(
            "INTEGRATION_RABBITMQ_PORT",
            str(DEFAULT_RABBITMQ_PORT),
        )
    )

    credentials = pika.PlainCredentials(
        username=username,
        password=password,
    )

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=rabbitmq_host,
            port=rabbitmq_port,
            credentials=credentials,
            heartbeat=30,
            blocked_connection_timeout=30,
            connection_attempts=5,
            retry_delay=2,
        )
    )

    try:
        channel = connection.channel()

        channel.queue_declare(
            queue=QUEUE_NAME,
            passive=True,
        )

        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=build_message(
                image_id=image_id,
                image_bytes=image_bytes,
            ),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    finally:
        connection.close()


def wait_for_prediction(
    pod_ip: str,
    image_id: str,
) -> dict[str, object]:
    """Wait until the Worker processes the image and prediction succeeds."""

    prediction_url = (
        f"http://{pod_ip}:8000/predict/{image_id}"
    )

    deadline = (
        time.monotonic()
        + PREDICTION_TIMEOUT_SECONDS
    )

    with httpx.Client(
        timeout=5.0
    ) as http_client:
        while time.monotonic() < deadline:
            response = http_client.post(
                prediction_url
            )

            if response.status_code == 200:
                payload = response.json()

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise AssertionError(
                        "Prediction response is not a JSON object."
                    )

                return payload

            if response.status_code not in {
                404,
                503,
            }:
                raise AssertionError(
                    "Unexpected prediction response: "
                    f"{response.status_code} "
                    f"{response.text}"
                )

            time.sleep(
                POLL_INTERVAL_SECONDS
            )

    raise AssertionError(
        "Timed out waiting for a successful prediction."
    )


def delete_test_pod(
    core_api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
) -> None:
    """Delete the temporary integration Pod."""

    try:
        core_api.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            grace_period_seconds=0,
            propagation_policy="Background",
        )

    except ApiException as error:
        if error.status != 404:
            raise


def test_container_startup() -> None:
    """Verify the built API image through the real Sentinel data path."""

    image_name = os.getenv(
        "INTEGRATION_API_IMAGE"
    )

    if not image_name:
        pytest.skip(
            "INTEGRATION_API_IMAGE is not set."
        )

    namespace = os.getenv(
        "INTEGRATION_NAMESPACE",
        DEFAULT_NAMESPACE,
    )

    load_kubernetes_configuration()

    core_api = client.CoreV1Api()
    apps_api = client.AppsV1Api()

    pod_name = (
        f"sentinel-api-integration-"
        f"{uuid4().hex[:8]}"
    )

    pod = build_test_pod(
        apps_api=apps_api,
        namespace=namespace,
        image_name=image_name,
        pod_name=pod_name,
    )

    core_api.create_namespaced_pod(
        namespace=namespace,
        body=pod,
    )

    try:
        pod_ip = wait_for_pod_ip(
            core_api=core_api,
            namespace=namespace,
            pod_name=pod_name,
        )

        wait_for_health(
            pod_ip=pod_ip,
        )

        image_id = (
            f"integration-{uuid4()}"
        )

        image_bytes = (
            create_test_image()
        )

        publish_image(
            core_api=core_api,
            namespace=namespace,
            image_id=image_id,
            image_bytes=image_bytes,
        )

        payload = wait_for_prediction(
            pod_ip=pod_ip,
            image_id=image_id,
        )

        assert (
            payload["image_id"]
            == image_id
        )

        predicted_class = payload[
            "predicted_class"
        ]

        assert isinstance(
            predicted_class,
            int,
        )

        assert (
            0
            <= predicted_class
            <= 9
        )

        predicted_label = payload[
            "predicted_label"
        ]

        assert isinstance(
            predicted_label,
            str,
        )

        assert predicted_label

        confidence = payload[
            "confidence"
        ]

        assert isinstance(
            confidence,
            int | float,
        )

        assert (
            0.0
            <= confidence
            <= 1.0
        )

        assert (
            payload["model_version"]
            == "v1"
        )

    except Exception:
        try:
            logs = (
                core_api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=100,
                )
            )

            print(
                "\n=== Integration API logs ==="
            )

            print(logs)

        except ApiException:
            pass

        raise

    finally:
        delete_test_pod(
            core_api=core_api,
            namespace=namespace,
            pod_name=pod_name,
        )