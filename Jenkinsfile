pipeline {
    agent {
        kubernetes {
            defaultContainer 'python'
            yaml '''
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: jenkins-deployer

  containers:
    - name: python
      image: ghcr.io/astral-sh/uv:python3.11-bookworm-slim
      command:
        - cat
      tty: true
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: "2"
          memory: 3Gi

    - name: buildkit
      image: moby/buildkit:v0.32.2-rootless
      command:
        - sh
        - -c
      args:
        - sleep infinity
      env:
        - name: BUILDKITD_FLAGS
          value: --oci-worker-no-process-sandbox
      resources:
        requests:
          cpu: "1"
          memory: 2Gi
        limits:
          cpu: "4"
          memory: 8Gi
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile:
          type: Unconfined
        appArmorProfile:
          type: Unconfined

    - name: trivy
      image: aquasec/trivy:0.74.0
      command:
        - sh
        - -c
      args:
        - sleep infinity
      resources:
        requests:
          cpu: 250m
          memory: 512Mi
        limits:
          cpu: "2"
          memory: 3Gi

    - name: skopeo
      image: quay.io/skopeo/stable:latest
      command:
        - sh
        - -c
      args:
        - sleep infinity
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: "1"
          memory: 1Gi

    - name: helm
      image: alpine/helm:3.18.6
      command:
        - sh
        - -c
      args:
        - sleep infinity
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi

    - name: kubectl
      image: alpine/k8s:1.35.8
      command:
        - sh
        - -c
      args:
        - sleep infinity
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi
      volumeMounts:
        - name: alertmanager-jenkins-credentials
          mountPath: /run/secrets/sentinel-alertmanager
          readOnly: true

  volumes:
    - name: alertmanager-jenkins-credentials
      secret:
        secretName: sentinel-alertmanager-credentials
        items:
          - key: password
            path: password
'''
        }
    }

    parameters {
        booleanParam(
            name: 'DEPLOY_CLEARML_SERVING_E2E',
            defaultValue: false,
            description: 'Deploy isolated ClearML Serving E2E to sentinel-dev (not Production).'
        )
        booleanParam(
            name: 'BOOTSTRAP_E2E_DATABASE',
            defaultValue: false,
            description: 'Initialize isolated PostgreSQL E2E database in sentinel-dev only.'
        )
    }

    options {
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    stages {
        stage('Test') {
            steps {
                sh 'uv sync --frozen --group validation'
                sh 'uv run --frozen --group validation pytest'
            }
        }

        stage('API Documentation') {
            steps {
                sh '''
                    uv run --frozen python \
                      -m sentinel.serving.api \
                      --export-openapi \
                      > openapi.json

                    test -s openapi.json

                    uv run --frozen python \
                      -m json.tool \
                      openapi.json \
                      > /dev/null
                '''

                archiveArtifacts(
                    artifacts: 'openapi.json',
                    fingerprint: true
                )
            }
        }

        stage('Compliance') {
            steps {
                sh 'uv run --frozen python scripts/check_licenses.py'
            }
        }

        stage('Build Images') {
            steps {
                container('buildkit') {
                    sh '''
                        rm -f \
                          sentinel-api.tar \
                          sentinel-worker.tar \
                          sentinel-train.tar \
                          sentinel-validator.tar

                        buildctl-daemonless.sh build \
                        --frontend dockerfile.v0 \
                        --local context=. \
                        --local dockerfile=. \
                        --opt filename=Dockerfile.api \
                        --output type=docker,name=omer5628/sentinel-api:${BUILD_NUMBER},dest=sentinel-api.tar

                        buildctl-daemonless.sh build \
                        --frontend dockerfile.v0 \
                        --local context=. \
                        --local dockerfile=. \
                        --opt filename=Dockerfile.worker \
                        --output type=docker,name=omer5628/sentinel-worker:${BUILD_NUMBER},dest=sentinel-worker.tar

                        buildctl-daemonless.sh build \
                        --frontend dockerfile.v0 \
                        --local context=. \
                        --local dockerfile=. \
                        --opt filename=Dockerfile.train \
                        --output type=docker,name=omer5628/sentinel-train:${BUILD_NUMBER},dest=sentinel-train.tar

                        buildctl-daemonless.sh build \
                        --frontend dockerfile.v0 \
                        --local context=. \
                        --local dockerfile=. \
                        --opt filename=Dockerfile.validator \
                        --output type=docker,name=omer5628/sentinel-validator:${BUILD_NUMBER},dest=sentinel-validator.tar
                    '''
                }
            }
        }

        stage('Security Scan') {
            steps {
                container('trivy') {
                    sh '''
                        trivy image \
                        --input sentinel-api.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --input sentinel-worker.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --input sentinel-train.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --input sentinel-validator.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml
                    '''
                }
            }
        }

        stage('Push Images') {
            steps {
                container('skopeo') {
                    withCredentials([
                        usernamePassword(
                            credentialsId: 'dockerhub-credentials',
                            usernameVariable: 'DOCKERHUB_USER',
                            passwordVariable: 'DOCKERHUB_TOKEN'
                        )
                    ]) {
                        sh '''
                            echo "$DOCKERHUB_TOKEN" | \
                            skopeo login \
                            --username "$DOCKERHUB_USER" \
                            --password-stdin \
                            docker.io

                            skopeo copy \
                            docker-archive:sentinel-api.tar \
                            docker://docker.io/omer5628/sentinel-api:${BUILD_NUMBER}

                            skopeo copy \
                            docker-archive:sentinel-worker.tar \
                            docker://docker.io/omer5628/sentinel-worker:${BUILD_NUMBER}

                            skopeo copy \
                            docker-archive:sentinel-train.tar \
                            docker://docker.io/omer5628/sentinel-train:${BUILD_NUMBER}

                            skopeo copy \
                            docker-archive:sentinel-validator.tar \
                            docker://docker.io/omer5628/sentinel-validator:${BUILD_NUMBER}
                        '''
                    }
                }
            }
        }

        stage('Integration Test') {
            steps {
                sh '''
                    INTEGRATION_API_IMAGE="omer5628/sentinel-api:${BUILD_NUMBER}" \
                    INTEGRATION_NAMESPACE="sentinel-dev" \
                    uv run --frozen pytest \
                      tests/integration/test_container_startup.py \
                      -v
                '''
            }
        }

        stage('Sync AlertManager Credentials') {
            steps {
                container('kubectl') {
                    sh '''
                        set -eu

                        SECRET_NAME="sentinel-alertmanager-credentials"
                        TARGET_NAMESPACE="sentinel-dev"
                        PASSWORD_FILE="/run/secrets/sentinel-alertmanager/password"

                        test -s "$PASSWORD_FILE"

                        if kubectl get secret \
                          "$SECRET_NAME" \
                          --namespace "$TARGET_NAMESPACE" \
                          > /dev/null 2>&1
                        then
                          kubectl create secret generic \
                            "$SECRET_NAME" \
                            --namespace "$TARGET_NAMESPACE" \
                            --from-file=password="$PASSWORD_FILE" \
                            --dry-run=client \
                            -o yaml \
                            | kubectl replace \
                                --namespace "$TARGET_NAMESPACE" \
                                -f -
                        else
                          kubectl create secret generic \
                            "$SECRET_NAME" \
                            --namespace "$TARGET_NAMESPACE" \
                            --from-file=password="$PASSWORD_FILE"
                        fi

                        echo "AlertManager Jenkins credentials synchronized."
                    '''
                }
            }
        }

        stage('Deploy Dev') {
            steps {
                container('helm') {
                    sh '''
                        helm upgrade --install sentinel \
                          charts/sentinel \
                          --namespace sentinel-dev \
                          -f charts/sentinel/values-dev.yaml \
                          --set-string api.image.tag=${BUILD_NUMBER} \
                          --set-string worker.image.tag=${BUILD_NUMBER} \
                          --wait \
                          --timeout 10m
                    '''
                }
            }
        }

        stage('Bootstrap E2E Database') {
            when {
                expression { params.BOOTSTRAP_E2E_DATABASE == true }
            }
            steps {
                container('helm') {
                    sh '''
                        set -eu

                        # Render only E2E resources; never upgrade the Sentinel release.
                        helm template sentinel charts/sentinel \
                          --namespace sentinel-dev \
                          -f charts/sentinel/values-dev.yaml \
                          -f charts/sentinel/values-e2e.yaml \
                          --show-only templates/retraining-e2e-db-configmap.yaml \
                          --set retraining.databaseBootstrap.enabled=true \
                          > e2e-db-configmap.yaml

                        helm template sentinel charts/sentinel \
                          --namespace sentinel-dev \
                          -f charts/sentinel/values-dev.yaml \
                          -f charts/sentinel/values-e2e.yaml \
                          --show-only templates/retraining-e2e-db-bootstrap-job.yaml \
                          --set retraining.databaseBootstrap.enabled=true \
                          > e2e-db-bootstrap-job.yaml
                    '''
                }

                container('python') {
                    sh '''
                        set -eu
                        uv run --frozen python - <<'PY'
from pathlib import Path
import yaml


def read_manifest(path):
    documents = list(yaml.safe_load_all(Path(path).read_text()))
    assert len(documents) == 1 and documents[0], f"Unexpected document count: {path}"
    return documents[0]


configmap = read_manifest("e2e-db-configmap.yaml")
job = read_manifest("e2e-db-bootstrap-job.yaml")

assert configmap["kind"] == "ConfigMap"
assert configmap["metadata"]["name"] == "sentinel-retraining-e2e-db"
assert configmap["data"] == {
    "POSTGRES_HOST": "postgres-0.postgres-headless.sentinel-dev.svc.cluster.local",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "sentinel_e2e",
}

assert job["kind"] == "Job"
assert job["metadata"]["name"] == "sentinel-e2e-db-bootstrap"
pod = job["spec"]["template"]["spec"]
assert pod["automountServiceAccountToken"] is False
assert pod["restartPolicy"] == "Never"
assert len(pod["containers"]) == 1
container = pod["containers"][0]
env = {item["name"]: item for item in container["env"]}
assert env["E2E_DB_NAME"]["value"] == "sentinel_e2e"
assert env["E2E_DB_USER"]["value"] == "sentinel_e2e_user"
assert env["POSTGRES_HOST"]["value"] == configmap["data"]["POSTGRES_HOST"]
assert env["K8S_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"
assert env["POSTGRES_ADMIN_USER"]["valueFrom"]["secretKeyRef"] == {
    "name": "sentinel-service-secrets", "key": "POSTGRES_USER",
}
assert env["POSTGRES_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
    "name": "sentinel-service-secrets", "key": "POSTGRES_PASSWORD",
}
assert env["E2E_DB_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
    "name": "sentinel-retraining-e2e-db-credentials", "key": "POSTGRES_PASSWORD",
}
assert len(pod["volumes"]) == 1
assert pod["volumes"][0]["configMap"]["name"] == "postgres-init-sql"
assert "REVOKE " not in " ".join(container["args"]).upper(), (
    "Bootstrap must not change existing database grants"
)
print("PASS: E2E bootstrap manifests and credential references verified")
PY
                    '''
                }

                container('kubectl') {
                    sh '''
                        set -eu
                        NAMESPACE="sentinel-dev"
                        JOB_NAME="sentinel-e2e-db-bootstrap"
                        CONFIGMAP_NAME="sentinel-retraining-e2e-db"

                        # Require the existing schema ConfigMap and admin Secret.
                        kubectl get configmap postgres-init-sql \
                          --namespace "$NAMESPACE" --output name > /dev/null
                        kubectl get secret sentinel-service-secrets \
                          --namespace "$NAMESPACE" --output name > /dev/null

                        # Preserve an existing password on subsequent runs.
                        sh scripts/create_e2e_db_credentials.sh \
                          "$NAMESPACE" \
                          sentinel-retraining-e2e-db-credentials \
                          sentinel_e2e_user

                        # Update/create only the dedicated E2E ConfigMap.
                        if kubectl get configmap "$CONFIGMAP_NAME" \
                          --namespace "$NAMESPACE" > /dev/null 2>&1; then
                            kubectl replace --namespace "$NAMESPACE" \
                              -f e2e-db-configmap.yaml
                        else
                            kubectl create --namespace "$NAMESPACE" \
                              -f e2e-db-configmap.yaml
                        fi

                        # Recreate a completed/failed Job, never replace an active Job.
                        if kubectl get job "$JOB_NAME" \
                          --namespace "$NAMESPACE" > /dev/null 2>&1; then
                            ACTIVE="$(kubectl get job "$JOB_NAME" \
                              --namespace "$NAMESPACE" \
                              -o jsonpath='{.status.active}')"
                            if [ -n "$ACTIVE" ] && [ "$ACTIVE" != "0" ]; then
                                echo "ERROR: E2E bootstrap Job is already running." >&2
                                exit 1
                            fi
                            kubectl delete job "$JOB_NAME" \
                              --namespace "$NAMESPACE" --wait=true --timeout=120s
                        fi

                        kubectl create --namespace "$NAMESPACE" \
                          -f e2e-db-bootstrap-job.yaml

                        if ! kubectl wait --namespace "$NAMESPACE" \
                          --for=condition=complete \
                          --timeout=300s "job/$JOB_NAME"; then
                            kubectl logs --namespace "$NAMESPACE" \
                              "job/$JOB_NAME" --all-containers=true || true
                            echo "ERROR: E2E database bootstrap did not complete." >&2
                            exit 1
                        fi

                        kubectl logs --namespace "$NAMESPACE" \
                          "job/$JOB_NAME" --all-containers=true
                        echo "E2E PostgreSQL bootstrap verified as completed."
                    '''
                }
            }
        }

        stage('Deploy ClearML Serving E2E') {
            when {
                expression { params.DEPLOY_CLEARML_SERVING_E2E == true }
            }
            steps {
                container('python') {
                    sh '''
                        set -eu
                        uv run --frozen python -c '
from pathlib import Path
import yaml

e2e = yaml.safe_load(Path("charts/vendor/clearml-serving/values-e2e.yaml").read_text())
dev = yaml.safe_load(Path("charts/sentinel/values-dev.yaml").read_text())
config = e2e["clearml"]
task_id = str(config.get("servingTaskId", "")).strip()
live_task_id = str(dev["retraining"]["canaryPromotion"]["servingTaskId"]).strip()
assert task_id and task_id != live_task_id, "E2E Serving Task ID must differ from the live Serving Task ID"
assert config.get("existingSecret") == "clearml-retraining-credentials", "Expected E2E ClearML Kubernetes Secret"
assert not config.get("apiAccessKey") and not config.get("apiSecretKey"), "Do not put ClearML credentials in Helm values"
assert e2e["clearml_serving_triton"]["enabled"] is True, "Triton must be enabled for the E2E serving test"
assert e2e["clearml_serving_statistics"]["enabled"] is False, "Statistics must be disabled for isolated E2E"
print("E2E configuration safety checks passed.")
'
                    '''
                }

                container('kubectl') {
                    sh '''
                        set -eu
                        kubectl get secret clearml-retraining-credentials \
                          --namespace sentinel-dev \
                          --output name > /dev/null
                    '''
                }

                container('helm') {
                    sh '''
                        set -eu
                        helm lint charts/vendor/clearml-serving \
                          -f charts/vendor/clearml-serving/values-e2e.yaml

                        helm template clearml-serving-e2e \
                          charts/vendor/clearml-serving \
                          --namespace sentinel-dev \
                          -f charts/vendor/clearml-serving/values-e2e.yaml \
                          > clearml-serving-e2e-render.yaml
                    '''
                }

                container('python') {
                    sh '''
                        set -eu
                        uv run --frozen python -c '
from pathlib import Path
import yaml

values = yaml.safe_load(Path("charts/vendor/clearml-serving/values-e2e.yaml").read_text())
task_id = str(values["clearml"]["servingTaskId"])
secret = str(values["clearml"]["existingSecret"])
documents = [doc for doc in yaml.safe_load_all(Path("clearml-serving-e2e-render.yaml").read_text()) if doc]
expected = {
    ("Deployment", "clearml-serving-e2e-inference"),
    ("Deployment", "clearml-serving-e2e-triton"),
    ("Service", "clearml-serving-e2e-inference"),
    ("Service", "clearml-serving-e2e-triton"),
}
actual = {(doc["kind"], doc["metadata"]["name"]) for doc in documents}
assert actual == expected, f"Unexpected E2E Kubernetes resources: {actual ^ expected}"
for doc in documents:
    if doc["kind"] != "Deployment":
        continue
    env = doc["spec"]["template"]["spec"]["containers"][0]["env"]
    for key in ("CLEARML_API_ACCESS_KEY", "CLEARML_API_SECRET_KEY"):
        found = [item for item in env if item["name"] == key]
        assert len(found) == 1, f"Expected exactly one {key}"
        ref = found[0].get("valueFrom", {}).get("secretKeyRef", {})
        assert ref == {"name": secret, "key": key}, f"Incorrect Kubernetes Secret reference for {key}"
        assert "value" not in found[0], f"Plaintext credential field detected: {key}"
    serving = [item for item in env if item["name"] == "CLEARML_SERVING_TASK_ID"]
    assert len(serving) == 1 and serving[0].get("value") == task_id, "E2E Serving Task mismatch"
print("E2E Helm render safety checks passed.")
'
                    '''
                }

                container('helm') {
                    sh '''
                        set -eu
                        helm upgrade --install clearml-serving-e2e \
                          charts/vendor/clearml-serving \
                          --namespace sentinel-dev \
                          -f charts/vendor/clearml-serving/values-e2e.yaml \
                          --atomic \
                          --wait \
                          --timeout 10m
                    '''
                }
            }
        }

        stage('Promote to Prod?') {
            steps {
                input(
                    message: 'Deploy to Production?',
                    ok: 'Yes, Deploy'
                )
            }
        }

        stage('Deploy Prod') {
            steps {
                container('helm') {
                    sh '''
                        helm upgrade --install sentinel \
                          charts/sentinel \
                          --namespace sentinel-prod \
                          -f charts/sentinel/values-prod.yaml \
                          --set-string api.image.tag=${BUILD_NUMBER} \
                          --set-string worker.image.tag=${BUILD_NUMBER} \
                          --wait \
                          --timeout 10m
                    '''
                }
            }
        }
    }

    post {
        always {
            sh '''
                rm -f sentinel-api.tar
                rm -f sentinel-worker.tar
                rm -f sentinel-train.tar
                rm -f sentinel-validator.tar
                rm -f openapi.json
            '''
        }
    }
}