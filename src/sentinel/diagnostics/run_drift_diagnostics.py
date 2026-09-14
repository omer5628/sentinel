import argparse

from sentinel.diagnostics.kernel_explainer import (
    KernelShapConfig,
    print_kernel_shap_result,
    run_kernel_shap,
)
from sentinel.diagnostics.shap_diagnostics import (
    DEFAULT_BACKGROUND_SAMPLE_SIZE,
    DEFAULT_DRIFT_SAMPLE_SIZE,
    DEFAULT_LOOKBACK_MINUTES,
    DatabaseConfig,
    SamplingConfig,
    load_drift_sampling_result,
    print_sampling_summary,
)
from sentinel.diagnostics.triton_adapter import (
    TritonBatchPredictor,
    TritonDiagnosticsConfig,
)


def parse_arguments() -> argparse.Namespace:
    """Parse drift diagnostic command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run Sentinel SHAP diagnostics for "
            "a prediction-distribution drift alert."
        )
    )

    parser.add_argument(
        "--alert-class",
        type=int,
        required=True,
        help="Class reported by the drift alert.",
    )

    parser.add_argument(
        "--drift-sample-size",
        type=int,
        default=DEFAULT_DRIFT_SAMPLE_SIZE,
        help=(
            "Maximum number of distinct recent "
            "drift samples."
        ),
    )

    parser.add_argument(
        "--background-sample-size",
        type=int,
        default=DEFAULT_BACKGROUND_SAMPLE_SIZE,
        help=(
            "Maximum number of historical "
            "background samples."
        ),
    )

    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=DEFAULT_LOOKBACK_MINUTES,
        help=(
            "Drift window measured backward "
            "from the latest prediction."
        ),
    )

    return parser.parse_args()


def run_diagnostics(
    alert_class: int,
    drift_sample_size: int,
    background_sample_size: int,
    lookback_minutes: int,
) -> None:
    """Run the complete drift diagnostic workflow."""

    database_config = (
        DatabaseConfig.from_environment()
    )

    sampling_config = SamplingConfig(
        alert_class=alert_class,
        drift_sample_size=drift_sample_size,
        background_sample_size=(
            background_sample_size
        ),
        lookback_minutes=lookback_minutes,
    )

    sampling_result = (
        load_drift_sampling_result(
            database_config=database_config,
            sampling_config=sampling_config,
        )
    )

    print(
        "=== Drift Sampling ==="
    )

    print_sampling_summary(
        sampling_result
    )

    triton_config = (
        TritonDiagnosticsConfig.from_environment()
    )

    predictor = TritonBatchPredictor(
        triton_config
    )

    try:
        if not predictor.is_ready():
            raise RuntimeError(
                "Triton or the configured model "
                "is not ready."
            )

        shap_config = (
            KernelShapConfig.from_environment()
        )

        print(
            "=== SHAP Configuration ==="
        )

        print(
            f"triton_url={triton_config.url}"
        )

        print(
            "triton_model="
            f"{triton_config.model_name}"
        )

        print(
            "triton_model_version="
            f"{triton_config.model_version}"
        )

        print(
            "shap_nsamples="
            f"{shap_config.nsamples}"
        )

        print(
            "shap_top_features="
            f"{shap_config.top_feature_count}"
        )

        result = run_kernel_shap(
            predictor=predictor,
            background_matrix=(
                sampling_result.background.matrix
            ),
            drift_matrix=(
                sampling_result.drift.matrix
            ),
            alert_class=(
                sampling_result.alert_class
            ),
            sample_shape=(
                triton_config.sample_shape
            ),
            config=shap_config,
        )

    finally:
        predictor.close()

    print(
        "=== Top SHAP Contributors ==="
    )

    print_kernel_shap_result(
        result
    )


def main() -> None:
    """Run Sentinel drift diagnostics."""

    arguments = parse_arguments()

    run_diagnostics(
        alert_class=arguments.alert_class,
        drift_sample_size=(
            arguments.drift_sample_size
        ),
        background_sample_size=(
            arguments.background_sample_size
        ),
        lookback_minutes=(
            arguments.lookback_minutes
        ),
    )


if __name__ == "__main__":
    main()