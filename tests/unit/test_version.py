from importlib.metadata import version

import environment_store


def test_version_matches_installed_distribution_metadata() -> None:
    assert environment_store.__version__ == version("environment-store")


def test_version_is_the_current_release() -> None:
    assert environment_store.__version__.startswith("2.1.0")
