from scripts import check_licenses


class FakeMetadata(dict[str, str]):
    def get_all(self, key: str, failobj=None):
        if key == "Classifier":
            return []
        return failobj


class FakeDistribution:
    def __init__(
        self,
        name: str,
        version: str,
        license_expression: str,
    ) -> None:
        self.version = version
        self.metadata = FakeMetadata(
            {
                "Name": name,
                "License-Expression": license_expression,
            }
        )


def test_license_gate_fails_for_gpl(monkeypatch) -> None:
    package_name = "fake-gpl-package"
    package_version = "1.0.0"

    fake_distribution = FakeDistribution(
        name=package_name,
        version=package_version,
        license_expression="GPL-3.0-only",
    )

    monkeypatch.setattr(
        check_licenses,
        "load_locked_packages",
        lambda: {package_name: {package_version}},
    )

    monkeypatch.setattr(
        check_licenses.metadata,
        "distributions",
        lambda: [fake_distribution],
    )

    exit_code = check_licenses.main()

    assert exit_code == 1


def test_license_detector_allows_bsd() -> None:
    assert not check_licenses.is_forbidden_gpl(
        "License-Expression",
        "BSD-3-Clause",
    )