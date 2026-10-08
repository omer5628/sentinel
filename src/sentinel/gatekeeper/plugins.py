from importlib import import_module
from typing import Any, cast

from sentinel.gatekeeper.artifacts import (
    ModelArtifactResolver,
)
from sentinel.gatekeeper.contracts import (
    GoldenSetAdapter,
    ModelAdapter,
)


def load_plugin_object(
    reference: str,
) -> Any:
    """Load a Python object from a module:attribute reference."""

    normalized_reference = reference.strip()

    if not normalized_reference:
        raise ValueError(
            "Plugin reference cannot be empty."
        )

    module_name, separator, attribute_name = (
        normalized_reference.partition(":")
    )

    if (
        not separator
        or not module_name.strip()
        or not attribute_name.strip()
    ):
        raise ValueError(
            "Plugin reference must use the format "
            "'module:attribute'."
        )

    try:
        module = import_module(
            module_name.strip()
        )
    except ImportError as error:
        raise ImportError(
            "Could not import plugin module: "
            f"{module_name.strip()}"
        ) from error

    try:
        return getattr(
            module,
            attribute_name.strip(),
        )
    except AttributeError as error:
        raise ImportError(
            "Plugin attribute was not found: "
            f"{normalized_reference}"
        ) from error


def load_golden_set_adapter(
    reference: str,
) -> GoldenSetAdapter:
    """Load and instantiate a golden-set adapter plugin."""

    adapter_type = load_plugin_object(
        reference
    )

    if not callable(adapter_type):
        raise TypeError(
            "Golden-set adapter plugin must be callable."
        )

    adapter = adapter_type()

    if not isinstance(
        adapter,
        GoldenSetAdapter,
    ):
        raise TypeError(
            "Loaded plugin does not implement "
            "the GoldenSetAdapter contract."
        )

    return cast(
        GoldenSetAdapter,
        adapter,
    )


def load_model_adapter(
    reference: str,
) -> ModelAdapter:
    """Load and instantiate a model adapter plugin."""

    adapter_type = load_plugin_object(
        reference
    )

    if not callable(adapter_type):
        raise TypeError(
            "Model adapter plugin must be callable."
        )

    adapter = adapter_type()

    if not isinstance(
        adapter,
        ModelAdapter,
    ):
        raise TypeError(
            "Loaded plugin does not implement "
            "the ModelAdapter contract."
        )

    return cast(
        ModelAdapter,
        adapter,
    )


def load_model_artifact_resolver(
    reference: str,
) -> ModelArtifactResolver:
    """Load and instantiate a model-artifact resolver plugin."""

    resolver_type = load_plugin_object(
        reference
    )

    if not callable(resolver_type):
        raise TypeError(
            "Model-artifact resolver plugin must be callable."
        )

    resolver = resolver_type()

    if not isinstance(
        resolver,
        ModelArtifactResolver,
    ):
        raise TypeError(
            "Loaded plugin does not implement "
            "the ModelArtifactResolver contract."
        )

    return cast(
        ModelArtifactResolver,
        resolver,
    )