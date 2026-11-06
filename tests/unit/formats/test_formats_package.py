from environment_store import formats
from environment_store.formats import dotenv, infer, json_format, shell, toml_format


def test_formats_package_exposes_the_format_modules_and_inference() -> None:
    assert formats.Format is infer.Format
    assert formats.infer_format is infer.infer_format
    assert formats.posix_exports is shell.posix_exports
    assert (formats.dotenv, formats.json_format, formats.toml_format) == (
        dotenv,
        json_format,
        toml_format,
    )
    assert set(formats.__all__) == {
        "Format",
        "dotenv",
        "infer_format",
        "json_format",
        "posix_exports",
        "toml_format",
    }
