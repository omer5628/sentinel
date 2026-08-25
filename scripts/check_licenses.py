from __future__ import annotations

import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = PROJECT_ROOT / "uv.lock"

GPL_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z])GPL(?:[-v ]?(?:1|2|3)(?:\.\d)?)?"
    r"(?:-(?:only|or-later))?(?![A-Za-z])",
    re.IGNORECASE,
)

GPL_NAME_PATTERN = re.compile(
    r"GNU General Public License",
    re.IGNORECASE,
)


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_locked_packages() -> dict[str, set[str]]:
    with LOCK_FILE.open("rb") as file:
        lock_data = tomllib.load(file)

    locked_packages: dict[str, set[str]] = {}

    for package in lock_data.get("package", []):
        name = package.get("name")
        version = package.get("version")

        if not name or not version:
            continue

        normalized_name = normalize_package_name(name)
        locked_packages.setdefault(normalized_name, set()).add(str(version))

    return locked_packages


def get_license_metadata(
    dist: metadata.Distribution,
) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []

    license_expression = dist.metadata.get("License-Expression")
    if license_expression:
        values.append(("License-Expression", license_expression.strip()))

    for classifier in dist.metadata.get_all("Classifier", []):
        if classifier.startswith("License ::"):
            values.append(("Classifier", classifier.strip()))

    license_value = dist.metadata.get("License")

    if license_value:
        normalized_license = " ".join(license_value.split())

        if (
            normalized_license
            and normalized_license.upper() != "UNKNOWN"
            and len(normalized_license) <= 120
        ):
            values.append(("License", normalized_license))

    return values


def is_forbidden_gpl(source: str, value: str) -> bool:
    if source == "Classifier":
        return bool(GPL_NAME_PATTERN.search(value))

    return bool(
        GPL_NAME_PATTERN.search(value)
        or GPL_IDENTIFIER_PATTERN.search(value)
    )


def main() -> int:
    if not LOCK_FILE.exists():
        print(f"ERROR: Lock file not found: {LOCK_FILE}")
        return 2

    locked_packages = load_locked_packages()

    if not locked_packages:
        print("ERROR: No packages were found in uv.lock")
        return 2

    scanned_count = 0
    unknown_license_count = 0
    unlocked_packages: list[str] = []
    forbidden_packages: list[
        tuple[str, str, list[tuple[str, str]]]
    ] = []

    for dist in metadata.distributions():
        name = dist.metadata.get("Name")

        if not name:
            continue

        version = dist.version
        normalized_name = normalize_package_name(name)
        license_values = get_license_metadata(dist)

        scanned_count += 1

        locked_versions = locked_packages.get(normalized_name)

        if not locked_versions or version not in locked_versions:
            unlocked_packages.append(f"{name}=={version}")

        if not license_values:
            unknown_license_count += 1
            continue

        forbidden_values = [
            (source, value)
            for source, value in license_values
            if is_forbidden_gpl(source, value)
        ]

        if forbidden_values:
            forbidden_packages.append(
                (name, version, forbidden_values)
            )

    print("License compliance scan")
    print("-----------------------")
    print(f"Locked package names: {len(locked_packages)}")
    print(f"Installed packages scanned: {scanned_count}")
    print(
        "Packages without usable license metadata: "
        f"{unknown_license_count}"
    )
    print(
        "Installed packages not matching uv.lock: "
        f"{len(unlocked_packages)}"
    )

    if unlocked_packages:
        print("\nWARNING: Installed packages not matching uv.lock:")

        for package in sorted(unlocked_packages):
            print(f"  - {package}")

    if forbidden_packages:
        print("\nFAILED: GPL licensed dependencies detected:")

        for name, version, license_values in forbidden_packages:
            print(f"\n  {name}=={version}")

            for source, value in license_values:
                print(f"    {source}: {value}")

        return 1

    print("\nPASSED: No GPL licensed dependencies were detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())