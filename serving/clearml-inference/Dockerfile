FROM allegroai/clearml-serving-inference:1.3.0

RUN python - <<'PY'
from pathlib import Path


path = Path(
    "/root/clearml/clearml_serving/"
    "serving/preprocess_service.py"
)

content = path.read_text()

old = (
    'request.model_name = "{}/{}".format('
    'self.model_endpoint.serving_url, '
    'self.model_endpoint.version).strip("/")'
)

new = (
    'request.model_name = "{}_{}".format('
    'self.model_endpoint.serving_url, '
    'self.model_endpoint.version).strip("/")'
)

if old not in content:
    raise RuntimeError(
        "Expected Triton model-name code was not found."
    )

path.write_text(
    content.replace(
        old,
        new,
        1,
    )
)

print("Patched Triton model-name separator.")
PY