
"""Verify the Worker initializes its preprocessor once."""

from unittest.mock import Mock, patch

from sentinel.consumers.worker import run_worker


def test_worker_reuses_preprocessor_across_messages() -> None:
    """Create the adapter once and reuse it for every message."""

    preprocessor = Mock()

    rabbitmq_connection = Mock()
    channel = rabbitmq_connection.channel.return_value

    def deliver_messages() -> None:
        callback = channel.basic_consume.call_args.kwargs[
            "on_message_callback"
        ]

        for delivery_tag in (41, 42):
            method = Mock()
            method.delivery_tag = delivery_tag

            callback(
                channel,
                method,
                Mock(),
                b"message",
            )

    channel.start_consuming.side_effect = deliver_messages

    with (
        patch(
            "sentinel.consumers.worker.load_active_schema_versions",
            return_value=frozenset({"v1"}),
        ),
        patch(
            "sentinel.consumers.worker.create_preprocessor",
            return_value=preprocessor,
        ) as create_preprocessor,
        patch(
            "sentinel.consumers.worker.create_redis_client",
        ),
        patch(
            "sentinel.consumers.worker.PostgresWriter",
        ),
        patch(
            "sentinel.consumers.worker.is_auto_inference_enabled",
            return_value=False,
        ),
        patch(
            "sentinel.consumers.worker.create_rabbitmq_connection",
            return_value=rabbitmq_connection,
        ),
        patch(
            "sentinel.consumers.worker.declare_rabbitmq_topology",
        ),
        patch(
            "sentinel.consumers.worker.process_message",
        ) as process_message,
    ):
        run_worker()

    create_preprocessor.assert_called_once_with()

    assert process_message.call_count == 2

    for call in process_message.call_args_list:
        assert call.kwargs["preprocessor"] is preprocessor

    channel.basic_consume.assert_called_once()
