from pathlib import Path

from clearml import InputModel


class ClearMLModelArtifactResolver:
    """Resolve a ClearML model ID to its local artifact."""

    def resolve(
        self,
        model_reference: str,
    ) -> str:
        """Download one ClearML model artifact and return its local path."""

        normalized_reference = (
            model_reference.strip()
        )

        if not normalized_reference:
            raise ValueError(
                "ClearML model reference cannot be empty."
            )

        model = InputModel(
            model_id=normalized_reference
        )

        local_copy = model.get_local_copy(
            raise_on_error=True
        )

        if not local_copy:
            raise FileNotFoundError(
                "ClearML model artifact could not be resolved: "
                f"{normalized_reference}"
            )

        local_path = Path(
            local_copy
        )

        if not local_path.exists():
            raise FileNotFoundError(
                "Resolved ClearML model artifact does not exist: "
                f"{local_path}"
            )

        return str(
            local_path
        )