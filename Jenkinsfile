
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
      image: sentinel-jenkins-python:py311-uv0.13.4
      imagePullPolicy: Never
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
      imagePullPolicy: Never
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
      imagePullPolicy: Never
      command:
        - sh
        - -c
      args:
        - sleep infinity
      volumeMounts:
        - name: trivy-cache
          mountPath: /cache
        - name: trivy-db
          mountPath: /cache/db
          subPath: db
          readOnly: true
      resources:
        requests:
          cpu: 250m
          memory: 512Mi
        limits:
          cpu: "2"
          memory: 3Gi

    - name: skopeo
      image: quay.io/skopeo/stable:latest
      imagePullPolicy: Never
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
      imagePullPolicy: Never
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
      imagePullPolicy: Never
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
    - name: trivy-cache
      emptyDir: {}
    - name: trivy-db
      persistentVolumeClaim:
        claimName: sentinel-trivy-db
        readOnly: true
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
        choice(
            name: 'IMAGE_DELIVERY_MODE',
            choices: ['archive_only', 'dockerhub'],
            description: 'archive_only: archive without publishing or deploying; dockerhub: legacy CI/CD.'
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
                        --cache-dir /cache \
                        --skip-db-update \
                        --skip-java-db-update \
                        --skip-check-update \
                        --skip-version-check \
                        --offline-scan \
                        --input sentinel-api.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --cache-dir /cache \
                        --skip-db-update \
                        --skip-java-db-update \
                        --skip-check-update \
                        --skip-version-check \
                        --offline-scan \
                        --input sentinel-worker.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --cache-dir /cache \
                        --skip-db-update \
                        --skip-java-db-update \
                        --skip-check-update \
                        --skip-version-check \
                        --offline-scan \
                        --input sentinel-train.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml

                        trivy image \
                        --cache-dir /cache \
                        --skip-db-update \
                        --skip-java-db-update \
                        --skip-check-update \
                        --skip-version-check \
                        --offline-scan \
                        --input sentinel-validator.tar \
                        --scanners vuln \
                        --severity CRITICAL \
                        --exit-code 1 \
                        --ignorefile .trivyignore.yaml
                    '''
                }
            }
        }

        stage('Archive Images') {
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'archive_only'
                }
            }
            steps {
                archiveArtifacts(
                    artifacts: 'sentinel-api.tar,sentinel-worker.tar,sentinel-train.tar,sentinel-validator.tar',
                    fingerprint: true
                )
            }
        }

        stage('Push Images') {
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
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
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
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
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
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
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
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

        stage('Promote to Prod?') {
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
            steps {
                input(
                    message: 'Deploy to Production?',
                    ok: 'Yes, Deploy'
                )
            }
        }

        stage('Deploy Prod') {
            when {
                expression {
                    params.IMAGE_DELIVERY_MODE == 'dockerhub'
                }
            }
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
