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
'''
        }
    }

    options {
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    stages {
        stage('Test') {
            steps {
                sh 'uv sync --frozen'
                sh 'uv run pytest'
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
                        rm -f sentinel-api.tar sentinel-worker.tar

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
            '''
        }
    }
}