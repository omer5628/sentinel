#!/usr/bin/env python3
"""Pin Sentinel's first-party container image references without overwriting other edits.

Usage:
  python3 scripts/sentinel_pin_images.py --dry-run
  python3 scripts/sentinel_pin_images.py --apply
  python3 scripts/sentinel_pin_images.py --verify

Only known chart values, raw manifests, Dockerfiles, and two optional vendored
chart references are modified. The Jenkins Python 3.11 build agent is untouched.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import re
import shutil
import sys
import tempfile

IMAGE_TAGS = {
    "prom/prometheus": "v3.10.0",
    "prom/alertmanager": "v0.28.1",
    "grafana/grafana": "13.0.10-ubuntu",
    "grafana/loki": "3.5.12",
    "grafana/promtail": "3.5",
    "jaegertracing/all-in-one": "1.71.0",
}

HELM_SECTIONS = {
    "prometheus": ("prom/prometheus", "v3.10.0"),
    "alertmanager": ("prom/alertmanager", "v0.28.1"),
    "grafana": ("grafana/grafana", "13.0.10-ubuntu"),
    "loki": ("grafana/loki", "3.5.12"),
    "promtail": ("grafana/promtail", "3.5"),
    "jaeger": ("jaegertracing/all-in-one", "1.71.0"),
}

RAW_PATHS = (
    "k8s/raw/04-observability/prometheus-deployment.yaml",
    "k8s/raw/04-observability/grafana-deployment.yaml",
    "k8s/raw/04-observability/loki-statefulset.yaml",
    "k8s/raw/04-observability/promtail-daemonset.yaml",
    "k8s/raw/04-observability/jaeger-deployment.yaml",
)
VENDOR_RENDERER = 'external/helm-charts/clearml-serving/charts/grafana/values.yaml'
VENDOR_BUSYBOX_TEST = 'external/helm-charts/clearml-serving/charts/prometheus/charts/alertmanager/templates/tests/test-connection.yaml'

DOCKERFILES = (
    "Dockerfile.api",
    "Dockerfile.worker",
    "Dockerfile.train",
    "Dockerfile.validator",
)
UV_IMAGE = "ghcr.io/astral-sh/uv:python3.10-alpine"


class MigrationError(Exception):
    pass


def section_bounds(text: str, name: str) -> tuple[int, int]:
    matches = list(re.finditer(rf"(?m)^{re.escape(name)}:\s*(?:#.*)?$", text))
    if len(matches) != 1:
        raise MigrationError(f"Expected one top-level Helm section '{name}', found {len(matches)}")
    start = matches[0].end()
    following = re.search(r"(?m)^\S[^\n]*:\s*(?:#.*)?$", text[start:])
    end = start + following.start() if following else len(text)
    return start, end


def patch_helm(text: str) -> str:
    for section, (repository, tag) in HELM_SECTIONS.items():
        start, end = section_bounds(text, section)
        block = text[start:end]
        if len(re.findall(rf"(?m)^\s+repository:\s*{re.escape(repository)}\s*$", block)) != 1:
            raise MigrationError(f"Unexpected repository in Helm '{section}' section")
        # This chart has exactly one image/tag in each observability section.
        tag_re = re.compile(r'(?m)^(\s{4}tag:\s*)(["\']?)([^"\'\s#]+)(["\']?)(\s*(?:#.*)?)$')
        matches = list(tag_re.finditer(block))
        if len(matches) != 1:
            raise MigrationError(f"Expected one image tag in Helm '{section}', found {len(matches)}")
        existing = matches[0].group(3)
        allowed_tags = {"latest", tag}
        if section == "alertmanager":
            allowed_tags.add("v0.29.1")  # One-time migration from the previous mistaken tag.
        if existing not in allowed_tags:
            raise MigrationError(f"Unexpected image tag for '{section}': {existing!r}; edit manually")
        def replace(match: re.Match[str]) -> str:
            return f'{match.group(1)}"{tag}"{match.group(5)}'
        block = tag_re.sub(replace, block, count=1)
        text = text[:start] + block + text[end:]
    return text


def patch_raw(text: str, path: str) -> str:
    found = 0
    for repository, tag in IMAGE_TAGS.items():
        regex = re.compile(rf"(?m)^(\s*image:\s*)([\"']?){re.escape(repository)}:(latest|{re.escape(tag)})([\"']?)(\s*(?:#.*)?)$")
        matches = list(regex.finditer(text))
        if matches:
            if len(matches) != 1:
                raise MigrationError(f"Multiple image refs for {repository} in {path}")
            text = regex.sub(lambda m: f"{m.group(1)}{m.group(2)}{repository}:{tag}{m.group(4)}{m.group(5)}", text, count=1)
            found += 1
    if found != 1:
        raise MigrationError(f"Expected one observability image in {path}, found {found}")
    return text


def patch_dockerfile(text: str, path: str) -> str:
    # Existing upgraded Dockerfiles expose this argument; older checkouts may use direct FROM/COPY.
    if 'ARG UV_TOOL_IMAGE=' in text:
        arg_re = re.compile(r'(?m)^(ARG UV_TOOL_IMAGE=)(\S+)$')
        matches = arg_re.findall(text)
        if len(matches) != 1 or matches[0][1] not in {"ghcr.io/astral-sh/uv:latest", UV_IMAGE}:
            raise MigrationError(f"Unrecognized UV_TOOL_IMAGE value in {path}")
        text = arg_re.sub(lambda m: m.group(1) + UV_IMAGE, text, count=1)
    else:
        if "ghcr.io/astral-sh/uv:latest" not in text and UV_IMAGE not in text:
            raise MigrationError(f"No known uv image reference in {path}")
        text = text.replace("ghcr.io/astral-sh/uv:latest", UV_IMAGE)

    # Derived uv image stores the executables at /usr/local/bin, unlike distroless /uv.
    text = text.replace(
        'COPY --from=uv-source /uv /uvx /bin/',
        'COPY --from=uv-source /usr/local/bin/uv /usr/local/bin/uvx /bin/',
    ).replace(
        'COPY --from=uv-source /uv /usr/local/bin/uv',
        'COPY --from=uv-source /usr/local/bin/uv /usr/local/bin/uv',
    ).replace(
        'COPY --from=' + UV_IMAGE + ' /uv /usr/local/bin/uv',
        'COPY --from=' + UV_IMAGE + ' /usr/local/bin/uv /usr/local/bin/uv',
    ).replace(
        'COPY --from=' + UV_IMAGE + ' /uv /uvx /bin/',
        'COPY --from=' + UV_IMAGE + ' /usr/local/bin/uv /usr/local/bin/uvx /bin/',
    )
    if ' /uv ' in text or ' /uvx ' in text:
        raise MigrationError(f"Old uv binary path remained in {path}")
    if UV_IMAGE not in text:
        raise MigrationError(f"New uv image missing from {path}")
    return text


def patch_vendor_renderer(text: str) -> str:
    start, end = section_bounds(text, 'imageRenderer')
    block = text[start:end]
    if 'repository: grafana/grafana-image-renderer' not in block:
        raise MigrationError('Unexpected image-renderer repository in vendored Grafana values')
    pattern = re.compile(r'(?m)^(    tag:\s*)(["\']?)(latest|v5\.9\.1)(["\']?)(\s*(?:#.*)?)$')
    if len(pattern.findall(block)) != 1:
        raise MigrationError('Expected one Grafana image-renderer tag')
    block = pattern.sub(lambda m: f'{m.group(1)}"v5.9.1"{m.group(5)}', block, count=1)
    return text[:start] + block + text[end:]


def patch_vendor_busybox_test(text: str) -> str:
    pattern = re.compile(r'(?m)^(\s*image:\s*)(["\']?)(busybox|busybox:1\.31\.1)(["\']?)(\s*(?:#.*)?)$')
    if len(pattern.findall(text)) != 1:
        raise MigrationError('Expected one busybox Helm test image')
    return pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}busybox:1.31.1{m.group(4)}{m.group(5)}', text, count=1)


def plan(root: Path) -> dict[Path, str]:
    values = root / 'charts/sentinel/values.yaml'
    paths = [values, *(root / path for path in RAW_PATHS), *(root / path for path in DOCKERFILES), root / VENDOR_RENDERER, root / VENDOR_BUSYBOX_TEST]
    if not values.is_file() or not (root / 'pyproject.toml').is_file():
        raise MigrationError(f"Not a Sentinel project root: {root}")
    updates: dict[Path, str] = {}
    for path in paths:
        if not path.is_file():
            # Legacy raw manifests can be absent from more recent working copies.
            if path.relative_to(root).as_posix() in (*RAW_PATHS, VENDOR_RENDERER, VENDOR_BUSYBOX_TEST):
                print(f"SKIP optional legacy manifest: {path.relative_to(root)}")
                continue
            raise MigrationError(f"Required file not found: {path}")
        original = path.read_text(encoding='utf-8')
        if path == values:
            updated = patch_helm(original)
        elif path.name.startswith('Dockerfile.'):
            updated = patch_dockerfile(original, str(path.relative_to(root)))
        elif path.relative_to(root).as_posix() == VENDOR_RENDERER:
            updated = patch_vendor_renderer(original)
        elif path.relative_to(root).as_posix() == VENDOR_BUSYBOX_TEST:
            updated = patch_vendor_busybox_test(original)
        else:
            updated = patch_raw(original, str(path.relative_to(root)))
        updates[path] = updated
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--verify', action='store_true')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        updates = plan(root)
        changed = [(p, updated) for p, updated in updates.items() if p.read_text(encoding='utf-8') != updated]
        for path, _ in changed:
            print('CHANGE:', path.relative_to(root))
        print(f'Checked {len(updates)} files; changes required: {len(changed)}')
        if args.verify:
            if changed:
                raise MigrationError('Versions are not all pinned; run --apply first')
            print('PASS: first-party image references are pinned as requested')
            return 0
        if args.dry_run:
            print('DRY RUN: no project file was changed')
            return 0
        if not changed:
            print('PASS: already up to date')
            return 0
        backup = root.parent / (
            'sentinel-image-pins-backup-'
            + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        )
        backup.mkdir(mode=0o700)
        for path, _ in changed:
            dest = backup / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        print('BACKUP:', backup)
        done: list[Path] = []
        try:
            for path, updated in changed:
                with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=path.parent,
                    prefix='.sentinel-image-', delete=False
                ) as f:
                    tmp = Path(f.name)
                    f.write(updated)
                try:
                    tmp.chmod(path.stat().st_mode)
                    tmp.replace(path)
                    done.append(path)
                finally:
                    tmp.unlink(missing_ok=True)
        except Exception:
            for path in done:
                shutil.copy2(backup / path.relative_to(root), path)
            raise
        # Re-evaluate patches for idempotence.
        if any(p.read_text(encoding='utf-8') != candidate for p, candidate in plan(root).items()):
            raise MigrationError('Post-apply validation failed; restore from backup')
        print('PASS: image references pinned; Jenkins Python 3.11 agent unchanged')
        return 0
    except (MigrationError, OSError) as exc:
        print('FAIL:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
