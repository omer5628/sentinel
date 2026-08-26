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
    }
}