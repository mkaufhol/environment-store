"""File format names and inference from file names."""

import os
from enum import StrEnum
from pathlib import PurePath

__all__ = ["Format", "infer_format"]


class Format(StrEnum):
    """The file formats of `import` and `export`; the values are the `-t` names."""

    DOTENV = "dotenv"
    JSON = "json"
    TOML = "toml"


def infer_format(path: str | os.PathLike[str]) -> Format | None:
    """Infer a file format from a file name.

    `.json` and `.toml` (case-insensitive) win over the dotenv rule, so `.env.json` is JSON.
    Names starting with `.env` (`.env`, `.env.local`, …) and the `.env` suffix are dotenv.

    Args:
        path: The file path; only its name is inspected.

    Returns:
        The inferred format, or `None` if the name does not determine one.
    """
    pure = PurePath(path)
    suffix = pure.suffix.lower()
    if suffix == ".json":
        return Format.JSON
    if suffix == ".toml":
        return Format.TOML
    if pure.name.lower().startswith(".env") or suffix == ".env":
        return Format.DOTENV
    return None
