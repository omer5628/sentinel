from pathlib import Path

from clearml import OutputModel, Task


def main() -> None:
    model_path = Path("artifacts/model-v2.pt").resolve()

    if not model_path.exists():
        raise FileNotFoundError(f"Model file was not found: {model_path}")

    task = Task.init(
        project_name="Sentinel",
        task_name="register-model-for-k8s",
        task_type=Task.TaskTypes.inference,
        output_uri=True,
        reuse_last_task_id=False,
    )

    print(f"Task output URI: {task.output_uri}")

    model = OutputModel(
        task=task,
        name="sentinel-mnist-torchscript",
        tags=["v2", "k8s-serving"],
    )

    uploaded_uri = model.update_weights(
        weights_filename=str(model_path),
        async_enable=False,
    )

    print(f"Uploaded URI: {uploaded_uri}")
    print(f"ClearML model URL: {model.url}")
    print(f"ClearML model ID: {model.id}")
    print("Model upload completed successfully.")


if __name__ == "__main__":
    main()