# ADR-0017: Adopt Security and Compliance Gates

* **Status:** Accepted
* **Date:** 2026-08-25
* **Decision Owners:** Sentinel MLOps Platform Team

## Context

Project Sentinel is moving from manual deployment toward a governed CI/CD pipeline.

A successful build should not be considered deployable only because the application tests pass.

The pipeline must also detect:

* Dependencies using forbidden software licenses.
* Critical vulnerabilities in container images.
* Security exceptions that have expired.

These checks must run before deployment so security issues are detected early in the software delivery process.

This follows the **Shift Left Security** approach.

## Decision

Project Sentinel will introduce two mandatory CI/CD security gates:

1. License compliance checking.
2. Container vulnerability scanning with Trivy.

Any failed security gate will stop the pipeline before deployment.

## License Compliance Gate

A custom Python script is used to inspect the locked project dependencies and their installed package metadata.

The script reads package names and versions from:

```text
uv.lock
```

License information is obtained from Python package metadata such as:

* `License-Expression`
* `License`
* License classifiers

The current project policy rejects dependencies licensed under the GNU General Public License (GPL).

When a forbidden GPL dependency is detected, the script returns a non-zero exit code.

Example:

```text
GPL dependency detected
        |
        v
Exit code 1
        |
        v
Pipeline stopped
```

Automated tests verify that:

* GPL dependencies are rejected.
* Allowed licenses such as BSD are not rejected as false positives.

## Container Vulnerability Gate

Project Sentinel uses **Trivy** to scan container images for known vulnerabilities.

The CI/CD policy blocks images containing vulnerabilities with:

```text
Severity: CRITICAL
```

The security gate uses:

```bash
trivy image \
  --scanners vuln \
  --severity CRITICAL \
  --exit-code 1 \
  --ignorefile .trivyignore.yaml \
  IMAGE
```

If an unapproved critical vulnerability is found, Trivy returns exit code `1` and deployment is blocked.

## Temporary Security Exceptions

During validation, the Sentinel API image contained critical vulnerabilities inherited from its Debian base image.

No fixed package versions were available at the time of the scan.

Instead of disabling vulnerability enforcement globally, Sentinel uses targeted temporary exceptions in:

```text
.trivyignore.yaml
```

Each exception contains:

* The exact CVE identifier.
* A documented reason.
* An expiration date.

This allows known risks to be reviewed temporarily while ensuring new critical vulnerabilities continue to fail the pipeline.

Broad options such as:

```text
--ignore-unfixed
```

are intentionally avoided because they could silently suppress future vulnerabilities.

## Alternatives Considered

### Grype

Grype is a container vulnerability scanner from Anchore.

It provides similar vulnerability scanning capabilities, but Trivy was selected because it provides a simple CLI, broad ecosystem support, and straightforward integration into CI/CD pipelines.

### Snyk

Snyk provides dependency and container security scanning with strong reporting and remediation features.

However, it introduces an external service and additional account/platform dependencies.

Trivy can run locally and inside the self-hosted Jenkins environment.

### No Automated Security Gate

Security reviews could be performed manually before deployment.

This was rejected because manual checks are inconsistent, easy to forget, and do not provide an enforceable pipeline control.

## Consequences

### Positive

* Critical vulnerabilities block deployments automatically.
* Forbidden licenses are detected before deployment.
* Security policy becomes repeatable and auditable.
* Temporary vulnerability exceptions are explicit and time-limited.
* New critical vulnerabilities cannot be silently ignored.
* Security checks can run automatically inside Jenkins.

### Negative

* Vulnerability databases may occasionally contain false positives.
* Base image vulnerabilities may block deployment even when application code is unaffected.
* Security exceptions require ongoing review.
* License metadata quality depends on upstream package metadata.

## Security Principle

Project Sentinel follows a fail-closed approach for security gates.

The default behavior is:

```text
Unknown new CRITICAL vulnerability
              |
              v
            FAIL
```

Exceptions must be explicit rather than disabling the security control globally.

## Validation

License compliance:

```bash
uv run --frozen python scripts/check_licenses.py
```

Expected result:

```text
PASSED
Exit code 0
```

License policy tests:

```bash
uv run pytest tests/test_license_gate.py -v
```

Expected result:

```text
2 passed
```

Trivy must fail on an unapproved critical vulnerability:

```bash
trivy image \
  --scanners vuln \
  --severity CRITICAL \
  --exit-code 1 \
  sentinel-api:security-test
```

Expected result when critical vulnerabilities exist:

```text
Exit code 1
```

Trivy with approved temporary waivers:

```bash
trivy image \
  --scanners vuln \
  --severity CRITICAL \
  --exit-code 1 \
  --ignorefile .trivyignore.yaml \
  sentinel-api:security-test
```

Expected result:

```text
Exit code 0
```
