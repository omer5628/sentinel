import sys

import yaml


TARGET_DEPLOYMENTS = {
    "clearml-serving-inference",
    "clearml-serving-triton",
}

SECRET_NAME = "clearml-serving-credentials"

SECRET_KEYS = {
    "CLEARML_API_ACCESS_KEY",
    "CLEARML_API_SECRET_KEY",
}


def patch_deployment(document: dict) -> None:
    if document.get("kind") != "Deployment":
        return

    metadata = document.get("metadata", {})
    if metadata.get("name") not in TARGET_DEPLOYMENTS:
        return

    containers = (
        document.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )

    for container in containers:
        for env_item in container.get("env", []):
            name = env_item.get("name")

            if name not in SECRET_KEYS:
                continue

            env_item.pop("value", None)
            env_item["valueFrom"] = {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": name,
                }
            }


documents = list(yaml.safe_load_all(sys.stdin))

for document in documents:
    if isinstance(document, dict):
        patch_deployment(document)

yaml.safe_dump_all(
    documents,
    sys.stdout,
    sort_keys=False,
)
