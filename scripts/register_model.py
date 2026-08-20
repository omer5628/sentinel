import argparse
from pathlib import Path

from clearml import OutputModel, Task


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        choices=["v1", "v2"],
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    version = args.version

    model_path = Path(f"artifacts/model-{version}.pt").resolve()

    if not model_path.exists():
        raise FileNotFoundError(f"Model file was not found: {model_path}")

    task = Task.init(
        project_name="Sentinel",
        task_name=f"register-model-{version}-for-k8s",
        task_type=Task.TaskTypes.inference,
        output_uri=True,
        reuse_last_task_id=False,
    )

    print(f"Task output URI: {task.output_uri}")

    model = OutputModel(
        task=task,
        name="sentinel-mnist-torchscript",
        tags=[version, "k8s-serving"],
    )

    uploaded_uri = model.update_weights(
        weights_filename=str(model_path),
        async_enable=False,
        auto_delete_file=False,
    )

    print(f"Uploaded URI: {uploaded_uri}")
    print(f"ClearML model URL: {model.url}")
    print(f"ClearML model ID: {model.id}")
    print(f"Model {version} upload completed successfully.")

    task.close()


if __name__ == "__main__":
    main()