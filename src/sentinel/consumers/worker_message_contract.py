
"""Validate and decode incoming Worker messages."""

import base64
import binascii
import json
from typing import Any

from pydantic import ValidationError

from sentinel.schema.v1 import ImageMessageV1


SUPPORTED_SCHEMA_VERSION = "v1"


def extract_schema_version(body: bytes) -> str:
    """Extract the schema version from an incoming JSON message."""

    try:
        message: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Message body is not valid JSON.") from error

    if not isinstance(message, dict):
        raise ValueError("Message body must contain a JSON object.")

    schema_version = message.get("schema_version")

    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError(
            "Message must contain a non-empty string field named "
            "'schema_version'."
        )

    return schema_version


def deserialize_message(
    body: bytes,
    active_schema_versions: frozenset[str],
) -> ImageMessageV1:
    """Select the schema version and validate an incoming message."""

    schema_version = extract_schema_version(body)

    if schema_version not in active_schema_versions:
        raise ValueError(
            f"Schema version '{schema_version}' is not active in "
            f"the Schema Registry."
        )

    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Schema version '{schema_version}' is active but is not "
            "supported by this Worker version."
        )

    try:
        return ImageMessageV1.model_validate_json(body)
    except ValidationError as error:
        raise ValueError(
            f"Message failed the ImageMessageV1 contract: {error}"
        ) from error


def decode_image(message: ImageMessageV1) -> bytes:
    """Decode a Base64 image from a validated RabbitMQ message."""

    try:
        return base64.b64decode(
            message.image_base64,
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError("The image is not valid Base64.") from error
