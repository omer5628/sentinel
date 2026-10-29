"""Verify the Worker forwards runtime configuration to its components."""

from unittest.mock import Mock, patch
from uuid import UUID

from sentinel.consumers.worker import process_message, run_worker
from sentinel.consumers.worker_config import WorkerConfig


EVENT_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_run_worker_passes_runtime_configuration_to_components() -> None:
    """Load settings once and reuse them for RabbitMQ and message handling."""

    config = WorkerConfig(queue_name="configurable_stream", prefetch_count=5)
    rabbitmq_connection = Mock()
    channel = rabbitmq_connection.channel.return_value
    preprocessor = Mock()

    def deliver_message() -> None:
        callback = channel.basic_consume.call_args.kwargs[
            "on_message_callback"
        ]
        callback(channel, Mock(), Mock(), b"message")

    channel.start_consuming.side_effect = deliver_message

    with (
        patch(
            "sentinel.consumers.worker.WorkerConfig.from_environment",
            return_value=config,
        ) as load_config,
        patch(
            "sentinel.consumers.worker.load_active_schema_versions",
            return_value=frozenset({"v1"}),
        ),
        patch(
            "sentinel.consumers.worker.create_preprocessor",
            return_value=preprocessor,
        ),
        patch("sentinel.consumers.worker.create_redis_client"),
        patch("sentinel.consumers.worker.PostgresWriter"),
        patch(
            "sentinel.consumers.worker.is_auto_inference_enabled",
            return_value=False,
        ),
        patch(
            "sentinel.consumers.worker.create_rabbitmq_connection",
            return_value=rabbitmq_connection,
        ) as create_connection,
        patch(
            "sentinel.consumers.worker.declare_rabbitmq_topology"
        ) as declare_topology,
        patch(
            "sentinel.consumers.worker.process_message"
        ) as process_one_message,
    ):
        run_worker()

    load_config.assert_called_once_with()
    create_connection.assert_called_once_with(config=config)
    declare_topology.assert_called_once_with(channel, config=config)
    channel.basic_qos.assert_called_once_with(prefetch_count=5)
    assert channel.basic_consume.call_args.kwargs["queue"] == "configurable_stream"
    assert process_one_message.call_args.kwargs["config"] is config
    assert process_one_message.call_args.kwargs["preprocessor"] is preprocessor


def test_processing_passes_configuration_to_redis() -> None:
    """Pass the same runtime configuration into the storage callback."""

    config = WorkerConfig(feature_ttl_seconds=7200)
    message = Mock()
    message.event_id = EVENT_ID
    message.image_id = "image-1"
    channel = Mock()
    method = Mock(delivery_tag=42)
    preprocessor = Mock(return_value=Mock())
    redis_client = Mock()
    postgres_writer = Mock()

    with (
        patch(
            "sentinel.consumers.worker.deserialize_message",
            return_value=message,
        ),
        patch(
            "sentinel.consumers.worker.decode_image",
            return_value=b"image-bytes",
        ),
        patch(
            "sentinel.consumers.worker.write_to_redis"
        ) as write_to_redis,
    ):
        process_message(
            channel=channel,
            method=method,
            properties=Mock(),
            body=b"message",
            redis_client=redis_client,
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=None,
            preprocessor=preprocessor,
            config=config,
        )

    write_to_redis.assert_called_once_with(
        redis_client=redis_client,
        image_id="image-1",
        tensor=preprocessor.return_value,
        config=config,
    )
    channel.basic_ack.assert_called_once_with(delivery_tag=42)


def test_processing_passes_configuration_to_dead_letter_handler() -> None:
    """Preserve the invalid-message path with configured DLQ details."""

    config = WorkerConfig(dead_letter_queue="custom.dlq")
    error = ValueError("Invalid message")
    channel = Mock()
    method = Mock(delivery_tag=43)

    with (
        patch(
            "sentinel.consumers.worker.deserialize_message",
            side_effect=error,
        ),
        patch(
            "sentinel.consumers.worker.reject_invalid_message"
        ) as reject_invalid,
    ):
        process_message(
            channel=channel,
            method=method,
            properties=Mock(),
            body=b"message",
            redis_client=Mock(),
            postgres_writer=Mock(),
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=None,
            config=config,
        )

    reject_invalid.assert_called_once_with(
        channel=channel,
        delivery_tag=43,
        error=error,
        config=config,
    )
