
"""Create a configurable preprocessing adapter using Hydra."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

from hydra import compose, initialize_config_dir
from hydra.utils import instantiate
from torch import Tensor


Preprocessor = Callable[[bytes], Tensor]


def create_preprocessor(
    config_dir: Path | None = None,
) -> Preprocessor:
    """Load Hydra configuration and create the selected preprocessor."""

    if config_dir is None:
        config_dir = Path(
            os.getenv("SENTINEL_CONFIG_DIR", "conf")
        )

    config_dir = config_dir.resolve()

    if not config_dir.is_dir():
        raise FileNotFoundError(
            f"Hydra configuration directory not found: {config_dir}"
        )

    with initialize_config_dir(
        version_base=None,
        config_dir=str(config_dir),
    ):
        cfg = compose(config_name="config")

    preprocessor = instantiate(cfg.preprocessing)

    if not callable(preprocessor):
        raise TypeError(
            "Configured preprocessor must be callable."
        )

    return cast(Preprocessor, preprocessor)
