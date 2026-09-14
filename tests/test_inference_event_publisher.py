from typing import cast

import pytest

import sentinel.serving.inference_events as inference_events
from sentinel.schema.v1 import InferenceEventV1
from sentinel.serving.inference_events import (
    INFERENCE_QUEUE_NAME,
    InferenceEventPublisher,
)


class FakeEvent:
    def model_dump_json(self) -> str:
        return '{"event":"test"}'


class FakeChannel:
    def __init__(
        self,
        fail_publish: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.is_open = True
        self.fail_publish = fail_publish
        self.fail_close = fail_close
        self.publish_calls = 0
        self.close_calls = 0
        self.declarations: list[
            tuple[str, bool]
        ] = []

    def queue_declare(
        self,
        *,
        queue: str,
        durable: bool,
    ) -> None:
        self.declarations.append(
            (
                queue,
                durable,
            )
        )

    def basic_publish(
        self,
        **kwargs: object,
    ) -> None:
        del kwargs

        self.publish_calls += 1

        if self.fail_publish:
            self.fail_publish = False

            raise ConnectionResetError(
                104,
                "Connection reset by peer",
            )

    def close(self) -> None:
        self.close_calls += 1

        if self.fail_close:
            raise ConnectionResetError(
                104,
                "Connection reset during close",
            )

        self.is_open = False


class FakeConnection:
    def __init__(
        self,
        channel: FakeChannel,
        fail_close: bool = False,
    ) -> None:
        self.is_open = True
        self._channel = channel
        self.fail_close = fail_close
        self.close_calls = 0

    def channel(self) -> FakeChannel:
        return self._channel

    def close(self) -> None:
        self.close_calls += 1

        if self.fail_close:
            raise ConnectionResetError(
                104,
                "Connection reset during close",
            )

        self.is_open = False


def test_publish_reconnects_after_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_channel = FakeChannel(
        fail_publish=True,
    )

    second_channel = FakeChannel()

    first_connection = FakeConnection(
        first_channel
    )

    second_connection = FakeConnection(
        second_channel
    )

    connections = iter(
        [
            first_connection,
            second_connection,
        ]
    )

    connection_count = 0

    def create_connection() -> FakeConnection:
        nonlocal connection_count

        connection_count += 1

        return next(
            connections
        )

    monkeypatch.setattr(
        inference_events,
        "create_rabbitmq_connection",
        create_connection,
    )

    publisher = InferenceEventPublisher()

    event = cast(
        InferenceEventV1,
        FakeEvent(),
    )

    publisher.publish(
        event
    )

    assert connection_count == 2

    assert first_channel.publish_calls == 1
    assert second_channel.publish_calls == 1

    assert first_connection.is_open is False
    assert second_connection.is_open is True

    assert publisher.connection is second_connection
    assert publisher.channel is second_channel

    assert first_channel.declarations == [
        (
            INFERENCE_QUEUE_NAME,
            True,
        )
    ]

    assert second_channel.declarations == [
        (
            INFERENCE_QUEUE_NAME,
            True,
        )
    ]


def test_publish_reconnects_when_cleanup_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_channel = FakeChannel(
        fail_publish=True,
        fail_close=True,
    )

    second_channel = FakeChannel()

    first_connection = FakeConnection(
        first_channel,
        fail_close=True,
    )

    second_connection = FakeConnection(
        second_channel
    )

    connections = iter(
        [
            first_connection,
            second_connection,
        ]
    )

    connection_count = 0

    def create_connection() -> FakeConnection:
        nonlocal connection_count

        connection_count += 1

        return next(
            connections
        )

    monkeypatch.setattr(
        inference_events,
        "create_rabbitmq_connection",
        create_connection,
    )

    publisher = InferenceEventPublisher()

    event = cast(
        InferenceEventV1,
        FakeEvent(),
    )

    publisher.publish(
        event
    )

    assert connection_count == 2

    assert first_channel.publish_calls == 1
    assert first_channel.close_calls == 1
    assert first_connection.close_calls == 1

    assert second_channel.publish_calls == 1

    assert publisher.connection is second_connection
    assert publisher.channel is second_channel
