from pathlib import Path, PurePosixPath

import pytest

from environment_store.formats.infer import Format, infer_format


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", Format.DOTENV),
        (".env.local", Format.DOTENV),
        (".env.production", Format.DOTENV),
        ("config/.env", Format.DOTENV),
        ("staging.env", Format.DOTENV),
        ("vars.json", Format.JSON),
        ("dir/vars.JSON", Format.JSON),
        (".env.json", Format.JSON),
        ("vars.toml", Format.TOML),
        (".env.toml", Format.TOML),
        ("Vars.Toml", Format.TOML),
    ],
)
def test_infer_format_maps_extensions_to_formats(path: str, expected: Format) -> None:
    assert infer_format(path) is expected


@pytest.mark.parametrize("path", ["vars.yaml", "vars", "README.md", "env", "my.environment"])
def test_infer_format_returns_none_for_unknown_extensions(path: str) -> None:
    assert infer_format(path) is None


def test_infer_format_accepts_path_objects() -> None:
    assert infer_format(Path("a") / ".env") is Format.DOTENV
    assert infer_format(PurePosixPath("a/b.toml")) is Format.TOML


def test_format_values_are_the_cli_type_names() -> None:
    assert [str(member) for member in Format] == ["dotenv", "json", "toml"]
