
"""Regression tests for configurable Worker storage."""

from unittest.mock import Mock

import torch

from sentinel.consumers.worker_config import WorkerConfig
from sentinel.consumers.worker_storage import (
    FEATURE_TTL_SECONDS,
    tensor_to_json,
    write_to_redis,
)


def test_default_feature_ttl() -> None:
    """Preserve the original Redis TTL and binary format."""

    redis_client = Mock()
    tensor = torch.tensor([1.0, 2.0], dtype=torch.float32)

    write_to_redis(
        redis_client=redis_client,
        image_id="test-image",
        tensor=tensor,
    )

    assert FEATURE_TTL_SECONDS == 3600

    redis_client.setex.assert_called_once_with(
        name="feat:test-image",
        time=3600,
        value=tensor.numpy().tobytes(),
    )


def test_custom_feature_ttl() -> None:
    """Use the configured TTL without changing the binary format."""

    redis_client = Mock()
    tensor = torch.tensor([1.0, 2.0], dtype=torch.float32)

    config = WorkerConfig(feature_ttl_seconds=7200)

    write_to_redis(
        redis_client=redis_client,
        image_id="test-image",
        tensor=tensor,
        config=config,
    )

    redis_client.setex.assert_called_once_with(
        name="feat:test-image",
        time=7200,
        value=tensor.numpy().tobytes(),
    )


def test_custom_config_does_not_change_defaults() -> None:
    """Config overrides must not mutate the original defaults."""

    redis_client = Mock()
    tensor = torch.tensor([1.0], dtype=torch.float32)

    write_to_redis(
        redis_client,
        "first-image",
        tensor,
        config=WorkerConfig(feature_ttl_seconds=7200),
    )

    write_to_redis(
        redis_client,
        "second-image",
        tensor,
    )

    assert redis_client.setex.call_args.kwargs["time"] == 3600


def test_tensor_json_serialization_unchanged() -> None:
    """Keep PostgreSQL feature serialization backward compatible."""

    tensor = torch.tensor([[1.0, 2.0]], dtype=torch.float32)

    assert tensor_to_json(tensor) == "[[1.0, 2.0]]"
