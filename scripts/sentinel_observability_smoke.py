#!/usr/bin/env python3
"""Isolated Observability smoke test using Sentinel's rendered Helm config.

Run from the Sentinel project root:
    uv run --locked --group validation python scripts/sentinel_observability_smoke.py

The script pulls missing images (while the current machine has internet), then
starts temporary containers on an internal Docker network with no published
ports. It does not access or modify existing Docker/Kubernetes resources.

Uses the exact Alertmanager v0.28.1 image requested for Sentinel.
No substitute image is accepted: a missing image causes the smoke test to fail.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {
    "prometheus": "prom/prometheus:v3.10.0",
    "alertmanager": "prom/alertmanager:v0.28.1",
    "grafana": "grafana/grafana:13.0.10-ubuntu",
    "loki": "grafana/loki:3.5.12",
    "promtail": "grafana/promtail:3.5",
    "jaeger": "jaegertracing/all-in-one:1.71.0",
}
CONFIG_MAPS = {
    "prometheus-config": ("prometheus", "prometheus.yml"),
    "prometheus-drift-rules": ("prometheus/rules", "drift-rules.yml"),
    "alertmanager-config": ("alertmanager", "alertmanager.yml"),
    "loki-config": ("loki", "loki.yaml"),
    "promtail-config": ("promtail", "promtail.yaml"),
    "grafana-datasources": ("grafana/datasources", "datasources.yaml"),
    "grafana-dashboard-provider": ("grafana/dashboard-provider", "dashboards.yaml"),
    "grafana-dashboards": ("grafana/dashboards", "sentinel-observability.json"),
}

# Executed only inside the ephemeral Python probe container.
PROBE = r'''
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

active = set(os.environ["SENTINEL_TEST_SERVICES"].split(",")) - {""}
endpoints = {
    "prometheus": "http://prometheus:9090/-/ready",
    "alertmanager": "http://alertmanager:9093/-/ready",
    "grafana": "http://grafana:3000/api/health",
    "loki": "http://loki:3100/ready",
    "jaeger": "http://jaeger:16686/api/services",
}

def request(url, data=None, headers=None, timeout=4):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read()

failures = []
for service in ("prometheus", "alertmanager", "grafana", "loki", "jaeger"):
    if service not in active:
        continue
    endpoint = endpoints[service]
    last_error = "unavailable"
    for attempt in range(60):
        try:
            code, _ = request(endpoint)
            if code == 200:
                print(f"PASS: {service} HTTP readiness", flush=True)
                break
            last_error = f"HTTP {code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    else:
        print(f"FAIL: {service} did not become ready ({last_error})", flush=True)
        failures.append(service + " readiness")

if "alertmanager" in active and "alertmanager readiness" not in failures:
    try:
        alert = [{
            "labels": {"alertname": "SentinelObservabilitySmokeTest", "severity": "test"},
            "annotations": {"summary": "Disposable Alertmanager API v2 smoke test"},
        }]
        code, _ = request(
            "http://alertmanager:9093/api/v2/alerts",
            json.dumps(alert).encode(),
            {"Content-Type": "application/json"},
        )
        assert code in (200, 202), code
        for attempt in range(20):
            _, payload = request("http://alertmanager:9093/api/v2/alerts")
            stored = json.loads(payload)
            if any(
                entry.get("labels", {}).get("alertname") == "SentinelObservabilitySmokeTest"
                for entry in stored
            ):
                break
            time.sleep(0.25)
        else:
            raise AssertionError("Posted test alert did not appear in Alertmanager API v2")
        print("PASS: Alertmanager API v2 accepted and returned test alert", flush=True)
    except Exception as exc:
        failures.append("Alertmanager API v2")
        print(f"FAIL: Alertmanager API v2: {exc}", flush=True)

if "prometheus" in active and "prometheus readiness" not in failures:
    try:
        _, payload = request("http://prometheus:9090/api/v1/rules")
        body = json.loads(payload)
        names = {
            rule.get("name")
            for group in body.get("data", {}).get("groups", [])
            for rule in group.get("rules", [])
        }
        assert "SentinelPredictionDistributionDrift" in names, names
        print("PASS: Prometheus Sentinel drift alert rule loaded", flush=True)
    except Exception as exc:
        failures.append("Prometheus rules")
        print(f"FAIL: Prometheus drift rules: {exc}", flush=True)

if "grafana" in active and "grafana readiness" not in failures:
    try:
        token = base64.b64encode(b"admin:sentinel-smoke-local-test").decode("ascii")
        _, payload = request("http://grafana:3000/api/datasources", headers={"Authorization": "Basic " + token})
        names = {ds["name"] for ds in json.loads(payload)}
        assert {"Prometheus", "Loki", "Jaeger"}.issubset(names), names
        print("PASS: Grafana provisioned Prometheus/Loki/Jaeger data sources", flush=True)
    except Exception as exc:
        failures.append("Grafana data sources")
        print(f"FAIL: Grafana data sources: {exc}", flush=True)

if "loki" in active and "loki readiness" not in failures:
    try:
        body = json.dumps({"streams": [{"stream": {"job": "sentinel-observability-smoke"}, "values": [[str(time.time_ns()), "sentinel temporary log entry"]]}]}).encode()
        code, _ = request("http://loki:3100/loki/api/v1/push", body, {"Content-Type": "application/json"})
        assert code == 204, code
        print("PASS: Loki accepted log ingestion", flush=True)
    except Exception as exc:
        failures.append("Loki log ingestion")
        print(f"FAIL: Loki log ingestion: {exc}", flush=True)

if "jaeger" in active and "jaeger readiness" not in failures:
    try:
        now = time.time_ns()
        otlp = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "sentinel-observability-smoke"}}]}, "scopeSpans": [{"scope": {"name": "smoke"}, "spans": [{"traceId": "1234567890abcdef1234567890abcdef", "spanId": "1234567890abcdef", "name": "smoke-span", "kind": 1, "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000000)}]}]}]}
        code, _ = request("http://jaeger:4318/v1/traces", json.dumps(otlp).encode(), {"Content-Type": "application/json"})
        assert code in (200, 202), code
        print("PASS: Jaeger accepted OTLP/HTTP trace", flush=True)
    except Exception as exc:
        failures.append("Jaeger OTLP")
        print(f"FAIL: Jaeger OTLP ingestion: {exc}", flush=True)

if failures:
    print("FAILED CHECKS:", ", ".join(failures), flush=True)
    sys.exit(1)
print("PASS: All available service integration checks passed", flush=True)
'''


def run(args: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=timeout)


def logs(name: str) -> None:
    result = run(["docker", "logs", "--tail", "45", name], check=False)
    output = (result.stdout + result.stderr).strip()
    if output:
        print(f"--- Last logs: {name} ---\n{output}", flush=True)


def render_configs(directory: Path) -> None:
    cmd = [
        "helm", "template", "sentinel-observability-smoke", "charts/sentinel",
        "--namespace", "sentinel-dev", "-f", "charts/sentinel/values-dev.yaml",
        "--set", "alertmanager.jenkinsWebhook.enabled=false",
    ]
    result = run(cmd, timeout=45)
    configmaps = {
        doc["metadata"]["name"]: doc.get("data", {})
        for doc in yaml.safe_load_all(result.stdout)
        if isinstance(doc, dict) and doc.get("kind") == "ConfigMap"
    }
    # Ensure the smoke test uses the same Alertmanager image as Helm Dev.
    deployed_images = [
        container.get("image")
        for doc in yaml.safe_load_all(result.stdout)
        if isinstance(doc, dict) and doc.get("kind") == "Deployment"
        for container in doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if container.get("name") == "alertmanager"
    ]
    if deployed_images != [IMAGES["alertmanager"]]:
        raise RuntimeError(
            f"Helm Alertmanager image mismatch: {deployed_images!r}; "
            f"expected {IMAGES['alertmanager']}"
        )
    print("PASS: Helm deploys exact Alertmanager v0.28.1 image", flush=True)

    for name, (folder, filename) in CONFIG_MAPS.items():
        if name not in configmaps or filename not in configmaps[name]:
            raise RuntimeError(f"Missing Helm ConfigMap data: {name}/{filename}")
        dest = directory / folder / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(configmaps[name][filename], encoding="utf-8")
    print("PASS: Rendered real Sentinel Helm observability configuration", flush=True)
    print("NOTE: Jenkins webhook disabled only for the disposable Alertmanager test", flush=True)


def docker_start(
    name: str, network: str, service: str, image: str,
    options: list[str], image_args: list[str],
) -> bool:
    cmd = [
        "docker", "run", "-d", "--pull=never", "--name", name,
        "--network", network, "--network-alias", service,
        "--label", "sentinel.smoke=observability",
        *options, image, *image_args,
    ]
    result = run(cmd, check=False, timeout=60)
    if result.returncode:
        print(f"FAIL: {service} could not start: {result.stderr.strip()}", flush=True)
        return False
    print(f"STARTED: {service}", flush=True)
    return True


def image_available(image: str) -> bool:
    present = run(["docker", "image", "inspect", image], check=False, timeout=30)
    if present.returncode == 0:
        print(f"PASS: image {image} (local)", flush=True)
        return True
    print(f"PULL: {image}", flush=True)
    pulled = run(["docker", "pull", image], check=False, timeout=600)
    if pulled.returncode:
        print(f"MISSING: {image}: {pulled.stderr.strip()[-350:]}", flush=True)
        return False
    print(f"PASS: image {image}", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Disposable Sentinel observability smoke test")
    parser.add_argument(
        "--probe-image", default="sentinel-api:pinned-images-test",
        help="Preexisting local image with Python stdlib; defaults to the verified Sentinel API test image",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    test_id = f"sentinel-obs-{os.getpid()}-{secrets.token_hex(3)}"
    network = test_id
    created: list[str] = []
    failed: list[str] = []
    available: dict[str, str] = {}
    network_created = False

    # Never remove pre-existing containers, images, volumes or Kubernetes resources.
    with tempfile.TemporaryDirectory(prefix="sentinel-observability-smoke-") as temp:
        directory = Path(temp)
        try:
            print("===== PREFLIGHT =====", flush=True)
            run(["docker", "info"], timeout=20)
            render_configs(directory)
            print("===== CHECKING EXACT IMAGE TAGS =====", flush=True)
            for service, image in IMAGES.items():
                if image_available(image):
                    available[service] = image
                    continue
                failed.append(f"Image unavailable: {image}")
            # Reuse a locally built Sentinel Python runtime instead of requiring
            # the unrelated python:3.11 image to be locally tagged.
            if run(["docker", "image", "inspect", args.probe_image], check=False).returncode:
                print(f"FAIL: local Python probe image unavailable: {args.probe_image}", flush=True)
                print("HINT: run the four Docker builds from step 13.3 or pass --probe-image with an existing Python image", flush=True)
                return 1
            print(f"PASS: Python probe uses local {args.probe_image}", flush=True)
            run(["docker", "network", "create", "--internal", "--label", "sentinel.smoke=observability", network], timeout=30)
            network_created = True
            print("===== STARTING TEMPORARY SERVICES (NO HOST PORTS) =====", flush=True)
            options = {
                "prometheus": [
                    "--mount", f"type=bind,src={directory / 'prometheus'},dst=/etc/prometheus,readonly",
                    "--tmpfs", "/prometheus:rw,mode=1777",
                ],
                "alertmanager": [
                    "--mount", f"type=bind,src={directory / 'alertmanager'},dst=/etc/alertmanager,readonly",
                    "--tmpfs", "/alertmanager:rw,mode=1777",
                ],
                "loki": [
                    "--mount", f"type=bind,src={directory / 'loki'},dst=/etc/loki,readonly",
                    "--tmpfs", "/loki:rw,mode=1777",
                ],
                "grafana": [
                    "-e", "GF_SECURITY_ADMIN_USER=admin",
                    "-e", "GF_SECURITY_ADMIN_PASSWORD=sentinel-smoke-local-test",
                    "--tmpfs", "/var/lib/grafana:rw,mode=1777",
                    "--mount", f"type=bind,src={directory / 'grafana' / 'datasources'},dst=/etc/grafana/provisioning/datasources,readonly",
                    "--mount", f"type=bind,src={directory / 'grafana' / 'dashboard-provider'},dst=/etc/grafana/provisioning/dashboards,readonly",
                    "--mount", f"type=bind,src={directory / 'grafana' / 'dashboards'},dst=/var/lib/grafana/dashboards,readonly",
                ],
                "jaeger": ["-e", "COLLECTOR_OTLP_ENABLED=true"],
            }
            image_args = {
                "prometheus": ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus"],
                "alertmanager": ["--config.file=/etc/alertmanager/alertmanager.yml", "--storage.path=/alertmanager"],
                "loki": ["-config.file=/etc/loki/loki.yaml"],
            }
            running = []
            for service in ("loki", "jaeger", "prometheus", "alertmanager", "grafana"):
                if service not in available:
                    continue
                name = f"{test_id}-{service}"
                if docker_start(name, network, service, available[service], options[service], image_args.get(service, [])):
                    created.append(name)
                    running.append(service)
                else:
                    failed.append(f"Failed to start: {service}")
            if "promtail" in available:
                print("===== VALIDATING PROMTAIL KUBERNETES CONFIG SYNTAX =====", flush=True)
                cmd = [
                    "docker", "run", "--rm", "--pull=never", "--network", network,
                    "--mount", f"type=bind,src={directory / 'promtail'},dst=/etc/promtail,readonly",
                    available["promtail"],
                    "-config.file=/etc/promtail/promtail.yaml", "-check-syntax",
                ]
                result = run(cmd, check=False, timeout=60)
                if result.returncode:
                    print(f"FAIL: Promtail config syntax: {(result.stdout + result.stderr)[-1500:]}", flush=True)
                    failed.append("Promtail config syntax")
                else:
                    print("PASS: Promtail config syntax", flush=True)
                    print("NOTE: Kubernetes log discovery requires a separate cluster test", flush=True)
            if running:
                print("===== HTTP / INGESTION / PROVISIONING TESTS =====", flush=True)
                probe = [
                    "docker", "run", "--rm", "--pull=never", "--network", network,
                    "-e", f"SENTINEL_TEST_SERVICES={','.join(running)}",
                    "--entrypoint", "python", args.probe_image, "-c", PROBE,
                ]
                result = run(probe, check=False, timeout=220)
                if result.stdout:
                    print(result.stdout.rstrip(), flush=True)
                if result.returncode:
                    print(f"FAIL: Health/integration probes: {result.stderr.strip()[-1600:]}", flush=True)
                    failed.append("Health/integration probes")
                    for service in running:
                        logs(f"{test_id}-{service}")
            if failed:
                print("===== INCOMPLETE / FAILED =====", flush=True)
                for issue in failed:
                    print("FAIL:", issue, flush=True)
                return 1
            print("===== ALL OBSERVABILITY SMOKE CHECKS PASSED =====", flush=True)
            return 0
        finally:
            for name in reversed(created):
                run(["docker", "rm", "-f", name], check=False, timeout=30)
            if network_created:
                run(["docker", "network", "rm", network], check=False, timeout=30)
            print("CLEANUP: Temporary containers and internal network removed", flush=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
