from pathlib import Path

import matplotlib.pyplot as plt


TARGET_RPS = [
    500,
    1000,
    1500,
    2000,
]

FASTAPI_RPS = [
    498.82,
    866.19,
    823.36,
    837.87,
]

TRITON_RPS = [
    493.92,
    993.27,
    1485.91,
    1353.82,
]

OUTPUT_PATH = Path(
    "artifacts/serving-throughput-comparison.png"
)


def main() -> None:
    """Create the Phase 3.5 serving throughput comparison chart."""

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    figure, axis = plt.subplots(
        figsize=(10, 6)
    )

    axis.plot(
        TARGET_RPS,
        FASTAPI_RPS,
        marker="o",
        label="Python FastAPI + TorchScript",
    )

    axis.plot(
        TARGET_RPS,
        TRITON_RPS,
        marker="o",
        label=(
            "ClearML Serving / Triton "
            "+ Dynamic Batching"
        ),
    )

    axis.plot(
        TARGET_RPS,
        TARGET_RPS,
        linestyle="--",
        label="Target throughput",
    )

    axis.set_title(
        "Phase 3.5 Serving Throughput Comparison"
    )
    axis.set_xlabel(
        "Target Requests Per Second"
    )
    axis.set_ylabel(
        "Achieved Requests Per Second"
    )

    axis.legend()
    axis.grid(
        visible=True,
        alpha=0.3,
    )

    figure.tight_layout()

    figure.savefig(
        OUTPUT_PATH,
        dpi=150,
    )

    print(
        f"Chart saved to: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()