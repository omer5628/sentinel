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
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile:
          type: Unconfined
        appArmorProfile:
          type: Unconfined
'''
        }
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

        stage('Build API Image') {
            steps {
                container('buildkit') {
                    sh '''
                        rm -f sentinel-api.oci.tar

                        buildctl-daemonless.sh build \
                          --frontend dockerfile.v0 \
                          --local context=. \
                          --local dockerfile=. \
                          --opt filename=Dockerfile.api \
                          --output type=oci,dest=sentinel-api.oci.tar
                    '''
                }
            }
        }
    }
}