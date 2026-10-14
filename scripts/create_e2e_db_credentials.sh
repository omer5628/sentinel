#!/bin/sh
set -eu

# Create isolated E2E PostgreSQL credentials.
# Existing credentials must never be rotated automatically.

namespace="${1:?Namespace is required}"
secret_name="${2:?Secret name is required}"
db_user="${3:?Database username is required}"

if [ "$namespace" != "sentinel-dev" ]; then
    echo "ERROR: E2E credentials are restricted to sentinel-dev." >&2
    exit 1
fi

if [ "$secret_name" = "sentinel-service-secrets" ] ||
   [ "$db_user" = "sentinel" ]; then
    echo "ERROR: Refusing to use production database credentials." >&2
    exit 1
fi

existing="$(kubectl get secret "$secret_name" \
    -n "$namespace" \
    --ignore-not-found \
    -o name)"

if [ -n "$existing" ]; then
    existing_user="$(kubectl get secret "$secret_name" \
        -n "$namespace" \
        -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)"

    if [ "$existing_user" != "$db_user" ]; then
        echo "ERROR: Existing secret has a different database user." >&2
        exit 1
    fi

    password_data="$(kubectl get secret "$secret_name" \
        -n "$namespace" \
        -o jsonpath='{.data.POSTGRES_PASSWORD}')"

    if [ -z "$password_data" ]; then
        echo "ERROR: Existing secret has no database password." >&2
        exit 1
    fi

    echo "E2E database credentials already exist. Preserving them."
    exit 0
fi

umask 077
password_file="$(mktemp)"
trap 'rm -f "$password_file"' EXIT HUP INT TERM

# Generate 32 cryptographically random bytes as a hex password.
od -An -N32 -tx1 /dev/urandom \
    | tr -d ' \n' > "$password_file"

if [ "$(wc -c < "$password_file" | tr -d ' ')" -ne 64 ]; then
    echo "ERROR: Password generation failed." >&2
    exit 1
fi

kubectl create secret generic "$secret_name" \
    -n "$namespace" \
    --from-literal="POSTGRES_USER=$db_user" \
    --from-file="POSTGRES_PASSWORD=$password_file"

echo "E2E database credentials created successfully."