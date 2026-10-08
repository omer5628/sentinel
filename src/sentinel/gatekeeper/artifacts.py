from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelArtifactResolver(Protocol):
    """Resolve an immutable model reference to a local artifact."""

    def resolve(
        self,
        model_reference: str,
    ) -> str:
        """Return the local artifact path for one model."""

        ...